"""Étape 6 : vérifie que le planner produit un plan et un Deck valides.

Usage :
  python test_planner.py                       → tests sur samples/
  python test_planner.py fichier.pdf [n]       → plan de n slides (10 par défaut)
"""
import sys
from pathlib import Path

from ingest import load_document
from planner import PlanResult, plan

SAMPLES = Path(__file__).resolve().parent / "samples"


def show(result: PlanResult) -> None:
    o = result.outline
    print(f"\n« {o.title} » ({o.language}) — {o.slide_count()} slides pour "
          f"{result.requested} demandées, {result.attempts} appel(s) au modèle, "
          f"{result.seconds:.1f} s")
    n = 1
    print(f"  1. [title] {o.title}")
    for section in o.sections:
        print(f"  ── {section.title}")
        for s in section.slides:
            n += 1
            pages = ",".join(map(str, s.source_pages)) or "-"
            print(f"  {n}. [{s.layout}] {s.title}  (p.{pages})")
            print(f"       → {s.key_point}")
    for w in result.warnings:
        print(f"  ⚠ {w}")


def check(name: str, n_slides: int) -> list[str]:
    doc = load_document(SAMPLES / name)
    result = plan(doc, n_slides=n_slides)
    show(result)
    deck = result.outline.to_deck()  # lève une erreur si le Deck est invalide
    problems = []
    if abs(len(deck.slides) - n_slides) > 1:  # CA-05
        problems.append(f"{name} : {len(deck.slides)} slides au lieu de {n_slides} (±1)")
    if result.outline.language != "fr":
        problems.append(f"{name} : langue {result.outline.language}")
    if any("<" in s.title or "<" in s.key_point for s in result.outline.planned_slides()):
        problems.append(f"{name} : texte de l'exemple recopié")
    return problems


if __name__ == "__main__":
    if len(sys.argv) > 1:
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        show(plan(load_document(sys.argv[1]), n_slides=n))
    else:
        problems = check("rapport_verdi.md", 5) + check("rapport_verdi.pdf", 7)
        if problems:
            raise SystemExit("\nÉCHEC :\n  - " + "\n  - ".join(problems))
        print("\nOK : plans valides, Deck valides, nombre de slides respecté")
