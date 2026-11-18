"""Ingestion des PDF natifs (avec couche texte) via PyMuPDF.

- Titres : repérés par une police plus grande (ou en gras) que le corps du texte.
- Tableaux : détectés par PyMuPDF (`find_tables`) et convertis en Markdown.
- En-têtes et pieds de page répétés sur chaque page : ignorés.
- Pages sans couche texte (scannées) : OCR avec Tesseract (ingest/ocr.py), page par page.
  Un PDF peut mélanger pages natives et pages scannées.
"""
import re
import statistics
from collections import Counter
from pathlib import Path

import pymupdf
from PIL import Image

import config
from schemas import Block, Document

from .language import detect_language
from .router import IngestError

# Moins de N caractères par page en moyenne → PDF considéré comme scanné.
MIN_CHARS_PER_PAGE = 50
_PAGE_NUMBER = re.compile(r"^(page\s*)?\d+(\s*(/|of|sur)\s*\d+)?$", re.IGNORECASE)


def needs_ocr(page: pymupdf.Page) -> bool:
    """Page sans (presque) aucun texte mais avec une image : c'est un scan."""
    return len(page.get_text().strip()) < MIN_CHARS_PER_PAGE and bool(page.get_images())


def _ocr(page: pymupdf.Page) -> list[dict]:
    from .ocr import ocr_page  # import à la demande : Tesseract n'est requis que pour les scans
    pix = page.get_pixmap(dpi=config.OCR_DPI, colorspace=pymupdf.csGRAY)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    items, _ = ocr_page(image, config.OCR_DPI)
    for it in items:
        if it["type"] == "para":  # les tableaux gardent leurs retours à la ligne
            it["text"] = _clean(it["text"])
        it["ocr"] = True
    return [it for it in items if it["text"]]


def _overlaps(rect: pymupdf.Rect, zones: list[pymupdf.Rect]) -> bool:
    return any(rect.intersects(z) for z in zones)


_INVISIBLE = dict.fromkeys(map(ord, "​‎‏﻿­"))  # zero-width, BOM, tiret conditionnel


def _clean(text: str) -> str:
    text = text.translate(_INVISIBLE).replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def _continues(prev: str, nxt: str) -> bool:
    """Le bloc suivant prolonge-t-il la phrase du précédent ?"""
    return not prev.endswith((".", ":", ";", "!", "?", "»")) and nxt[:1].islower()


def _cell_text(page: pymupdf.Page, bbox) -> str:
    """Texte d'une cellule, mot par mot : `table.extract()` perd les espaces sur certains PDF."""
    if bbox is None:
        return ""
    words = page.get_text("words", clip=pymupdf.Rect(bbox))
    words.sort(key=lambda w: (w[5], w[6], w[7]))  # bloc, ligne, mot : ordre de lecture
    return _clean(" ".join(w[4] for w in words))


def _continues_row(prev: list[str], row: list[str]) -> bool:
    """Ligne qui prolonge la précédente : une cellule de texte coupée sur plusieurs lignes."""
    first, prev_first = row[0], prev[0]
    return (not first
            or prev_first.endswith("-")
            or (first[:1].islower() and not prev_first.endswith((".", ":", ";"))))


def _merge_rows(rows: list[list[str]]) -> list[list[str]]:
    out = [rows[0]]
    for row in rows[1:]:
        if len(out) > 1 and len(row) == len(out[-1]) and _continues_row(out[-1], row):
            out[-1] = [(a + b if a.endswith("-") else f"{a} {b}").strip()
                       for a, b in zip(out[-1], row)]
        else:
            out.append(row)
    return out


def _table_markdown(page: pymupdf.Page, table) -> str:
    """Tableau → Markdown. Répare un en-tête fusionné (cellules vides, « Col3 ») en
    redistribuant ses mots selon la position des colonnes des lignes de données, et
    regroupe les lignes qui prolongent une cellule de texte."""
    rows = [[_cell_text(page, c) for c in row.cells] for row in table.rows]
    if not rows:
        return ""
    rows = _merge_rows(rows)
    header = rows[0]
    if len(rows) > 1 and any(not c for c in header) and len(table.rows) > 1:
        columns = [c for c in table.rows[1].cells]
        if all(columns):
            words = page.get_text("words", clip=pymupdf.Rect(table.rows[0].bbox))
            fixed = [[] for _ in columns]
            for w in sorted(words, key=lambda w: w[0]):
                center = (w[0] + w[2]) / 2
                j = next((k for k, c in enumerate(columns) if c[0] <= center <= c[2]), None)
                if j is None:  # entre deux colonnes : la plus proche
                    j = min(range(len(columns)),
                            key=lambda k: abs(center - (columns[k][0] + columns[k][2]) / 2))
                fixed[j].append(w[4])
            if all(fixed):
                header = [_clean(" ".join(ws)) for ws in fixed]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines).translate(_INVISIBLE)


