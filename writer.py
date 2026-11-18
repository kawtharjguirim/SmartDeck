"""Étape 7 : rédige les puces et les notes orateur de chaque slide (FR-05, FR-06).

Pour chaque slide du plan, le modèle reçoit seulement les extraits utiles du
document (pages sources, sinon recherche par mots-clés). Moins de matière,
c'est moins d'occasions d'inventer. Les chiffres sont contrôlés (FR-12).
"""
import time
from dataclasses import dataclass, field
from typing import Callable

import config
from llm.client import LLMError, generate_structured, unload
from planner import LANG_NAMES
from quality.numbers import source_numbers, unsupported_numbers
from quality.text import keywords
from schemas import (Block, Deck, DiagramSpec, Document, Outline, PlannedSlide, Slide,
                     SlideContent)
from visuals.charts import format_number
from visuals.diagrams import to_dot

SYSTEM = (
    "Tu rédiges le contenu d'une slide de présentation à partir d'extraits d'un document. "
    "Tu réponds uniquement en JSON conforme au schéma, en texte simple. "
    "Tu n'utilises que les informations et les chiffres présents dans les extraits."
)

EXAMPLE = """{"bullets": ["<puce d'environ 12 mots>", "<puce d'environ 12 mots>", "<puce d'environ 12 mots>"],
 "notes": "<2 à 4 phrases que l'orateur dit pour présenter la slide>"}"""

TITLE_NOTES = {
    "fr": "Présenter le sujet : {title}. Annoncer le plan : {sections}.",
    "en": "Introduce the topic: {title}. Outline the agenda: {sections}.",
    "ar": "تقديم الموضوع: {title}. عرض محاور العرض: {sections}.",
}


@dataclass
class WriteResult:
    deck: Deck
    seconds: float
    warnings: list[str] = field(default_factory=list)


# --- Sélection des extraits ----------------------------------------------

_words = keywords


def select_context(document: Document, slide: PlannedSlide,
                   max_chars: int = config.WRITE_CONTEXT_CHARS) -> str:
    """Extraits du document pour une slide : blocs de sa section, les plus proches d'abord."""
    keywords = _words(f"{slide.title} {slide.key_point}")

    def score(b: Block) -> float:
        s = len(keywords & _words(b.content))
        if b.page and b.page in slide.source_pages:
            s += 3
        return s

    # Le planner indique les blocs de la section : on ne cherche que là.
    in_section = bool(slide.source_blocks)
    pool = [document.blocks[i] for i in slide.source_blocks] if in_section else document.blocks
    candidates = [b for b in pool if b.kind != "title"]
    ranked = sorted(candidates, key=score, reverse=True)
    chosen, total = [], 0
    for b in ranked:
        if (score(b) <= 0 and not in_section) or total + len(b.content) > max_chars:
            continue
        chosen.append(b)
        total += len(b.content)
    if not chosen:  # aucun lien évident : début du document
        chosen = candidates[:5]
    chosen.sort(key=document.blocks.index)  # remettre dans l'ordre du document
    return "\n\n".join(
        (f"[p.{b.page}] " if b.page else "") + b.content for b in chosen
    )[:max_chars]


# --- Rédaction ------------------------------------------------------------

def similarity(a: str, b: str) -> float:
    """Part de mots communs entre deux puces (0 = rien en commun, 1 = identiques)."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def _prompt(deck_title: str, slide: PlannedSlide, others: list[str], used: list[str],
            context: str, language: str, feedback: str = "", visual: str = "") -> str:
    already = "\n".join(f"- {b}" for b in used) or "(rien encore)"
    return f"""Rédige le contenu d'une slide en {LANG_NAMES.get(language, language)}.

Présentation : {deck_title}
Titre de la slide : {slide.title}
Idée principale : {slide.key_point}
Autres slides de la présentation : {"; ".join(others)}
{visual}
Déjà dit dans les slides précédentes (NE PAS répéter ces informations) :
{already}

Règles :
- 3 à 5 puces, environ 12 mots chacune, sans numérotation ni tiret au début.
- Les puces portent uniquement sur le titre et l'idée principale de cette slide.
- Chaque puce apporte une information nouvelle, tirée des extraits.
- N'écris aucun chiffre absent des extraits ; ne fais pas de calcul.
- Notes orateur : 2 à 4 phrases que l'orateur dit directement au public.
  Ne commence pas par « Cette slide » et ne parle pas des notes elles-mêmes.
{feedback}
Format attendu (contenu à remplacer) :
{EXAMPLE}

