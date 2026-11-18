"""Outils de texte partagés (comparaison de mots-clés)."""
import re
import unicodedata


_ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")


def is_rtl(text: str) -> bool:
    """Texte majoritairement arabe (écrit de droite à gauche)."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and len(_ARABIC.findall(text)) * 2 > len(letters)


def keywords(text: str) -> set[str]:
    """Mots de plus de 3 lettres, en minuscules et sans accents."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return {w for w in re.findall(r"\w+", text) if len(w) > 3}
