"""SmartDeck : document → présentation PPTX et PDF.

Usage :
  python generate.py document.pdf                 → 10 slides, langue du document
  python generate.py document.pdf --slides 8 --lang fr
  python generate.py --deck output/x.deck.json    → reconstruit le PPTX sans rappeler le LLM
  python generate.py --deck output/x.deck.json --regen 3   → régénère la slide 3 (FR-13)
  --no-pdf                                        → sans export PDF

Sorties dans output/ :
  <nom>.pptx          la présentation (livrable principal)
  <nom>.pdf           export PDF (LibreOffice, étape 12)
  <nom>.deck.json     le contenu validé (réutilisable)
  <nom>.report.json   le rapport de génération : avertissements, chiffres à vérifier, durées
  <nom>.work.json     document et plan, pour régénérer une slide sans tout refaire

Le même code sert à l'interface Streamlit (app.py) : `progress(étape, total, message)`.
"""
import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import config
from build.pdf_export import PdfExportError, export_pdf
from build.pptx_builder import build_pptx
from ingest import IngestError, load_document, load_pasted_text
from planner import plan
from schemas import Deck, Document, Outline
from writer import rewrite_slide, write

STEPS = 5
Progress = Callable[[int, int, str], None]


def _print_progress(step: int, total: int, message: str) -> None:
    print(f"{step}/{total} {message}" if step else f"    {message}")


@dataclass
class Run:
    """Une génération : tout ce qu'il faut pour afficher, télécharger ou régénérer."""
    stem: Path            # output/<nom> (sans extension)
    document: Document
    outline: Outline
    deck: Deck
    report: dict

    def path(self, ext: str) -> Path:
        return Path(f"{self.stem}.{ext}")


def to_pdf(pptx: Path) -> tuple[str | None, list[str]]:
    """Export PDF (étape 12). Un échec n'annule pas le PPTX : il devient un avertissement."""
    try:
        pdf, tool = export_pdf(pptx)
        return str(pdf), [] if tool == "LibreOffice" else [f"PDF exporté avec {tool}"]
    except PdfExportError as e:
        return None, [f"PDF non généré : {e}"]


def safe_stem(name: str) -> str:
    """Nom de fichier sûr : lettres, chiffres, tirets (pas de chemin ni de caractères spéciaux)."""
    stem = re.sub(r"[^\w-]+", "_", Path(name).stem, flags=re.UNICODE).strip("_")
    return stem[:60] or "presentation"


def _split(warnings: list[str]) -> dict:
    return {"a_verifier": [w for w in warnings if "à vérifier" in w],
            "avertissements": [w for w in warnings if "à vérifier" not in w]}


def generate_document(document: Document, name: str, n_slides: int, language: str | None,
                      pdf: bool = True, progress: Progress = _print_progress,
                      ingestion_s: float = 0.0) -> Run:
    """Plan → rédaction → PPTX → PDF pour un Document déjà extrait."""
    timings = {"ingestion_s": round(ingestion_s, 1)}
    stem = config.OUTPUT_DIR / safe_stem(name)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    progress(2, STEPS, "Plan…")
    planned = plan(document, n_slides=n_slides, language=language)
    timings["plan_s"] = round(planned.seconds, 1)
    progress(2, STEPS, f"Plan : {planned.outline.slide_count()} slides en {planned.seconds:.0f} s")

    written = write(planned.outline, document,
                    on_slide=lambda i, n, title: progress(3, STEPS, f"Rédaction {i}/{n} : {title}"))
    timings["redaction_s"] = round(written.seconds, 1)
    progress(3, STEPS, f"Rédaction : {written.seconds:.0f} s")

    run = Run(stem, document, planned.outline, written.deck, {})
    t = time.perf_counter()
    built = build_pptx(written.deck, run.path("pptx"), source=name)
    timings["pptx_s"] = round(time.perf_counter() - t, 1)
    progress(4, STEPS, f"PPTX : {built.path}")

    pdf_path, pdf_warnings = None, []
    if pdf:
        progress(5, STEPS, "PDF…")
        t = time.perf_counter()
        pdf_path, pdf_warnings = to_pdf(built.path)
        timings["pdf_s"] = round(time.perf_counter() - t, 1)
        progress(5, STEPS, f"PDF : {pdf_path or 'échec'}")

    warnings = planned.warnings + written.warnings + built.warnings + pdf_warnings
    run.report = {
        "source": name,
        "date": datetime.now().isoformat(timespec="seconds"),
        "models": {"plan": config.PLAN_MODEL, "redaction": config.WRITE_MODEL}
                  | ({"vision": config.VISION_MODEL} if document.origin == "image" else {}),
        "slides_demandees": n_slides,
        "slides_produites": len(written.deck.slides),
        "langue": written.deck.language,
        "durees": timings | {"total_s": round(sum(timings.values()), 1)},
        "ingestion": {
            "origine": document.origin,
            "remarques": document.notes,
            # Blocs lus par OCR peu sûr ou par le modèle vision : à relire dans la source.
            "blocs_a_verifier": [b.content[:200] for b in document.blocks if b.needs_review],
        },
        **_split(warnings),
        "fichiers": {"pptx": str(built.path), "pdf": pdf_path, "deck": str(run.path("deck.json"))},
    }
    save(run)
    return run


