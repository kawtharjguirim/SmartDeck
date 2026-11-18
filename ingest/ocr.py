"""OCR des pages scannées avec Tesseract (étape 9).

Une seule fonction publique, `ocr_page`, pour pouvoir changer de moteur plus tard
(PaddleOCR pour les photos, étape 10) sans toucher au reste de l'ingestion.

Pour chaque page :
1. OSD (Tesseract) : détecte l'écriture (latine / arabe) et une éventuelle rotation ;
2. OCR avec la langue adaptée ;
3. regroupement des mots en paragraphes, avec position, hauteur du texte et confiance.
"""
import os
import re
import shutil
import statistics
from pathlib import Path

import pytesseract
from PIL import Image

import config

from .router import IngestError


def _tesseract() -> str:
    cmd = config.TESSERACT_CMD
    if Path(cmd).exists():
        return cmd
    found = shutil.which("tesseract")
    if found:
        return found
    raise IngestError(
        "Tesseract introuvable : installez-le ou indiquez son chemin dans "
        "la variable SMARTDECK_TESSERACT."
    )


def _config(psm: int) -> str:
    return f"--psm {psm}"


def _setup() -> None:
    pytesseract.pytesseract.tesseract_cmd = _tesseract()
    # Dossier des langues via l'environnement : --tessdata-dir supporte mal les guillemets
    # et les espaces une fois passé par pytesseract sous Windows.
    os.environ["TESSDATA_PREFIX"] = str(config.TESSDATA_DIR)


def detect_script(image: Image.Image) -> tuple[str, int]:
    """(écriture, rotation en degrés) d'après l'OSD de Tesseract. Latin/0 si incertain."""
    try:
        osd = pytesseract.image_to_osd(image, config=_config(0),
                                       output_type=pytesseract.Output.DICT)
        return osd.get("script", "Latin"), int(osd.get("rotate", 0))
    except pytesseract.TesseractError:  # trop peu de texte pour décider
        return "Latin", 0


def _join_lines(lines: list[str]) -> str:
    text = ""
    for line in lines:
        if text.endswith("-") and line[:1].islower():  # « dévelop- pement »
            text = text[:-1] + line
        else:
            text = f"{text} {line}".strip()
    return re.sub(r"\s+", " ", text)


def ocr_page(image: Image.Image, dpi: int) -> tuple[list[dict], str]:
    """OCR d'une page. Renvoie (éléments, langue Tesseract utilisée).

    Paragraphe : {"type": "para", "text", "y", "size" (pt), "bold", "chars", "conf"} ;
    tableau : {"type": "table", "text" (Markdown), "y", "conf"}
    — le même format que la lecture des PDF natifs, plus la confiance (0-100).
    """
    _setup()
    image = image.convert("L")  # niveaux de gris
    script, rotate = detect_script(image)
    if rotate:
        image = image.rotate(-rotate, expand=True)  # OSD : rotation horaire à appliquer
    lang = "ara" if script == "Arabic" else config.OCR_LATIN_LANGS

    data = pytesseract.image_to_data(image, lang=lang, config=_config(3),
                                     output_type=pytesseract.Output.DICT)
    lines = _lines(data)
    table_lines = _find_tables(lines)
    items = [_table_item(rows, dpi) for rows in table_lines]
    in_table = {id(line) for rows in table_lines for line in rows}

    paras: dict[tuple, list[dict]] = {}
    for line in lines:
        if id(line) not in in_table:
            paras.setdefault(line["par"], []).append(line)
    for par_lines in paras.values():
        # Titre collé à son paragraphe : première ligne nettement plus haute que la suite.
        first, rest = par_lines[0], par_lines[1:]
        if rest and first["height"] >= TITLE_RATIO * statistics.median(l["height"] for l in rest):
            items.append(_para_item([first], dpi))
            par_lines = rest
        items.append(_para_item(par_lines, dpi))
    return sorted((it for it in items if it["text"]), key=lambda it: it["y"]), lang


TITLE_RATIO = 1.2   # ligne 20 % plus haute que le paragraphe → titre
CELL_GAP = 1.5      # écart entre deux mots > 1,5 × hauteur de ligne → nouvelle colonne
MIN_TABLE_ROWS = 3


