"""Fidélité du texte rédigé à la source (fine-tuning, section 14).

Deux défauts mesurés, au-delà des chiffres (déjà contrôlés par quality/numbers.py) :
- détail inventé : une puce dont la plupart des mots porteurs de sens sont absents
  de la source (« hôpitaux privés » dans un rapport qui n'en parle pas) ;
- note « méta » : une note orateur qui parle de la slide au lieu de s'adresser au
  public (« Cette slide présente… »).
La mesure est approximative (mots, pas sens) mais identique avant et après
fine-tuning : elle sert à comparer, pas à juger une phrase isolée.
"""
import re
import unicodedata

# Mots-outils fréquents (fr, en) : ne disent rien du contenu.
STOPWORDS = set("""
avec dans pour par sur sous entre vers chez sans plus moins très tout tous toute toutes
leur leurs notre nos votre vos cette ces celui celle ceux elles ils nous vous
être avoir fait faire sont sera seront était ainsi aussi comme donc mais car alors
ensemble chaque autre autres même depuis lors après avant pendant encore déjà
année années également afin dont quand quel quelle quels quelles plusieurs
this that these those with from into over under about between their there where which
have has been will would could should while also more most such than then them they
very each other into your ours year years
""".split())

# Notes qui commentent la slide au lieu d'être dites au public.
_META = re.compile(
    r"^\s*(cette|ce|la|dans cette|sur cette|voici la|this|in this|on this|the)\s+"
    r"(slide|diapositive|diapo|présentation)\b", re.IGNORECASE)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def content_words(text: str) -> list[str]:
    """Mots porteurs de sens : au moins 4 lettres, hors mots-outils et nombres."""
    words = re.findall(r"[^\W\d_]{4,}", _norm(text))
    return [w for w in words if w not in STOPWORDS]


def _stem(word: str) -> str:
    return word[:6]  # « recrutement / recruter / recrutés » → « recrut »


def source_vocabulary(source_text: str) -> set[str]:
    return {_stem(w) for w in content_words(source_text)}


def support(text: str, vocabulary: set[str]) -> float:
    """Part des mots porteurs de sens de `text` présents dans la source (1.0 = tous)."""
    words = content_words(text)
    if not words:
        return 1.0
    return sum(_stem(w) in vocabulary for w in words) / len(words)


UNSUPPORTED_BELOW = 0.6  # moins de 60 % des mots dans la source → détail probablement inventé


def is_unsupported(text: str, vocabulary: set[str]) -> bool:
    return support(text, vocabulary) < UNSUPPORTED_BELOW


def is_meta_note(notes: str) -> bool:
    return bool(_META.match(notes))
