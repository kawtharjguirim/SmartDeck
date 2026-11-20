"""Aperçus des thèmes (interface) : une vignette par thème, générée une fois.

Chaque vignette montre trois slides d'une présentation d'exemple fixe (titre,
puces, graphique) construite avec le vrai code (PPTX → PDF LibreOffice → PNG).
Les images sont gardées dans templates/previews/ ; elles sont refaites si le
code des thèmes change (date de modification plus récente).

Lancer `python -m build.theme_previews` pour les (re)générer à la main.
"""
import tempfile
from pathlib import Path

import pymupdf
from PIL import Image

import config
from build.pdf_export import PdfExportError, export_pdf
from build.pptx_builder import build_pptx
from build.themes import THEMES
from schemas import ChartSpec, Deck, Slide

PREVIEW_DIR = config.TEMPLATES_DIR / "previews"
SOURCES = [Path(__file__).with_name("themes.py"), Path(__file__).with_name("pptx_builder.py")]

DEMO = Deck(title="Rapport annuel 2025", language="fr", slides=[
    Slide(layout="title", title="Rapport annuel 2025", notes=""),
    Slide(title="Faits marquants", bullets=[
        "Chiffre d'affaires en hausse de 12 % sur l'année",
        "Deux nouveaux sites ouverts à Lyon et Nantes",
        "Satisfaction client stable à 91 %",
    ], notes=""),
    Slide(layout="chart", title="Ventes par trimestre", bullets=[
        "Progression régulière", "Pic au quatrième trimestre"],
        chart=ChartSpec(kind="bar", title="Ventes", labels=["T1", "T2", "T3", "T4"],
                        values=[120, 135, 150, 180], unit="k€"), notes=""),
])


def preview_path(theme: str) -> Path:
    return PREVIEW_DIR / f"{theme}.png"


def _stale(path: Path) -> bool:
    return not path.exists() or any(path.stat().st_mtime < s.stat().st_mtime for s in SOURCES)


def make_preview(theme: str, dpi: int = 40) -> Path:
    """Vignette du thème : 3 slides côte à côte."""
    out = preview_path(theme)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        pptx = Path(tmp) / f"apercu_{theme}.pptx"
        build_pptx(DEMO, pptx, source="exemple.pdf", theme=theme, logo=Path("absent"))
        pdf, _ = export_pdf(pptx, Path(tmp))
        with pymupdf.open(pdf) as doc:
            pages = [page.get_pixmap(dpi=dpi) for page in doc]
    images = [Image.frombytes("RGB", (p.width, p.height), p.samples) for p in pages]
    gap = 10
    w, h = images[0].size
    sheet = Image.new("RGB", (len(images) * w + (len(images) - 1) * gap, h), "#D1D5DB")
    for i, im in enumerate(images):
        sheet.paste(im, (i * (w + gap), 0))
    sheet.save(out)
    return out


def ensure_previews() -> dict[str, Path | None]:
    """Vignettes de tous les thèmes ; None pour un thème dont le rendu PDF a échoué."""
    result: dict[str, Path | None] = {}
    for name in THEMES:
        path = preview_path(name)
        try:
            result[name] = make_preview(name) if _stale(path) else path
        except PdfExportError:
            result[name] = path if path.exists() else None
    return result


if __name__ == "__main__":
    for name, path in ensure_previews().items():
        print(f"{name:15} {path or 'échec'}")