def _lines(data: dict) -> list[dict]:
    """Regroupe les mots de Tesseract en lignes, triées de haut en bas."""
    lines: dict[tuple, dict] = {}
    for i, word in enumerate(data["text"]):
        word = word.strip()
        conf = float(data["conf"][i])
        if not word or conf < 0:
            continue
        par = (data["block_num"][i], data["par_num"][i])
        line = lines.setdefault(par + (data["line_num"][i],), {"par": par, "words": []})
        line["words"].append({"text": word, "left": data["left"][i], "top": data["top"][i],
                              "right": data["left"][i] + data["width"][i],
                              "height": data["height"][i], "conf": conf})
    for line in lines.values():
        words = sorted(line["words"], key=lambda w: w["left"])
        line["words"] = words
        line["top"] = min(w["top"] for w in words)
        line["height"] = statistics.median(w["height"] for w in words)
        cells, current = [], [words[0]]
        for prev, word in zip(words, words[1:]):
            if word["left"] - prev["right"] > CELL_GAP * line["height"]:
                cells.append(current)
                current = []
            current.append(word)
        line["cell_words"] = cells + [current]  # ordre géométrique (gauche → droite)
        line["rtl"] = _is_rtl(" ".join(w["text"] for w in words))
        line["cells"] = _cells_text(line)
    return sorted(lines.values(), key=lambda l: l["top"])


_ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")


def _is_rtl(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and len(_ARABIC.findall(text)) * 2 > len(letters)


def _words_text(words: list[dict], rtl: bool) -> str:
    """Texte dans l'ordre de lecture : de droite à gauche pour l'arabe."""
    return " ".join(w["text"] for w in (reversed(words) if rtl else words))


def _cells_text(line: dict) -> list[str]:
    cells = [_words_text(c, line["rtl"]) for c in line["cell_words"]]
    return cells[::-1] if line["rtl"] else cells


def _find_tables(lines: list[dict]) -> list[list[dict]]:
    """Suites d'au moins 3 lignes consécutives ayant le même nombre (≥ 2) de colonnes.

    La ligne juste au-dessus (souvent l'en-tête, aux colonnes plus serrées) est découpée
    selon la position des colonnes du tableau et ajoutée si elle remplit chaque colonne.
    """
    tables, run = [], []
    for line in lines + [{"cells": []}]:  # sentinelle pour clore la dernière suite
        n = len(line["cells"])
        if n >= 2 and (not run or n == len(run[0]["cells"])):
            run.append(line)
            continue
        if len(run) >= MIN_TABLE_ROWS:
            tables.append(run)
        run = [line] if n >= 2 else []

    for rows in tables:
        i = lines.index(rows[0])
        if i and _split_like(lines[i - 1], rows):
            rows.insert(0, lines[i - 1])
    return tables


def _split_like(line: dict, rows: list[dict]) -> bool:
    """Découpe `line` selon les colonnes de `rows`. Vrai si chaque colonne reçoit des mots."""
    if line["top"] < rows[0]["top"] - 3 * rows[0]["height"]:  # trop loin : pas l'en-tête
        return False
    n = len(rows[0]["cells"])
    starts = [min(w["left"] for r in rows for w in r["cell_words"][j]) for j in range(n)]
    tolerance = rows[0]["height"]
    cells = [[] for _ in range(n)]
    for word in line["words"]:
        j = max((k for k in range(n) if starts[k] <= word["left"] + tolerance), default=0)
        cells[j].append(word)
    if not all(cells):
        return False
    line["cell_words"] = cells
    line["cells"] = _cells_text(line)
    return True


def _table_item(rows: list[dict], dpi: int) -> dict:
    md = ["| " + " | ".join(r["cells"]) + " |" for r in rows]
    md.insert(1, "|" + "---|" * len(rows[0]["cells"]))  # 1re ligne = en-tête
    confs = [w["conf"] for r in rows for w in r["words"]]
    return {"type": "table", "text": "\n".join(md), "y": rows[0]["top"] * 72 / dpi,
            "conf": statistics.mean(confs)}


def _para_item(lines: list[dict], dpi: int) -> dict:
    text = _join_lines([_words_text(l["words"], l["rtl"]) for l in lines])
    words = [w for l in lines for w in l["words"]]
    return {
        "type": "para",
        "text": text,
        "y": lines[0]["top"] * 72 / dpi,
        # Hauteur médiane des mots, en points : sert à repérer les titres.
        "size": statistics.median(w["height"] for w in words) * 72 / dpi,
        "bold": False,  # Tesseract ne détecte pas le gras
        "chars": len(text),
        "conf": statistics.mean(w["conf"] for w in words),
    }
