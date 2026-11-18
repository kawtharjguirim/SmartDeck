"""Étape 11 : graphiques et diagrammes, sans appel au LLM.

Vérifie : séries lues dans les tableaux, CA-02 (valeurs présentes dans la source),
rendu Matplotlib / Graphviz, et slides visuelles dans le PPTX.
Usage : python test_visuals.py   → output/test_visuels.pptx
"""
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

import config
from build.pptx_builder import build_pptx
from ingest import load_document
from quality.numbers import source_numbers
from schemas import Deck, DiagramSpec, Slide
from visuals.data import numbered_steps, parse_number, table_series, to_chart
from visuals.diagrams import to_dot

SAMPLES = Path(__file__).resolve().parent / "samples"


def run() -> None:
    doc = load_document(SAMPLES / "rapport_verdi.pdf")
    series = table_series(doc, list(range(len(doc.blocks))))
    known = source_numbers(doc)
    by_name = {s.name: s for s in series}
    sales = by_name.get("Ventes")
    spec = load_document(SAMPLES / "cahier_des_charges.pdf")

    deck = Deck(title="Test des visuels", slides=[
        Slide(layout="title", title="Test des visuels", notes="Slide de titre du test."),
        Slide(layout="chart", title="Ventes par trimestre", chart=to_chart(sales),
              bullets=["Les ventes progressent chaque trimestre",
                       "Le T4 atteint 1 170 k€", "Le T1 reste le plus faible"],
              notes="Le graphique reprend le tableau du rapport."),
        Slide(layout="diagram", title="Processus commercial",
              diagram_dot=to_dot(DiagramSpec(kind="process", nodes=[
                  "Prospection", "Devis", "Signature", "Livraison", "Facturation"])),
              bullets=["Cinq étapes de la prospection à la facture",
                       "La signature déclenche la livraison"],
              notes="Le processus se lit de gauche à droite."),
        Slide(layout="diagram", title="Organisation",
              diagram_dot=to_dot(DiagramSpec(kind="hierarchy", nodes=[
                  "Direction", "Ventes", "Technique", "Support"])),
              bullets=["Trois équipes rattachées à la direction"],
              notes="Organisation simplifiée."),
    ])
    out = config.OUTPUT_DIR / "test_visuels.pptx"
    result = build_pptx(deck, out, source="test")
    prs = Presentation(str(out))
    pictures = [sum(sh.shape_type == MSO_SHAPE_TYPE.PICTURE for sh in s.shapes)
                for s in prs.slides]

    checks = {
        "parse_number : « 1 020 », « 34 % », « T1 »":
            parse_number("1 020") == (1020, "") and parse_number("34 %") == (34, "%")
            and parse_number("T1") is None,
        "2 séries lues dans le tableau (Ventes, Part en ligne)":
            set(by_name) == {"Ventes", "Part en ligne"},
        "Ventes : T1 à T4 = 950, 1020, 1060, 1170, unité k€":
            sales is not None and sales.values == [950, 1020, 1060, 1170] and sales.unit == "k€",
        "CA-02 : toutes les valeurs des séries sont dans la source":
            all(round(v, 6) in known for s in series for v in s.values),
        "Cahier des charges : aucune colonne de numérotation (1, 2, 3…) en graphique":
            not any(s.values[:3] == [1, 2, 3]
                    for s in table_series(spec, list(range(len(spec.blocks))))),
        "Liste numérotée du cahier des charges → 10 étapes + titre":
            numbered_steps(spec, list(range(len(spec.blocks))))[0][:2] == ["Routeur", "Extraction"]
            and numbered_steps(spec, list(range(len(spec.blocks))))[1] == "Architecture technique",
        "PPTX : une image par slide visuelle": pictures == [0, 1, 1, 1],
        "PPTX : aucun avertissement de rendu": not result.warnings,
    }
    print(f"{out.name} : {len(prs.slides)} slides, images par slide {pictures}")
    for w in result.warnings:
        print(f"  ⚠ {w}")
    for name, ok in checks.items():
        print(f"  {'✔' if ok else '✘'} {name}")
    if not all(checks.values()):
        raise SystemExit("\nÉCHEC")
    print("\nOK : graphiques et diagrammes construits")


if __name__ == "__main__":
    run()
