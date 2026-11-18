"""Étape 10 : une image devient un Document (OCR + vision), avec ses valeurs à vérifier.

Usage :
  python test_image.py               → teste les 3 images de samples/
  python test_image.py photo.jpg     → affiche le Document extrait
"""
import sys
import time
from pathlib import Path

import config
from ingest import load_document
from samples.make_samples import PROCESS, SALES
from schemas import Document

SAMPLES = Path(__file__).resolve().parent / "samples"


def show(path: Path) -> tuple[Document, float]:
    t = time.perf_counter()
    doc = load_document(path)
    seconds = time.perf_counter() - t
    print(f"\n=== {path.name} → origin={doc.origin}, language={doc.language}, "
          f"{len(doc.blocks)} blocs, {seconds:.0f} s")
    for b in doc.blocks:
        flag = " [à vérifier]" if b.needs_review else ""
        print(f"  [{b.kind}]{flag}\n    " + b.content.replace("\n", "\n    "))
    for note in doc.notes:
        print(f"  ℹ {note}")
    return doc, seconds


def run_checks() -> None:
    chart, t1 = show(SAMPLES / "verdi_ventes.png")
    diagram, t2 = show(SAMPLES / "verdi_processus.jpg")
    note, t3 = show(SAMPLES / "verdi_note.png")

    figure = next((b for b in chart.blocks if b.kind == "figure"), None)
    chart_text = figure.content if figure else ""
    values_found = sum(f"| {label} | {value} |" in chart_text for label, value in SALES.items())
    flow = next((b.content for b in diagram.blocks if b.kind == "figure"), "")
    positions = [flow.find(step) for step in PROCESS]

    checks = {
        "Graphique : origine image": chart.origin == "image",
        "Graphique : bloc figure à vérifier": figure is not None and figure.needs_review,
        f"Graphique : valeurs lues ({values_found}/4, au moins 3)": values_found >= 3,
        "Graphique : contrôle croisé OCR dans les notes": any("confirmées par l'OCR" in n
                                                              for n in chart.notes),
        "Schéma : les 5 étapes dans l'ordre": -1 not in positions
                                             and positions == sorted(positions),
        "Texte : OCR (45 salariés, Lyon)": "45 salariés" in note.full_text()
                                          and "Lyon" in note.full_text(),
        "Texte : titre détecté": any(b.kind == "title" and "Ressources humaines" in b.content
                                     for b in note.blocks),
        "Texte : langue fr": note.language == "fr",
    }
    print(f"\nDurées : {t1:.0f} s, {t2:.0f} s, {t3:.0f} s (modèle {config.VISION_MODEL})")
    for name, ok in checks.items():
        print(f"  {'✔' if ok else '✘'} {name}")
    if not all(checks.values()):
        raise SystemExit("\nÉCHEC")
    print("\nOK : les images deviennent des Document, valeurs marquées à vérifier")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            show(Path(arg))
    else:
        run_checks()