Extraits du document :
\"\"\"
{context}
\"\"\""""


def write_slide(document: Document, deck_title: str, slide: PlannedSlide,
                others: list[str], used: list[str], language: str, known: set[float],
                visual: str = "") -> tuple[SlideContent, list[str]]:
    """Rédige une slide, avec contrôle des chiffres (FR-12) et des répétitions."""
    context = select_context(document, slide)
    feedback, best = "", None
    for _ in range(config.WRITE_RETRIES + 1):
        content = generate_structured(
            _prompt(deck_title, slide, others, used, context, language, feedback, visual),
            SlideContent, system=SYSTEM, model=config.WRITE_MODEL,
        )
        # Puces trop proches de ce qui a déjà été dit : écartées.
        fresh = [b for b in content.bullets
                 if all(similarity(b, u) < config.DUPLICATE_THRESHOLD for u in used)]
        repeated = [b for b in content.bullets if b not in fresh]
        missing = unsupported_numbers(" ".join(fresh) + " " + content.notes, known)

        if len(fresh) >= 3:
            best = (SlideContent(bullets=fresh, notes=content.notes), missing)
            if not missing:
                return best[0], []
        problems = []
        if len(fresh) < 3:
            problems.append("ces puces répètent les slides précédentes : "
                            + " | ".join(repeated) + ". Écris des puces nouvelles.")
        if missing:
            problems.append(f"les chiffres {', '.join(missing)} ne figurent pas dans les "
                            "extraits. Retire-les ou utilise des chiffres des extraits.")
        feedback = "\nATTENTION : " + " ".join(problems) + "\n"

    warnings = []
    if best is None:  # jamais 3 puces nouvelles : on garde la dernière réponse telle quelle
        best = (content, unsupported_numbers(" ".join(content.bullets) + " " + content.notes, known))
        warnings.append(f"« {slide.title} » : puces proches d'autres slides")
    if best[1]:
        warnings.append(f"« {slide.title} » : chiffres absents de la source, à vérifier : "
                        + ", ".join(best[1]))
    return best[0], warnings


# --- Visuels (étape 11) ---------------------------------------------------

DIAGRAM_EXAMPLE = '{"kind": "process", "nodes": ["<élément 1>", "<élément 2>", "<élément 3>"]}'


def make_diagram(document: Document, slide: PlannedSlide, language: str, known: set[float]
                 ) -> tuple[DiagramSpec | None, list[str]]:
    """Éléments du diagramme : lus par la vision (slide.steps) ou tirés des extraits par le LLM."""
    if slide.steps:
        nodes = [" ".join(s.split()[:5]) for s in slide.steps]
        return DiagramSpec(kind="process", nodes=nodes), []
    prompt = f"""Tire des extraits le schéma de la slide « {slide.title} » ({slide.key_point}).
Écris en {LANG_NAMES.get(language, language)}.
- kind : "process" pour des étapes successives, "hierarchy" pour un élément central
  (le premier) et ses composants.
- nodes : 2 à 6 éléments de 1 à 5 mots, tirés des extraits, dans l'ordre.

Format attendu (contenu à remplacer) :
{DIAGRAM_EXAMPLE}

Extraits du document :
\"\"\"
{select_context(document, slide)}
\"\"\""""
    try:
        spec = generate_structured(prompt, DiagramSpec, system=SYSTEM, model=config.WRITE_MODEL)
    except LLMError as e:
        return None, [f"« {slide.title} » : diagramme impossible ({e}), slide en puces"]
    missing = unsupported_numbers(" ".join(spec.nodes), known)
    warnings = [f"« {slide.title} » : chiffres du diagramme absents de la source, "
                f"à vérifier : {', '.join(missing)}"] if missing else []
    return spec, warnings


