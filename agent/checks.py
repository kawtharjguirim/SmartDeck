"""Défauts mesurés d'une slide : ce que l'agent doit corriger, et son garde-fou.

Mesures déterministes (le code, pas le modèle) :
- chiffres absents de la source (FR-12) ;
- note orateur « méta » (« Cette slide présente… ») ;
- puce en double avec une autre slide ;
- puce peu fidèle : la plupart de ses mots porteurs de sens sont absents de la source.
Le score pondère ces défauts ; une réécriture n'est gardée que s'il ne monte pas.
"""
from dataclasses import dataclass, field

from quality.faithfulness import is_meta_note, is_unsupported, source_vocabulary
from quality.numbers import source_numbers, unsupported_numbers
from schemas import Deck, Document, Slide
from writer import similarity

import config

WEIGHTS = {"chiffres": 3, "note_meta": 2, "doublons": 2, "peu_fideles": 1}


@dataclass
class SlideIssues:
    chiffres: list[str] = field(default_factory=list)
    note_meta: bool = False
    doublons: list[str] = field(default_factory=list)
    peu_fideles: list[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        return (WEIGHTS["chiffres"] * len(self.chiffres) + WEIGHTS["note_meta"] * self.note_meta
                + WEIGHTS["doublons"] * len(self.doublons)
                + WEIGHTS["peu_fideles"] * len(self.peu_fideles))

    def describe(self) -> str:
        parts = []
        if self.chiffres:
            parts.append("chiffres absents de la source : " + ", ".join(self.chiffres))
        if self.note_meta:
            parts.append("la note orateur parle de la slide au lieu de s'adresser au public")
        if self.doublons:
            parts.append("puces répétées ailleurs : " + " | ".join(self.doublons))
        if self.peu_fideles:
            parts.append("puces peu fidèles à la source : " + " | ".join(self.peu_fideles))
        return " ; ".join(parts) or "aucun défaut mesuré"


class Checker:
    """Calcule les défauts d'une slide dans le contexte du deck et du document."""

    def __init__(self, document: Document):
        self.known = source_numbers(document)
        self.vocabulary = source_vocabulary(document.full_text())

    def slide(self, deck: Deck, index: int, slide: Slide | None = None) -> SlideIssues:
        slide = slide or deck.slides[index]
        others = [b for i, s in enumerate(deck.slides) if i not in (0, index) for b in s.bullets]
        return SlideIssues(
            chiffres=unsupported_numbers(" ".join(slide.bullets) + " " + slide.notes, self.known),
            note_meta=is_meta_note(slide.notes),
            doublons=[b for b in slide.bullets
                      if any(similarity(b, o) >= config.DUPLICATE_THRESHOLD for o in others)],
            peu_fideles=[b for b in slide.bullets if is_unsupported(b, self.vocabulary)],
        )

    def deck(self, deck: Deck) -> dict[int, SlideIssues]:
        """Défauts de chaque slide de contenu (la slide de titre est écrite par le code)."""
        return {i: self.slide(deck, i) for i in range(1, len(deck.slides))}