def save(run: Run) -> None:
    run.path("deck.json").write_text(run.deck.model_dump_json(indent=2), encoding="utf-8")
    run.path("report.json").write_text(json.dumps(run.report, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    work = {"document": run.document.model_dump(), "outline": run.outline.model_dump()}
    run.path("work.json").write_text(json.dumps(work, ensure_ascii=False), encoding="utf-8")


def load_run(deck_file: Path) -> Run:
    """Recharge une génération (deck + document + plan) pour régénérer une slide."""
    stem = Path(str(deck_file).removesuffix(".deck.json"))
    work_file = Path(f"{stem}.work.json")
    if not work_file.exists():
        raise ValueError(f"{work_file.name} absent : régénérez la présentation complète")
    work = json.loads(work_file.read_text(encoding="utf-8"))
    report_file = Path(f"{stem}.report.json")
    report = json.loads(report_file.read_text(encoding="utf-8")) if report_file.exists() else {}
    return Run(stem, Document.model_validate(work["document"]),
               Outline.model_validate(work["outline"]),
               Deck.model_validate_json(deck_file.read_text(encoding="utf-8")), report)


def generate(source: Path, n_slides: int, language: str | None, pdf: bool = True,
             progress: Progress = _print_progress) -> Run:
    progress(1, STEPS, "Ingestion…")
    t = time.perf_counter()
    document = load_document(source)
    seconds = time.perf_counter() - t
    progress(1, STEPS, f"Ingestion : {len(document.blocks)} blocs "
                       f"({document.origin}, {document.language})")
    for note in document.notes:
        progress(0, STEPS, f"ℹ {note}")
    return generate_document(document, source.name, n_slides, language, pdf, progress, seconds)


def generate_text(text: str, n_slides: int, language: str | None, pdf: bool = True,
                  progress: Progress = _print_progress, name: str = "texte_colle") -> Run:
    """FR-01 : texte collé (limite 50 000 caractères)."""
    if len(text) > config.MAX_TEXT_CHARS:
        raise IngestError(f"texte de {len(text)} caractères, limite {config.MAX_TEXT_CHARS}")
    if not text.strip():
        raise IngestError("texte vide")
    progress(1, STEPS, "Ingestion du texte collé…")
    document = load_pasted_text(text)
    return generate_document(document, name, n_slides, language, pdf, progress)


def regenerate_slide(run: Run, index: int, pdf: bool = True) -> list[str]:
    """FR-13 : réécrit la slide `index` (1 = après le titre), reconstruit PPTX et PDF."""
    old_title = run.deck.slides[index].title
    slide, warnings = rewrite_slide(run.outline, run.document, run.deck, index)
    run.deck.slides[index] = slide
    built = build_pptx(run.deck, run.path("pptx"), source=run.report.get("source", ""))
    warnings += built.warnings
    if pdf:
        pdf_path, pdf_warnings = to_pdf(built.path)
        warnings += pdf_warnings
        run.report.setdefault("fichiers", {})["pdf"] = pdf_path
    # Les avertissements de l'ancienne version de la slide sont remplacés.
    kept = [w for w in run.report.get("a_verifier", []) + run.report.get("avertissements", [])
            if f"« {old_title} »" not in w]
    run.report |= _split(kept + warnings)
    run.report.setdefault("regenerations", []).append(
        {"slide": index + 1, "date": datetime.now().isoformat(timespec="seconds")})
    save(run)
    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère une présentation PPTX à partir d'un document.")
    parser.add_argument("source", nargs="?", type=Path,
                        help="fichier .txt, .md, .pdf, .png, .jpg ou .webp")
    parser.add_argument("--slides", type=int, default=config.DEFAULT_SLIDES,
                        help=f"nombre de slides ({config.MIN_SLIDES} à {config.MAX_SLIDES})")
    parser.add_argument("--lang", choices=["fr", "en", "ar"], help="langue (par défaut : celle du document)")
    parser.add_argument("--deck", type=Path, help="reconstruire le PPTX depuis un .deck.json")
    parser.add_argument("--regen", type=int, metavar="N",
                        help="avec --deck : régénérer seulement la slide N (2 = première après le titre)")
    parser.add_argument("--no-pdf", action="store_true", help="ne pas exporter le PDF")
    args = parser.parse_args()

    if args.deck and args.regen:
        try:
            run = load_run(args.deck)
            warnings = regenerate_slide(run, args.regen - 1, pdf=not args.no_pdf)
        except (ValueError, IndexError) as e:
            sys.exit(f"Erreur : {e}")
        print(f"Slide {args.regen} régénérée : {run.deck.slides[args.regen - 1].title}")
        for b in run.deck.slides[args.regen - 1].bullets:
            print(f"  - {b}")
        for w in warnings:
            print(f"  ⚠ {w}")
        return
    if args.deck:
        deck = Deck.model_validate_json(args.deck.read_text(encoding="utf-8"))
        out = args.deck.with_name(args.deck.name.replace(".deck.json", ".pptx"))
        result = build_pptx(deck, out)
        print(f"PPTX : {result.path}")
        warnings = result.warnings
        if not args.no_pdf:
            pdf_path, pdf_warnings = to_pdf(result.path)
            print(f"PDF : {pdf_path or 'échec'}")
            warnings += pdf_warnings
        for w in warnings:
            print(f"  ⚠ {w}")
        return
    if not args.source:
        parser.error("indiquez un fichier source (ou --deck)")

    try:
        report = generate(args.source, args.slides, args.lang, pdf=not args.no_pdf).report
    except (IngestError, ValueError) as e:
        sys.exit(f"Erreur : {e}")

    print(f"\nTerminé en {report['durees']['total_s']:.0f} s — "
          f"{report['slides_produites']} slides pour {report['slides_demandees']} demandées")
    for w in report["a_verifier"]:
        print(f"  🔎 {w}")
    for w in report["avertissements"]:
        print(f"  ⚠ {w}")


if __name__ == "__main__":
    main()
