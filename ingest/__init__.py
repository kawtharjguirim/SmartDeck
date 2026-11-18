"""Point d'entrée de l'ingestion : un fichier (ou un texte collé) → Document."""
from pathlib import Path

from schemas import Document

from .router import IngestError, detect_kind
from .text import load_text_file, parse_text

__all__ = ["IngestError", "load_document", "load_pasted_text"]


def load_document(path: str | Path) -> Document:
    kind = detect_kind(path)
    if kind == "text":
        return load_text_file(path)
    if kind == "pdf":
        from .pdf import load_pdf  # import à la demande : PyMuPDF n'est chargé que si besoin
        return load_pdf(path)
    from .image import load_image  # import à la demande : OCR et vision
    return load_image(path)


def load_pasted_text(text: str) -> Document:
    return parse_text(text, source="texte collé")
