"""Ingestion des entrées texte : .txt, .md et texte collé (CDC section 3)."""
import re
import unicodedata
from pathlib import Path

import config
from schemas import Block, Document

from .language import detect_language
from .router import IngestError

_HEADING = re.compile(r"^#{1,6}\s+(.*)$")
_LIST_ITEM = re.compile(r"^\d{1,2}[.)]\s+\S")


def _looks_like_heading(line: str) -> bool:
    return (len(line) <= 70 and len(line.split()) <= 9
            and not line.endswith((".", ",", ";", ":", "!", "?"))
            and not _LIST_ITEM.match(line))


def decode_bytes(data: bytes) -> str:
    """Décode en UTF-8 (avec ou sans BOM), sinon en Windows-1252."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = text.replace(" ", " ")  # espaces insécables
    return text.strip()


def parse_text(text: str, source: str) -> Document:
    """Découpe un texte en blocs : titres Markdown, tableaux, paragraphes."""
    text = normalize(text)
    if not text:
        raise IngestError(f"{source} : texte vide")
    if len(text) > config.MAX_TEXT_CHARS:
        raise IngestError(
            f"{source} : {len(text)} caractères, limite {config.MAX_TEXT_CHARS}"
        )

    blocks: list[Block] = []
    buffer: list[str] = []
    table: list[str] = []

    def flush_paragraph():
        para = " ".join(line.strip() for line in buffer).strip()
        if para:
            blocks.append(Block(kind="text", content=para, source=source))
        buffer.clear()

    def flush_table():
        if table:
            blocks.append(Block(kind="table", content="\n".join(table), source=source))
        table.clear()

    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        heading = _HEADING.match(stripped)
        if stripped.startswith("|"):  # tableau Markdown
            flush_paragraph()
            table.append(stripped)
            continue
        flush_table()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if heading:
            flush_paragraph()
            blocks.append(Block(kind="title", content=heading.group(1).strip(), source=source))
        elif not stripped:
            flush_paragraph()
        elif _LIST_ITEM.match(stripped):  # « 1. … » : un bloc par élément (diagrammes)
            flush_paragraph()
            buffer.append(stripped)
            flush_paragraph()
        elif not buffer and (nxt or not blocks) and _looks_like_heading(stripped):
            # Texte brut sans « # » : ligne courte, sans ponctuation finale, suivie de texte.
            blocks.append(Block(kind="title", content=stripped, source=source))
        else:
            buffer.append(stripped)
    flush_paragraph()
    flush_table()

    return Document(origin="text", language=detect_language(text), blocks=blocks)


def load_text_file(path: str | Path) -> Document:
    path = Path(path)
    return parse_text(decode_bytes(path.read_bytes()), source=path.name)