def _visual_line(slide: PlannedSlide, diagram: DiagramSpec | None) -> str:
    """Ce que montre le visuel : les puces le commentent au lieu de le paraphraser."""
    if slide.layout == "chart" and slide.chart:
        c = slide.chart
        values = ", ".join(f"{l} = {format_number(v, c.unit)}" for l, v in zip(c.labels, c.values))
        return (f"La slide affiche aussi un graphique « {c.title} » : {values}.\n"
                "Les puces commentent ce graphique (tendance, point marquant) avec ces "
                "valeurs exactes, sans calculer d'écart ni de pourcentage.\n")
    if slide.layout == "diagram" and diagram:
        return (f"La slide affiche aussi un schéma : {' → '.join(diagram.nodes)}.\n"
                "Les puces expliquent ce schéma.\n")
    return ""


def write(outline: Outline, document: Document,
          on_slide: Callable[[int, int, str], None] | None = None) -> WriteResult:
    """Rédige toutes les slides. `on_slide(i, n, titre)` est appelé avant chaque slide."""
    start = time.perf_counter()
    # 4 Go de VRAM : on libère le modèle du plan avant de charger celui de la rédaction.
    if config.PLAN_MODEL != config.WRITE_MODEL:
        unload(config.PLAN_MODEL)
    known = source_numbers(document)
    planned = outline.planned_slides()
    titles = [s.title for s in planned]
    warnings: list[str] = []

    sections = ", ".join(s.title for s in outline.sections)
    template = TITLE_NOTES.get(outline.language, TITLE_NOTES["en"])
    slides = [Slide(layout="title", title=outline.title,
                    notes=template.format(title=outline.title, sections=sections))]

    used: list[str] = []  # puces déjà écrites, pour éviter les répétitions
    for i, planned_slide in enumerate(planned):
        if on_slide:
            on_slide(i + 1, len(planned), planned_slide.title)
        others = titles[:i] + titles[i + 1:]
        slide, w = _compose(document, outline, planned_slide, others, used, known)
        warnings += w
        used += slide.bullets
        slides.append(slide)

    deck = Deck(title=outline.title, language=outline.language, slides=slides)
    return WriteResult(deck, time.perf_counter() - start, warnings)


def _compose(document: Document, outline: Outline, planned_slide: PlannedSlide,
             others: list[str], used: list[str], known: set[float], hint: str = ""
             ) -> tuple[Slide, list[str]]:
    """Une slide complète : visuel éventuel, puces et notes."""
    warnings: list[str] = []
    diagram, extra = None, {}
    if planned_slide.layout == "diagram":
        diagram, w = make_diagram(document, planned_slide, outline.language, known)
        warnings += w
        if diagram:
            extra = {"layout": "diagram", "diagram_dot": to_dot(diagram)}
    elif planned_slide.layout == "chart" and planned_slide.chart:
        extra = {"layout": "chart", "chart": planned_slide.chart}

    visual = _visual_line(planned_slide, diagram) if extra else ""
    content, w = write_slide(document, outline.title, planned_slide, others, used,
                             outline.language, known, visual=visual + hint)
    warnings += w
    # À côté d'un visuel, la place manque : on garde les premières puces.
    bullets = content.bullets[: config.VISUAL_BULLETS] if extra else content.bullets
    return Slide(**({"layout": "bullets"} | extra), title=planned_slide.title,
                 bullets=bullets, notes=content.notes), warnings


def rewrite_slide(outline: Outline, document: Document, deck: Deck, index: int
                  ) -> tuple[Slide, list[str]]:
    """FR-13 : régénère la slide `index` du deck (1 = première slide après le titre).

    Les puces des autres slides servent de « déjà dit » ; l'ancienne version est
    donnée au modèle pour qu'il en propose une autre (sinon, même graine, même texte).
    """
    planned = outline.planned_slides()
    if not 1 <= index <= len(planned):
        raise ValueError(f"slide {index} : seules les slides 1 à {len(planned)} se régénèrent")
    if config.PLAN_MODEL != config.WRITE_MODEL:
        unload(config.PLAN_MODEL)
    old = deck.slides[index]
    used = [b for i, s in enumerate(deck.slides) if i not in (0, index) for b in s.bullets]
    titles = [s.title for s in planned]
    others = titles[: index - 1] + titles[index:]
    hint = ("Version précédente à ne pas reprendre telle quelle : "
            + " | ".join(old.bullets) + "\nPropose des puces formulées autrement.\n")
    return _compose(document, outline, planned[index - 1], others, used,
                    source_numbers(document), hint=hint)
