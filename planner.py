"""Étape 6 : produit le plan de la présentation (FR-03, FR-04).

Plan en deux temps : le code garde le contrôle de la structure, le modèle ne
fait que des choix simples.

  0. Code   : découpe le document en « parties » (une par titre, ou par taille).
  1. LLM    : regroupe les parties en 2 à 5 sections thématiques.
  2. Code   : répartit les N slides entre les sections selon leur volume de texte.
  3. LLM    : pour chaque section, propose exactement k slides (k petit, 1 à 4).

Le modèle n'a jamais à compter jusqu'à 10, et chaque section ne voit que ses
propres extraits : meilleure couverture, moins de doublons.
"""
import math
import time
from dataclasses import dataclass, field

import config
from llm.client import generate_structured
from quality.numbers import source_numbers, unsupported_numbers
from quality.text import keywords
from schemas import (DraftOutline, Document, Outline, PlannedSlide, Section,
                     SectionSlides)
from visuals.data import figure_steps, numbered_steps, table_series, to_chart

LANG_NAMES = {"fr": "français", "en": "anglais", "ar": "arabe"}

SYSTEM = (
    "Tu es un expert en présentations. Tu réponds uniquement en JSON conforme au schéma. "
    "Tous les champs sont du texte simple. N'invente aucune information absente du document."
)

# Contenus volontairement neutres : un petit modèle recopie le texte des exemples.
EXAMPLE_SECTIONS = """{"title": "<titre de la présentation>", "sections": [
  {"title": "<section A>", "part_ids": [1, 2, 3]},
  {"title": "<section B>", "part_ids": [4, 5]},
  {"title": "<section C>", "part_ids": [6, 7, 8]}
]}"""

EXAMPLE_SLIDES = """{"slides": [
  {"title": "<titre slide>", "layout": "bullets", "key_point": "<idée principale>", "source_pages": [<page>]},
  {"title": "<titre slide>", "layout": "bullets", "key_point": "<idée principale>", "source_pages": []}
]}"""


@dataclass
class PlanResult:
    outline: Outline
    requested: int
    attempts: int  # nombre d'appels au modèle
    seconds: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class Part:
    """Morceau du document : un titre et les blocs qui le suivent."""
    id: int
    heading: str
    block_ids: list[int] = field(default_factory=list)
    chars: int = 0
    pages: set[int] = field(default_factory=set)


# --- 0. Découpage en parties ---------------------------------------------

def make_parts(document: Document, max_chars: int = config.PART_MAX_CHARS) -> list[Part]:
    parts: list[Part] = []

    def new(heading: str) -> Part:
        parts.append(Part(id=len(parts) + 1, heading=heading))
        return parts[-1]

    current = None
    for i, b in enumerate(document.blocks):
        if b.kind == "title":
            if current is not None and current.chars == 0:
                current.heading = b.content  # titres consécutifs : on garde le dernier
                current.block_ids.append(i)
                continue
            current = new(b.content)
        elif current is None:
            current = new("Début du document")
        elif current.chars and current.chars + len(b.content) > max_chars:
            current = new(f"{current.heading.removesuffix(' (suite)')} (suite)")
        current.block_ids.append(i)
        if b.kind != "title":
            current.chars += len(b.content)
        if b.page:
            current.pages.add(b.page)
    return [p for p in parts if p.chars > 0]


def _render(document: Document, block_ids: list[int], max_chars: int) -> str:
    """Texte des blocs avec numéros de page, raccourcis si besoin pour tenir."""
    def render(limit: int | None) -> str:
        out = []
        for i in block_ids:
            b = document.blocks[i]
            text = b.content
            if limit and len(text) > limit:
                text = text[:limit].rsplit(" ", 1)[0] + "…"
            page = f"[p.{b.page}] " if b.page else ""
            out.append(f"\n{page}## {text}" if b.kind == "title" else f"{page}{text}")
        return "\n".join(out).strip()

    for limit in (None, 800, 500, 300, 150):
        text = render(limit)
        if len(text) <= max_chars:
            return text
    return text[:max_chars]


