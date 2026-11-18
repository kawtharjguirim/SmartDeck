"""Étape 8 : construit les PPTX à partir des Deck enregistrés à l'étape 7, puis les relit.

Usage : python test_build.py   (après test_writer.py, qui crée output/*.deck.json)
"""
from pathlib import Path

from pptx import Presentation

import config
from build.pptx_builder import build_pptx
from schemas import Deck


def check(deck: Deck, path: Path) -> list[str]:
    prs = Presentation(str(path))  # relecture : le fichier doit être valide
    problems = []
    if len(prs.slides) != len(deck.slides):
        problems.append(f"{path.name} : {len(prs.slides)} slides au lieu de {len(deck.slides)}")
    for i, (slide, data) in enumerate(zip(prs.slides, deck.slides), 1):
        if slide.shapes.title is None or slide.shapes.title.text != data.title:
            problems.append(f"{path.name} slide {i} : titre absent ou différent")
        notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        if notes != data.notes:
            problems.append(f"{path.name} slide {i} : notes orateur absentes")
        texts = " ".join(sh.text_frame.text for sh in slide.shapes if sh.has_text_frame)
        missing = [b for b in data.bullets if b not in texts]
        if missing:
            problems.append(f"{path.name} slide {i} : puces absentes {missing}")
    return problems


if __name__ == "__main__":
    decks = sorted(config.OUTPUT_DIR.glob("*.deck.json"))
    if not decks:
        raise SystemExit("Aucun output/*.deck.json : lancez d'abord test_writer.py")
    problems = []
    for deck_file in decks:
        deck = Deck.model_validate_json(deck_file.read_text(encoding="utf-8"))
        out = config.OUTPUT_DIR / deck_file.name.replace(".deck.json", ".pptx")
        result = build_pptx(deck, out, source=deck_file.name.replace(".deck.json", ""))
        print(f"{out.name} : {len(deck.slides)} slides")
        for w in result.warnings:
            print(f"  ⚠ {w}")
        problems += check(deck, out)
    if problems:
        raise SystemExit("\nÉCHEC :\n  - " + "\n  - ".join(problems))
    print("\nOK : PPTX construits et relus (titres, puces, notes orateur)")
