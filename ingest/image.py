"""Ingestion d'une image (étape 10 ; FR-01, FR-09) : OCR + modèle vision.

1. OCR (Tesseract, ingest/ocr.py) : le texte présent dans l'image.
2. Vision (qwen2.5vl:3b) : type d'image, description, et pour un graphique
   ses valeurs lisibles ; pour un schéma, ses étapes.
3. Contrôle croisé : chaque valeur lue par la vision est cherchée dans le texte OCR.
4. Le modèle vision est déchargé de la VRAM avant le plan et la rédaction.

Tout ce qui vient de la vision est marqué needs_review (« valeurs à vérifier »).
"""
import io
import math
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

import config
from llm.client import LLMError, generate_structured, unload
from quality.numbers import extract_numbers
from schemas import Block, Document, ImageAnalysis

from .language import detect_language
from .ocr import ocr_page
from .pdf import _clean, build_blocks
from .router import IngestError

LANG_NAMES = {"fr": "français", "en": "anglais", "ar": "arabe"}
MIN_OCR_CHARS = 40  # en dessous, le texte OCR ne suffit pas à détecter la langue

SYSTEM = (
    "Tu analyses une image pour en tirer le contenu d'une présentation. "
    "Tu réponds uniquement en JSON. Tu ne recopies que ce qui est lisible dans l'image : "
    "si une valeur n'est pas lisible, tu ne l'inventes pas."
)


def _open(path: Path) -> Image.Image:
    size_mb = path.stat().st_size / 1_048_576
    if size_mb > config.MAX_IMAGE_MB:
        raise IngestError(f"{path.name} : {size_mb:.1f} Mo, limite {config.MAX_IMAGE_MB} Mo")
    try:
        image = Image.open(path)
        image.load()
    except (UnidentifiedImageError, OSError) as e:
        raise IngestError(f"{path.name} : image illisible ({e})") from e
    image = ImageOps.exif_transpose(image)  # photo prise en mode portrait
    if image.mode in ("RGBA", "LA", "P"):  # transparence → fond blanc
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return image.convert("RGB")


def _ocr(image: Image.Image) -> list[dict]:
    # Tesseract lit mal les petits caractères : on agrandit les images étroites.
    factor = max(1, math.ceil(config.OCR_MIN_WIDTH / image.width))
    factor = min(factor, 3)
    if factor > 1:
        image = image.resize((image.width * factor, image.height * factor), Image.LANCZOS)
    items, _ = ocr_page(image, dpi=72 * factor)  # tailles en « points » de l'image d'origine
    for it in items:
        if it["type"] == "para":
            it["text"] = _clean(it["text"])
        it["ocr"] = True
    return [it for it in items if it["text"]]


def _png(image: Image.Image) -> bytes:
    small = image.copy()
    small.thumbnail((config.VISION_MAX_SIDE, config.VISION_MAX_SIDE))
    buffer = io.BytesIO()
    small.save(buffer, format="PNG")
    return buffer.getvalue()


def analyse(image: Image.Image, language: str, ocr_text: str) -> ImageAnalysis:
    hint = f"\n\nTexte lu par OCR dans l'image (peut contenir des erreurs) :\n{ocr_text[:2000]}" \
        if ocr_text else ""
    prompt = (
        f"Analyse cette image. Rédige title et description en {LANG_NAMES.get(language, language)}.\n"
        "- kind : chart (graphique), diagram (schéma, processus), table, text, photo ou other.\n"
        "- description : 2 à 4 phrases courtes. Ne recopie pas le texte de l'image.\n"
        "- Graphique : chart_kind, labels et values (une valeur par étiquette, lue sur "
        "l'image), unit.\n"
        "- Schéma : steps, les étapes dans l'ordre.\n"
        "- Sinon : labels, values et steps restent des listes vides." + hint
    )
    return generate_structured(prompt, ImageAnalysis, system=SYSTEM,
                               model=config.VISION_MODEL, images=[_png(image)],
                               retries=config.VISION_RETRIES,
                               max_tokens=config.VISION_MAX_TOKENS)


def _figure_text(a: ImageAnalysis) -> str:
    lines = [a.title, a.description]
    if a.labels:
        unit = f" ({a.unit})" if a.unit else ""
        lines += ["", f"| Élément | Valeur{unit} |", "|---|---|"]
        lines += [f"| {label} | {value:g} |" for label, value in zip(a.labels, a.values)]
    if a.steps:
        lines.append("Étapes : " + " → ".join(a.steps))
    return "\n".join(lines)


def _cross_check(a: ImageAnalysis, ocr_text: str) -> list[str]:
    """Valeurs lues par la vision mais absentes du texte OCR → à vérifier."""
    if not a.values:
        return []
    seen = set()
    for _, candidates in extract_numbers(ocr_text):
        seen |= candidates
    missing = [f"{label} = {value:g}" for label, value in zip(a.labels, a.values)
               if round(value, 6) not in seen]
    confirmed = len(a.values) - len(missing)
    notes = [f"Graphique : {confirmed}/{len(a.values)} valeurs confirmées par l'OCR"]
    if missing:
        notes.append("Valeurs lues par la vision seulement, à vérifier : " + ", ".join(missing))
    return notes


def load_image(path: str | Path) -> Document:
    path = Path(path)
    image = _open(path)

    items = _ocr(image)
    ocr_blocks = build_blocks([items], path.name)
    ocr_text = "\n".join(b.content for b in ocr_blocks)
    language = detect_language(ocr_text) if len(ocr_text) >= MIN_OCR_CHARS \
        else config.DEFAULT_LANGUAGE

    notes: list[str] = []
    try:
        analysis = analyse(image, language, ocr_text)
    except LLMError as e:
        if not ocr_blocks:
            raise IngestError(f"{path.name} : ni texte OCR ni analyse vision ({e})") from e
        analysis = None
        notes.append(f"Analyse vision impossible, texte OCR seul : {e}")
    finally:
        try:
            unload(config.VISION_MODEL)  # libère la VRAM pour le plan et la rédaction
        except Exception:
            pass

    blocks: list[Block] = []
    if analysis and analysis.kind == "text" and ocr_blocks:
        # Image de texte : l'OCR est la source fiable ; la vision ferait doublon.
        notes.append(f"Image analysée par {config.VISION_MODEL} : text (texte OCR conservé)")
        analysis = None
    elif analysis:
        blocks.append(Block(kind="figure", content=_figure_text(analysis), page=1,
                            source=path.name, needs_review=True))
        notes.append(f"Image analysée par {config.VISION_MODEL} : {analysis.kind}")
        notes += _cross_check(analysis, ocr_text)
    # Pour un graphique ou un schéma, le texte OCR (graduations, étiquettes éparses)
    # brouillerait le plan : la description de la vision le remplace.
    if not analysis or analysis.kind not in ("chart", "diagram"):
        blocks += ocr_blocks

    full = "\n".join(b.content for b in blocks)
    if len(full) >= MIN_OCR_CHARS:
        language = detect_language(full)
    return Document(origin="image", language=language, blocks=blocks, notes=notes)