def _part_line(document: Document, part: Part) -> str:
    first = next(document.blocks[i].content for i in part.block_ids
                 if document.blocks[i].kind != "title")
    preview = first[:160].rsplit(" ", 1)[0] + ("…" if len(first) > 160 else "")
    pages = f"p.{min(part.pages)}" if part.pages else ""
    return f"[P{part.id}] {part.heading} ({pages} {part.chars} car.) : {preview}"


# --- 1. Sections ------------------------------------------------------------

def _draft_sections(document: Document, parts: list[Part], n_content: int,
                    language: str) -> DraftOutline:
    max_sections = max(1, min(config.MAX_SECTIONS, n_content, len(parts)))
    min_sections = min(2, max_sections)
    listing = "\n".join(_part_line(document, p) for p in parts)
    prompt = f"""Voici les parties d'un document, dans l'ordre.
Propose le titre de la présentation (en {LANG_NAMES.get(language, language)}) et regroupe
les parties en {min_sections} à {max_sections} sections thématiques.

Règles :
- Chaque partie appartient à une seule section ; garde l'ordre du document.
- Une section regroupe des parties consécutives qui parlent du même thème.
- Toutes les parties importantes doivent être couvertes.
- Titres de section courts (moins de 6 mots).

Format attendu (contenu à remplacer) :
{EXAMPLE_SECTIONS}

Parties du document :
{listing}"""
    return generate_structured(prompt, DraftOutline, system=SYSTEM, model=config.PLAN_MODEL)


def _fix_sections(draft: DraftOutline, parts: list[Part]) -> list[tuple[str, list[Part]]]:
    """Corrige le regroupement du modèle : ids invalides, doublons, parties oubliées."""
    by_id = {p.id: p for p in parts}
    owner: dict[int, int] = {}  # part id → index de section
    for s_idx, s in enumerate(draft.sections):
        for pid in s.part_ids:
            if pid in by_id and pid not in owner:
                owner[pid] = s_idx
    # Partie oubliée : rattachée à la section de la partie précédente (ou suivante).
    last = None
    for p in parts:
        if p.id in owner:
            last = owner[p.id]
        elif last is not None:
            owner[p.id] = last
    first = next((owner[p.id] for p in parts if p.id in owner), 0)
    for p in parts:
        owner.setdefault(p.id, first)

    sections = []
    for s_idx, s in enumerate(draft.sections):
        members = [p for p in parts if owner[p.id] == s_idx]
        if members:
            sections.append((s.title, members))
    sections.sort(key=lambda s: s[1][0].id)  # ordre du document
    return sections


# --- 2. Répartition des slides -------------------------------------------

def allocate(volumes: list[int], n: int) -> list[int]:
    """Répartit n slides selon les volumes (au moins 1 par section, plus forts restes)."""
    k = len(volumes)
    if n <= k:
        return [1] * k  # le cas n < k est évité en amont (fusion de sections)
    total = sum(volumes) or 1
    shares = [(n - k) * v / total for v in volumes]
    counts = [1 + math.floor(s) for s in shares]
    rest = n - sum(counts)
    order = sorted(range(k), key=lambda i: shares[i] - math.floor(shares[i]), reverse=True)
    for i in order[:rest]:
        counts[i] += 1
    return counts


def _merge_smallest(sections: list[tuple[str, list[Part]]], n: int):
    """Plus de sections que de slides : fusionne la plus petite avec sa voisine."""
    while len(sections) > n:
        vols = [sum(p.chars for p in ps) for _, ps in sections]
        i = vols.index(min(vols))
        j = i - 1 if i > 0 else 1
        title = sections[min(i, j)][0]
        merged = sorted(sections[i][1] + sections[j][1], key=lambda p: p.id)
        sections[min(i, j)] = (title, merged)
        del sections[max(i, j)]
    return sections


