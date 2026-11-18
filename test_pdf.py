"""Étape 12 : « Le PDF garde la mise en page du PPTX ».

Pour chaque output/*.deck.json : reconstruit le PPTX, l'exporte en PDF avec LibreOffice,
puis compare : nombre de pages, format 16:9, titres et puces, images des slides
visuelles, polices intégrées. Vérifie aussi le secours PowerPoint.
Usage : python test_pdf.py
"""
import re
import tempfile
import time
from pathlib import Path

import pymupdf

import config
from build import pdf_export
from build.pptx_builder import build_pptx
from schemas import Deck


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("­", "")).strip()


def check(deck: Deck, pdf: Path) -> list[str]:
    problems = []
    with pymupdf.open(pdf) as doc:
        if doc.page_count != len(deck.slides):
            problems.append(f"{doc.page_count} pages pour {len(deck.slides)} slides")
        for i, (page, slide) in enumerate(zip(doc, deck.slides), 1):
            ratio = page.rect.width / page.rect.height
            if abs(ratio - 16 / 9) > 0.01:
                problems.append(f"page {i} : format {ratio:.2f} au lieu de 16:9")
            text = _norm(page.get_text())
            missing = [t for t in [slide.title, *slide.bullets] if _norm(t) not in text]
            if missing:
                problems.append(f"page {i} : texte absent {missing}")
            if slide.layout in ("chart", "diagram") and not page.get_images():
                problems.append(f"page {i} : visuel absent")
        fonts = {f[3].split("+")[-1] for p in doc for f in p.get_fonts()}
        if not any(f.startswith(config.BRAND["font"]) for f in fonts):
            problems.append(f"police {config.BRAND['font']} non intégrée ({sorted(fonts)})")
    return problems


def run() -> None:
    decks = sorted(config.OUTPUT_DIR.glob("*.deck.json"))
    if not decks:
        raise SystemExit("Aucun output/*.deck.json : lancez d'abord generate.py")
    print(f"LibreOffice : {pdf_export.find_soffice()}")
    failures = []
    for deck_file in decks:
        deck = Deck.model_validate_json(deck_file.read_text(encoding="utf-8"))
        pptx = config.OUTPUT_DIR / deck_file.name.replace(".deck.json", ".pptx")
        build_pptx(deck, pptx, source=pptx.stem)
        t = time.perf_counter()
        pdf, tool = pdf_export.export_pdf(pptx)
        problems = check(deck, pdf)
        visuals = sum(s.layout in ("chart", "diagram") for s in deck.slides)
        print(f"  {'✔' if not problems else '✘'} {pdf.name} : {len(deck.slides)} pages, "
              f"{visuals} visuel(s), {tool}, {time.perf_counter() - t:.0f} s")
        failures += [f"{pdf.name} : {p}" for p in problems]

    # Secours : sans LibreOffice, PowerPoint (si présent) prend le relais.
    saved = (config.SOFFICE, pdf_export.STANDARD_PATHS, pdf_export.shutil.which)
    try:
        config.SOFFICE, pdf_export.STANDARD_PATHS = "absent.exe", []
        pdf_export.shutil.which = lambda _: None
        with tempfile.TemporaryDirectory() as tmp:
            deck = Deck.model_validate_json(decks[0].read_text(encoding="utf-8"))
            pptx = config.OUTPUT_DIR / decks[0].name.replace(".deck.json", ".pptx")
            pdf, tool = pdf_export.export_pdf(pptx, Path(tmp))
            problems = check(deck, pdf)
            print(f"  {'✔' if not problems else '✘'} secours sans LibreOffice : {tool}")
            failures += [f"secours {tool} : {p}" for p in problems]
    except pdf_export.PdfExportError as e:
        print(f"  – secours PowerPoint indisponible : {e}")
    finally:
        config.SOFFICE, pdf_export.STANDARD_PATHS, pdf_export.shutil.which = saved

    if failures:
        raise SystemExit("\nÉCHEC :\n  - " + "\n  - ".join(failures))
    print("\nOK : chaque PDF garde les pages, le format, les textes et les visuels du PPTX")


if __name__ == "__main__":
    run()
