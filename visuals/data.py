"""Données des graphiques, lues directement dans les tableaux de la source.

Le modèle ne recopie jamais une valeur : le code reprend les cellules du tableau
(CA-02 : aucune valeur de graphique absente de la source).
"""
import re
from dataclasses import dataclass

from schemas import ChartKind, ChartSpec, Document

_SPACES = re.compile(r"[\s   ]")
_NUMBER = re.compile(r"^[-+]?\d+(?:[.,]\d+)?$")
_UNIT_SUFFIX = re.compile(r"(%|k€|M€|€|\$|k\$)$")
_HEADER_UNIT = re.compile(r"\(([^)]{1,10})\)\s*$")
_TIME_LABEL = re.compile(
    r"^(T|Q|S|H)\d$|^(19|20)\d{2}$|^(janv|févr|mars|avr|mai|juin|juil|août|sept|oct|nov|déc|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.IGNORECASE)


@dataclass
class Series:
    """Une colonne de nombres d'un tableau, avec les étiquettes de la première colonne."""
    name: str
    unit: str
    labels: list[str]
    values: list[float]
    block: int  # indice du bloc source dans le Document

    def words(self) -> str:
        return f"{self.name} {' '.join(self.labels)}"


def parse_number(cell: str) -> tuple[float, str] | None:
    """« 1 020 » → (1020, "") ; « 34 % » → (34, "%") ; « T1 » → None."""
    s = _SPACES.sub("", cell)
    unit = ""
    m = _UNIT_SUFFIX.search(s)
    if m:
        unit, s = m.group(1), s[: m.start()]
    if not _NUMBER.match(s):
        return None
    return float(s.replace(",", ".")), unit


def parse_markdown_table(text: str) -> list[list[str]]:
    """Lignes « | a | b | » d'un texte → cellules (la ligne de séparation est ignorée)."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return rows


def _is_index(values: list[float]) -> bool:
    """1, 2, 3… (numéros d'étape, de ligne) : une numérotation, pas une mesure à tracer."""
    return all(v == int(v) for v in values) and \
        all(b - a == 1 for a, b in zip(values, values[1:]))


def table_series(document: Document, block_ids: list[int]) -> list[Series]:
    """Toutes les séries de nombres des tableaux (et figures) parmi `block_ids`."""
    out = []
    for i in block_ids:
        block = document.blocks[i]
        if block.kind not in ("table", "figure"):
            continue
        rows = parse_markdown_table(block.content)
        if len(rows) < 3:  # en-tête + au moins 2 lignes
            continue
        header, data = rows[0], [r for r in rows[1:] if len(r) == len(rows[0])]
        if len(data) < 2:
            continue
        label_col = next((j for j in range(len(header))
                          if not all(parse_number(r[j]) for r in data)), None)
        if label_col is None:
            continue
        labels = [r[label_col] for r in data]
        for j, name in enumerate(header):
            if j == label_col:
                continue
            parsed = [parse_number(r[j]) for r in data]
            if not all(parsed) or _is_index([v for v, _ in parsed]):
                continue
            m = _HEADER_UNIT.search(name)
            unit = m.group(1) if m else next((u for _, u in parsed if u), "")
            clean_name = _HEADER_UNIT.sub("", name).strip() or name
            if block.kind == "figure" and clean_name.lower() in ("valeur", "value"):
                # Figure lue par la vision : son titre (1re ligne) nomme mieux la série.
                clean_name = _HEADER_UNIT.sub("", block.content.splitlines()[0]).strip()
            out.append(Series(clean_name, unit, labels, [v for v, _ in parsed], i))
    return out


def choose_kind(series: Series) -> ChartKind:
    """Camembert pour des parts qui font 100 %, courbe pour une longue suite temporelle."""
    if series.unit == "%" and 95 <= sum(series.values) <= 105 and min(series.values) >= 0:
        return "pie"
    if len(series.labels) >= 5 and all(_TIME_LABEL.match(l) for l in series.labels):
        return "line"
    return "bar"


def to_chart(series: Series) -> ChartSpec:
    return ChartSpec(kind=choose_kind(series), title=series.name, labels=series.labels,
                     values=series.values, unit=series.unit)


_NUMBERED = re.compile(r"^(\d{1,2})[.)]\s+(.+)")


def _step_label(text: str) -> str:
    """« Routeur : détecte le type… » → « Routeur » ; sinon les 5 premiers mots."""
    head = re.split(r"\s*[:—–]\s+|\s+-\s+", text, maxsplit=1)[0].rstrip(" .;")
    words = head.split()
    return " ".join(words[:5]) + ("…" if len(words) > 5 else "")


def _heading_before(document: Document, index: int) -> str:
    """Titre le plus proche avant le bloc `index` (« 7. Architecture » → « Architecture »)."""
    for b in reversed(document.blocks[:index]):
        if b.kind == "title":
            return re.sub(r"^\d+[.)]\s*", "", b.content).strip()
    return ""


def numbered_steps(document: Document, block_ids: list[int]) -> tuple[list[str], str]:
    """Plus longue liste numérotée 1, 2, 3… (au moins 3 éléments) → (étapes, titre au-dessus)."""
    best, best_start, run, start = [], 0, [], 0
    for i in block_ids:
        block = document.blocks[i]
        m = _NUMBERED.match(block.content) if block.kind == "text" else None
        if m and int(m.group(1)) == len(run) + 1:
            if not run:
                start = i
            run.append(_step_label(m.group(2)))
        elif m and m.group(1) == "1":
            run, start = [_step_label(m.group(2))], i
        else:
            run = []
        if len(run) > len(best):
            best, best_start = list(run), start
    if len(best) < 3:
        return [], ""
    return best, _heading_before(document, best_start)


def figure_steps(document: Document, block_ids: list[int]) -> tuple[list[str], str]:
    """Étapes d'un schéma lu par la vision (« Étapes : a → b → c ») et son titre."""
    for i in block_ids:
        block = document.blocks[i]
        if block.kind != "figure":
            continue
        for line in block.content.splitlines():
            if line.startswith("Étapes :"):
                steps = [s.strip() for s in line.removeprefix("Étapes :").split("→") if s.strip()]
                return steps, block.content.splitlines()[0]
    return [], ""