def _read_page(page: pymupdf.Page) -> list[dict]:
    """Renvoie les éléments d'une page (paragraphes et tableaux) dans l'ordre de lecture."""
    items, table_zones = [], []
    try:
        for table in page.find_tables().tables:
            md = _table_markdown(page, table).strip()
            if md:
                items.append({"type": "table", "text": md, "y": table.bbox[1]})
                table_zones.append(pymupdf.Rect(table.bbox))
    except Exception:  # la détection de tableaux est une aide, pas un bloquant
        pass

    # Sans PRESERVE_LIGATURES, « ﬀ » devient « ff » (sinon « chiﬀre » ≠ « chiffre »).
    flags = (pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_LIGATURES) | pymupdf.TEXT_DEHYPHENATE
    for block in page.get_text("dict", flags=flags, sort=True)["blocks"]:
        if block.get("type") != 0 or _overlaps(pymupdf.Rect(block["bbox"]), table_zones):
            continue
        spans = [s for line in block["lines"] for s in line["spans"] if s["text"].strip()]
        if not spans:
            continue
        lines = [" ".join(s["text"].strip() for s in line["spans"] if s["text"].strip())
                 for line in block["lines"]]
        text = _clean(" ".join(l for l in lines if l))
        if not text:
            continue
        items.append({
            "type": "para",
            "text": text,
            "y": block["bbox"][1],
            "size": max(s["size"] for s in spans),
            "bold": all(s["flags"] & 16 for s in spans),
            "chars": len(text),
        })
    return sorted(items, key=lambda it: it["y"])


def load_pdf(path: str | Path) -> Document:
    path = Path(path)
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        raise IngestError(f"{path.name} : PDF illisible ({e})") from e

    with doc:
        if doc.needs_pass:
            raise IngestError(f"{path.name} : PDF protégé par mot de passe")
        if doc.page_count > config.MAX_PDF_PAGES:
            raise IngestError(
                f"{path.name} : {doc.page_count} pages, limite {config.MAX_PDF_PAGES}"
            )
        scanned = [page.number for page in doc if needs_ocr(page)]
        if len(scanned) > config.MAX_SCANNED_PAGES:
            raise IngestError(
                f"{path.name} : {len(scanned)} pages scannées, limite "
                f"{config.MAX_SCANNED_PAGES} (l'OCR est lent sur CPU)"
            )
        pages = [_ocr(page) if page.number in scanned else _read_page(page) for page in doc]

    blocks = build_blocks(pages, path.name)
    if not blocks:
        raise IngestError(f"{path.name} : aucun texte extrait")

    full = "\n".join(b.content for b in blocks)
    origin = "scanned_pdf" if len(scanned) * 2 > len(pages) else "pdf"
    return Document(origin=origin, language=detect_language(full), blocks=blocks)


def build_blocks(pages: list[list[dict]], source: str) -> list[Block]:
    """Éléments lus page par page (PDF natif ou OCR) → blocs titre / texte / tableau.

    Sert aussi pour les images (étape 10) : une image = une page OCR.
    """
    # Taille de police du corps = taille la plus fréquente, pondérée par le nombre de caractères.
    # Calculée à part pour les pages OCR : hauteur des mots en pixels ≠ taille de police.
    def body_size_of(ocr: bool) -> float:
        paras = [it for items in pages for it in items
                 if it["type"] == "para" and it.get("ocr", False) == ocr]
        weighted = [round(p["size"], 1) for p in paras for _ in range(p["chars"])]
        return statistics.mode(weighted) if weighted else 0

    body_sizes = {False: body_size_of(False), True: body_size_of(True)}

    # Textes répétés sur au moins la moitié des pages = en-têtes / pieds de page.
    repeats = Counter(t for items in pages for t in {it["text"] for it in items})
    min_repeat = max(3, len(pages) // 2)

    blocks: list[Block] = []
    for page_no, items in enumerate(pages, start=1):
        for it in items:
            text = it["text"]
            if it["type"] == "table":
                blocks.append(Block(kind="table", content=text, page=page_no, source=source,
                                    needs_review=it.get("conf", 100) < config.OCR_MIN_CONFIDENCE))
                continue
            if _PAGE_NUMBER.match(text) or (len(pages) >= 3 and repeats[text] >= min_repeat):
                continue
            body_size = body_sizes[it.get("ocr", False)]
            is_title = len(text) <= 150 and (
                it["size"] >= body_size * 1.15 or (it["bold"] and len(text) <= 80)
            )
            # OCR peu sûr : le bloc est marqué « à vérifier » (chiffres, noms propres…).
            review = it.get("conf", 100) < config.OCR_MIN_CONFIDENCE
            prev = blocks[-1] if blocks else None
            if (not is_title and prev and prev.kind == "text" and prev.page == page_no
                    and _continues(prev.content, text)):
                prev.content = f"{prev.content} {text}"  # phrase coupée sur deux blocs
                prev.needs_review = prev.needs_review or review
                continue
            blocks.append(Block(kind="title" if is_title else "text", content=text,
                                page=page_no, source=source, needs_review=review))
    return blocks