def _split(parts: list[Part], groups: int) -> list[list[Part]]:
    """Coupe une liste de parties en `groups` morceaux consécutifs de volume proche."""
    total = sum(p.chars for p in parts)
    out, current, acc = [], [], 0
    for p in parts:
        current.append(p)
        acc += p.chars
        if len(out) < groups - 1 and acc >= total * (len(out) + 1) / groups:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


# --- 3. Slides d'une section -------------------------------------------

def _plan_slides(document: Document, deck_title: str, section_title: str,
                 parts: list[Part], k: int, others: list[str], language: str
                 ) -> tuple[list[PlannedSlide], int, list[str]]:
    block_ids = [i for p in parts for i in p.block_ids]
    context = _render(document, block_ids, config.SECTION_CONTEXT_CHARS)
    feedback, calls = "", 0
    for _ in range(config.PLAN_COUNT_RETRIES + 1):
        calls += 1
        prompt = f"""Présentation : {deck_title}
Section : {section_title}
Autres sections (ne pas traiter leur contenu) : {"; ".join(others) or "aucune"}

Propose exactement {k} slide(s) en {LANG_NAMES.get(language, language)} pour cette section.
- Chaque slide traite un aspect différent des extraits ci-dessous.
- Titre court (moins de 8 mots) et idée principale en une phrase (key_point).
- source_pages : les numéros [p.X] des extraits utilisés (liste vide s'il n'y en a pas).
- layout "chart" seulement si la slide s'appuie sur les chiffres d'un tableau ;
  "diagram" pour un processus ou une architecture ; sinon "bullets".
{feedback}
Format attendu (contenu à remplacer) :
{EXAMPLE_SLIDES}

Extraits de la section :
\"\"\"
{context}
\"\"\""""
        slides = generate_structured(prompt, SectionSlides, system=SYSTEM,
                                     model=config.PLAN_MODEL).slides
        if len(slides) == k:
            break
        feedback = (f"\nATTENTION : tu as proposé {len(slides)} slides, "
                    f"il en faut exactement {k}.\n")

    warnings = []
    if len(slides) > k:
        slides = slides[:k]
    elif len(slides) < k:
        warnings.append(f"Section « {section_title} » : {len(slides)} slide(s) au lieu de {k}.")
    for s in slides:
        s.source_blocks = block_ids
    return slides, calls, warnings


# --- 4. Visuels (étape 11) ----------------------------------------------------

def _assign_visuals(document: Document, outline: Outline, warnings: list[str]) -> None:
    """Associe à chaque slide « chart » une série d'un tableau de la source, et à une
    slide « diagram » les étapes d'un schéma lu par la vision.

    Les valeurs viennent du tableau, jamais du modèle (CA-02). Une section qui contient
    un tableau de nombres reçoit au plus un graphique, même si le modèle n'en a pas prévu.
    """
    known = source_numbers(document)
    used: set[tuple[int, str]] = set()

    def overlap(slide: PlannedSlide, text: str) -> int:
        return len(keywords(f"{slide.title} {slide.key_point}") & keywords(text))

    for section in outline.sections:
        blocks = sorted({i for s in section.slides for i in s.source_blocks})
        series = [x for x in table_series(document, blocks)
                  if all(round(v, 6) in known for v in x.values)]

        def free():
            return [x for x in series if (x.block, x.name) not in used]

        def take(slide: PlannedSlide, x) -> None:
            slide.layout, slide.chart = "chart", to_chart(x)
            used.add((x.block, x.name))

        for s in section.slides:  # graphiques prévus par le modèle
            if s.layout != "chart":
                continue
            if free():
                take(s, max(free(), key=lambda x: overlap(s, x.words())))
            else:
                s.layout = "bullets"
                warnings.append(f"« {s.title} » : pas de tableau de chiffres pour un "
                                "graphique, slide en puces")

        if free() and not any(s.layout == "chart" for s in section.slides):
            candidates = [s for s in section.slides if s.layout == "bullets"]
            if candidates:
                def score(pair):
                    s, x = pair
                    page = document.blocks[x.block].page
                    return overlap(s, x.words()) + (2 if page in s.source_pages else 0)
                s, x = max(((s, x) for s in candidates for x in free()), key=score)
                take(s, x)

        # Étapes d'un schéma lu par la vision, sinon d'une liste numérotée du texte.
        steps, heading = figure_steps(document, blocks)
        if not steps:
            steps, heading = numbered_steps(document, blocks)
        steps = steps[: config.MAX_DIAGRAM_NODES]
        if len(steps) >= 2:
            text = f"{heading} {' '.join(steps)}"
            diagrams = [s for s in section.slides if s.layout == "diagram"]
            if not diagrams:
                candidates = [s for s in section.slides if s.layout == "bullets"]
                if candidates:
                    def duplicate(s: PlannedSlide) -> bool:  # titre quasi identique à un autre
                        k = keywords(s.title)
                        return bool(k) and any(o is not s and len(k & keywords(o.title)) * 2 >= len(k)
                                               for o in outline.planned_slides())

                    best = max(candidates,
                               key=lambda s: (overlap(s, text), duplicate(s)))
                    if overlap(best, text) == 0 and heading:
                        # Aucune slide ne parle de ce schéma : elle prend le titre de la source.
                        best.title = heading
                        best.key_point = f"{heading} : {' → '.join(steps)}"
                    best.layout = "diagram"
                    diagrams = [best]
            if diagrams:
                diagrams[0].steps = steps

        # Diagramme proposé par le modèle sans étapes trouvées par le code : la recette
        # (étape 14) a montré des schémas sans objet (« ventes → progression → 12 % »).
        if not config.LLM_DIAGRAMS:
            for s in section.slides:
                if s.layout == "diagram" and not s.steps:
                    s.layout = "bullets"


