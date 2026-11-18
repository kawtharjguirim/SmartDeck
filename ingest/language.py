"""Détection simple de la langue (fr, en, ar), sans modèle ni réseau."""
import re

_FR = {"le", "la", "les", "des", "est", "et", "une", "du", "pour", "dans",
       "que", "qui", "sur", "avec", "au", "aux", "ce", "pas", "sont", "par"}
_EN = {"the", "and", "is", "of", "to", "in", "that", "for", "with", "on",
       "are", "this", "be", "as", "by", "it", "from", "was", "an", "or"}


def detect_language(text: str, default: str = "fr") -> str:
    sample = text[:20_000]
    letters = [c for c in sample if c.isalpha()]
    if not letters:
        return default
    arabic = sum(1 for c in letters if "؀" <= c <= "ۿ")
    if arabic / len(letters) > 0.3:
        return "ar"

    words = re.findall(r"[a-zà-ÿ]+", sample.lower())
    fr = sum(w in _FR for w in words)
    en = sum(w in _EN for w in words)
    if fr == en == 0:
        return default
    return "fr" if fr >= en else "en"
