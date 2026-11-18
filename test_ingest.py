"""Étape 5 : vérifie qu'un fichier texte ou PDF devient un Document.

Usage :
  python test_ingest.py                    → teste les fichiers de samples/
  python test_ingest.py mon_fichier.pdf    → affiche le Document extrait
"""
import sys
from collections import Counter
from pathlib import Path

from ingest import IngestError, load_document

SAMPLES = Path(__file__).resolve().parent / "samples"


def show(path: Path, preview: int = 8) -> None:
    doc = load_document(path)
    kinds = Counter(b.kind for b in doc.blocks)
    print(f"\n=== {path.name} → Document(origin={doc.origin}, language={doc.language}, "
          f"{len(doc.blocks)} blocs : {dict(kinds)})")
    for b in doc.blocks[:preview]:
        page = f"p.{b.page}" if b.page else "   "
        text = b.content.replace("\n", " ⏎ ")
        print(f"  [{b.kind:5}] {page:5} {text[:90]}{'…' if len(text) > 90 else ''}")
    if len(doc.blocks) > preview:
        print(f"  … et {len(doc.blocks) - preview} autres blocs")


def run_checks() -> None:
    md = load_document(SAMPLES / "rapport_verdi.md")
    pdf = load_document(SAMPLES / "rapport_verdi.pdf")
    checks = {
        "markdown : origine text": md.origin == "text",
        "markdown : un tableau détecté": any(b.kind == "table" for b in md.blocks),
        "PDF : origine pdf": pdf.origin == "pdf",
        "PDF : langue fr": pdf.language == "fr",
        "PDF : titre détecté": any(b.kind == "title" and "Rapport annuel" in b.content
                                   for b in pdf.blocks),
        "PDF : tableau détecté": any(b.kind == "table" and "1 170" in b.content
                                     for b in pdf.blocks),
        "PDF : en-têtes/pieds ignorés": not any("confidentiel" in b.content or "Page 1" in b.content
                                                for b in pdf.blocks),
        "PDF : numéros de page": all(b.page for b in pdf.blocks),
        "PDF : ligatures dépliées": any("chiffre d'affaires" in b.content for b in pdf.blocks),
    }
    # Étape 9 : « Le texte OCR apparaît dans le Document ».
    scan = load_document(SAMPLES / "rapport_verdi_scanne.pdf")
    scan_text = scan.full_text()
    checks |= {
        "Scan : origine scanned_pdf": scan.origin == "scanned_pdf",
        "Scan : langue fr": scan.language == "fr",
        "Scan : texte OCR présent": "chiffre d'affaires" in scan_text
                                    and "Lyon" in scan_text,
        "Scan : chiffres reconnus (4,2 / 12 % / 45)": all(
            n in scan_text for n in ("4,2", "12 %", "45")),
        "Scan : titre détecté": any(b.kind == "title" and "Rapport annuel" in b.content
                                    for b in scan.blocks),
        "Scan : en-têtes/pieds ignorés": not any("confidentiel" in b.content
                                                 for b in scan.blocks),
        "Scan : 3 pages": {b.page for b in scan.blocks} == {1, 2, 3},
        "Scan : tableau reconstruit": any(b.kind == "table" and "| T4 |" in b.content
                                          and b.content.startswith("| Trimestre |")
                                          for b in scan.blocks),
        "Scan : titre séparé de son paragraphe": any(
            b.kind == "title" and b.content == "Ressources humaines" for b in scan.blocks),
    }

    print()
    for name, ok in checks.items():
        print(f"  {'✔' if ok else '✘'} {name}")
    if not all(checks.values()):
        raise SystemExit("\nÉCHEC")
    print("\nOK : le texte et le PDF de test deviennent des Document")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            try:
                show(Path(arg), preview=40)
            except IngestError as e:
                print(f"\n=== {Path(arg).name} → REFUSÉ : {e}")
    else:
        for name in ("rapport_verdi.md", "rapport_verdi.pdf", "rapport_verdi_scanne.pdf"):
            show(SAMPLES / name)
        run_checks()