# --- Point d'entrée ---------------------------------------------------------

def plan(document: Document, n_slides: int = config.DEFAULT_SLIDES,
         language: str | None = None) -> PlanResult:
    """Produit le plan pour `n_slides` slides au total (slide de titre comprise)."""
    if not config.MIN_SLIDES <= n_slides <= config.MAX_SLIDES:
        raise ValueError(f"nombre de slides entre {config.MIN_SLIDES} et {config.MAX_SLIDES}")
    language = language or document.language
    n_content = n_slides - 1
    start = time.perf_counter()
    warnings: list[str] = []

    parts = make_parts(document)
    draft = _draft_sections(document, parts, n_content, language)
    calls = 1
    sections = _merge_smallest(_fix_sections(draft, parts), n_content)
    counts = allocate([sum(p.chars for p in ps) for _, ps in sections], n_content)

    titles = [t for t, _ in sections]
    out_sections = []
    for (title, members), k in zip(sections, counts):
        others = [t for t in titles if t != title]
        groups = _split(members, math.ceil(k / config.MAX_SLIDES_PER_CALL))
        ks = allocate([sum(p.chars for p in g) for g in groups], k)
        slides = []
        for group, kg in zip(groups, ks):
            got, c, w = _plan_slides(document, draft.title, title, group, kg, others, language)
            slides += got
            calls += c
            warnings += w
        out_sections.append(Section(title=title, slides=slides))

    outline = Outline(title=draft.title, language=language, sections=out_sections)
    _assign_visuals(document, outline, warnings)

    # Pages citées qui n'existent pas dans le document : retirées.
    valid_pages = {b.page for b in document.blocks if b.page}
    for s in outline.planned_slides():
        bad = [p for p in s.source_pages if p not in valid_pages]
        if bad and valid_pages:
            warnings.append(f"« {s.title} » : pages inexistantes {bad} retirées")
        s.source_pages = [p for p in s.source_pages if p in valid_pages]

    # FR-12 : chiffres absents du document → à vérifier.
    known = source_numbers(document)
    for s in outline.planned_slides():
        missing = unsupported_numbers(f"{s.title} {s.key_point}", known)
        if missing:
            warnings.append(f"« {s.title} » : chiffres absents de la source, à vérifier : "
                            + ", ".join(missing))

    return PlanResult(outline, n_slides, calls, time.perf_counter() - start, warnings)
