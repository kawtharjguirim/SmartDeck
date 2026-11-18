"""Étape 7 : vérifie que chaque slide a des puces et des notes orateur.

Usage :
  python test_writer.py                    → test sur samples/rapport_verdi.pdf (6 slides)
  python test_writer.py fichier.pdf [n]    → plan + rédaction de n slides

Le Deck produit est enregistré dans output/<nom>.deck.json (réutilisé à l'étape 8).
"""
import sys
from pathlib import Path

import config
from ingest import load_document
from planner import plan
from schemas import Deck
from writer import similarity, write

SAMPLES = Path(__file__).resolve().parent / "samples"


def show(deck: Deck) -> None:
    print(f"\n« {deck.title} » ({deck.language}) — {len(deck.slides)} slides")
    for i, s in enumerate(deck.slides, 1):
        print(f"\n  {i}. [{s.layout}] {s.title}")
        for b in s.bullets:
            print(f"     • {b}  ({len(b.split())} mots)")
        print(f"     🗣 {s.notes}")


def check(deck: Deck) -> list[str]:
    problems = []
    for i, s in enumerate(deck.slides, 1):
        if not s.notes.strip():
            problems.append(f"slide {i} : pas de notes orateur")
        if s.layout != "title" and not 3 <= len(s.bullets) <= 5:
            problems.append(f"slide {i} : {len(s.bullets)} puces")
    bullets = [b for s in deck.slides for b in s.bullets]
    dups = sum(1 for i, a in enumerate(bullets) for b in bullets[:i]
               if similarity(a, b) >= config.DUPLICATE_THRESHOLD)
    print(f"Puces en doublon : {dups} sur {len(bullets)}")
    if dups > len(bullets) // 10:  # tolérance : 10 %
        problems.append(f"{dups} puces en doublon")
    return problems


def run(path: Path, n_slides: int) -> Deck:
    doc = load_document(path)
    print(f"Modèles : plan {config.PLAN_MODEL}, rédaction {config.WRITE_MODEL}")
    planned = plan(doc, n_slides=n_slides)
    print(f"Plan : {planned.outline.slide_count()} slides en {planned.seconds:.1f} s")
    written = write(planned.outline, doc)
    show(written.deck)

    words = [len(b.split()) for s in written.deck.slides for b in s.bullets]
    print(f"\nRédaction en {written.seconds:.1f} s — moyenne {sum(words) / len(words):.1f} mots par puce")
    for w in planned.warnings + written.warnings:
        print(f"  ⚠ {w}")

    out = config.OUTPUT_DIR / f"{path.stem}.deck.json"
    out.write_text(written.deck.model_dump_json(indent=2), encoding="utf-8")
    print(f"Deck enregistré : {out}")
    return written.deck


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 10)
    else:
        # Minimum autorisé (5) pour un PDF de 3 courtes pages (~250 mots).
        deck = run(SAMPLES / "rapport_verdi.pdf", 5)
        problems = check(deck)
        if problems:
            raise SystemExit("\nÉCHEC :\n  - " + "\n  - ".join(problems))
        print("\nOK : chaque slide a des puces et des notes orateur")
