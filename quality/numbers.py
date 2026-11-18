"""Contrôle des chiffres (FR-12, NFR-04, CA-02).

Chaque nombre écrit par le modèle doit apparaître dans le document source.
Sinon il est signalé « à vérifier » : inventé, ou calculé par le modèle.
"""
import re

from schemas import Document

# 4,2 · 1 020 · 1,020 · 12.5 · 38 — espaces fines et insécables acceptées.
_NUMBER = re.compile(r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")


def _candidates(raw: str) -> set[float]:
    """Interprétations possibles d'un nombre écrit (« 1,020 » = 1.02 ou 1020)."""
    s = re.sub(r"[   ]", "", raw)
    values = set()
    for variant in (s.replace(",", "."), s.replace(",", ""), s.replace(".", "").replace(",", ".")):
        try:
            values.add(round(float(variant), 6))
        except ValueError:
            pass
    return values


def extract_numbers(text: str) -> list[tuple[str, set[float]]]:
    return [(m.group(), _candidates(m.group())) for m in _NUMBER.finditer(text)]


def source_numbers(document: Document) -> set[float]:
    values: set[float] = set()
    for _, cands in extract_numbers(document.full_text()):
        values |= cands
    return values


def unsupported_numbers(text: str, known: set[float]) -> list[str]:
    """Nombres de `text` absents de la source (écrits tels quels, sans doublon)."""
    missing = [raw for raw, cands in extract_numbers(text) if not cands & known]
    return list(dict.fromkeys(missing))
