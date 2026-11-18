"""Routeur : détecte le type d'une entrée (CDC section 7, étape 1 ; FR-01).

On se fie d'abord à l'en-tête du fichier (les « magic bytes »), puis à
l'extension. Un fichier .pdf renommé en .txt sera donc bien vu comme un PDF.
"""
from pathlib import Path
from typing import Literal

InputKind = Literal["text", "pdf", "image"]

TEXT_EXT = {".txt", ".md", ".markdown"}
PDF_EXT = {".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


class IngestError(ValueError):
    """Entrée refusée : format inconnu, fichier trop gros, vide…"""


def sniff_header(head: bytes) -> InputKind | None:
    """Type d'après les premiers octets du fichier, ou None si inconnu."""
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if head.startswith(b"\xff\xd8\xff"):  # JPEG
        return "image"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image"
    return None


def detect_kind(path: str | Path) -> InputKind:
    path = Path(path)
    if not path.is_file():
        raise IngestError(f"Fichier introuvable : {path}")
    if path.stat().st_size == 0:
        raise IngestError(f"Fichier vide : {path.name}")

    with path.open("rb") as f:
        head = f.read(16)

    by_header = sniff_header(head)
    if by_header:
        return by_header

    ext = path.suffix.lower()
    if ext in TEXT_EXT:
        return "text"
    if ext in PDF_EXT or ext in IMAGE_EXT:
        # L'extension annonce un PDF/une image mais l'en-tête ne correspond pas.
        raise IngestError(f"{path.name} : contenu ne correspondant pas à l'extension {ext}")
    raise IngestError(
        f"Format non pris en charge : {ext or '(sans extension)'} "
        "(acceptés : .txt, .md, .pdf, .png, .jpg, .webp)"
    )
