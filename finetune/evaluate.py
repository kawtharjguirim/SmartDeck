"""Mesure de la qualité de rédaction d'un ensemble de decks (FT-03).

Pour chaque deck (output/<dossier>/*.deck.json + .work.json) :
  - puces probablement inventées (mots absents de la source)
  - notes « méta » (« Cette slide… »)
  - puces et notes avec un chiffre absent de la source
  - JSON valide, nombre de slides

Usage : python finetune/evaluate.py output/acceptance
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quality.faithfulness import is_meta_note, is_unsupported, source_vocabulary  # noqa: E402
from quality.numbers import source_numbers, unsupported_numbers  # noqa: E402
from schemas import Deck, Document  # noqa: E402


def evaluate_folder(folder: Path, verbose: bool = True) -> dict:
    totals = {"decks": 0, "slides": 0, "puces": 0, "puces_inventees": 0, "notes_meta": 0,
              "chiffres_absents": 0}
    examples = {"puces_inventees": [], "notes_meta": []}
    for deck_file in sorted(folder.glob("*.deck.json")):
        work_file = Path(str(deck_file).replace(".deck.json", ".work.json"))
        if not work_file.exists():
            continue
        deck = Deck.model_validate_json(deck_file.read_text(encoding="utf-8"))
        document = Document.model_validate(json.loads(work_file.read_text(encoding="utf-8"))["document"])
        vocab, known = source_vocabulary(document.full_text()), source_numbers(document)
        totals["decks"] += 1
        for slide in deck.slides[1:]:  # la slide de titre a des notes générées par le code
            totals["slides"] += 1
            totals["puces"] += len(slide.bullets)
            for b in slide.bullets:
                if is_unsupported(b, vocab):
                    totals["puces_inventees"] += 1
                    examples["puces_inventees"].append(f"{deck_file.stem}: {b}")
            if is_meta_note(slide.notes):
                totals["notes_meta"] += 1
                examples["notes_meta"].append(f"{deck_file.stem}: {slide.notes[:80]}")
            totals["chiffres_absents"] += len(
                unsupported_numbers(" ".join(slide.bullets) + " " + slide.notes, known))
    rates = {
        "puces_inventees_%": round(100 * totals["puces_inventees"] / max(totals["puces"], 1), 1),
        "notes_meta_%": round(100 * totals["notes_meta"] / max(totals["slides"], 1), 1),
    }
    if verbose:
        print(json.dumps(totals | rates, ensure_ascii=False, indent=2))
        for kind, items in examples.items():
            print(f"\n{kind} ({len(items)}) :")
            for item in items[:12]:
                print(f"  - {item}")
    return totals | rates | {"exemples": examples}


if __name__ == "__main__":
    evaluate_folder(Path(sys.argv[1] if len(sys.argv) > 1 else "output/acceptance"))
