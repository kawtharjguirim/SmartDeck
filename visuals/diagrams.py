"""Diagrammes (FR-08) : DiagramSpec → code Graphviz (DOT) → image PNG.

Le code DOT est généré ici, jamais par le modèle. Il est gardé dans le Deck
(Slide.diagram_dot) : on peut le retoucher dans le .deck.json puis reconstruire.
"""
import shutil
import subprocess
import textwrap
from pathlib import Path

import config
from schemas import DiagramSpec


class GraphvizError(RuntimeError):
    pass


def _label(text: str) -> str:
    wrapped = "\\n".join(textwrap.wrap(text, width=16)) or " "
    return wrapped.replace('"', '\\"')


def to_dot(spec: DiagramSpec) -> str:
    brand = config.BRAND
    n = len(spec.nodes)
    rows = -(-n // config.DIAGRAM_ROW) if spec.kind == "process" else 1
    # Processus long : plusieurs lignes empilées (TB), chaque ligne alignée (rank=same).
    rankdir = "TB" if spec.kind == "hierarchy" or rows > 1 else "LR"
    lines = [
        "digraph G {",
        f'  graph [rankdir={rankdir}, bgcolor="transparent", nodesep=0.35, ranksep=0.45, '
        'pad=0.1];',
        f'  node [shape=box, style="rounded,filled", fillcolor="#{brand["primary"]}", '
        f'color="#{brand["primary"]}", fontcolor="white", fontname="{brand["font"]}", '
        'fontsize=16, margin="0.25,0.15"];',
        f'  edge [color="#{brand["accent"]}", penwidth=2.5, arrowsize=0.9];',
    ]
    for i, node in enumerate(spec.nodes):
        lines.append(f'  n{i} [label="{_label(node)}"];')
    if spec.kind == "process" and rows > 1:
        per_row = -(-n // rows)  # lignes équilibrées : 10 → 5 + 5, 7 → 4 + 3
        for r in range(rows):
            ids = [f"n{i}" for i in range(r * per_row, min(n, (r + 1) * per_row))]
            lines.append("  { rank=same; " + " -> ".join(ids) + "; }")
            if r:
                # Colonnes alignées : liens invisibles vers l'élément du dessous.
                for i in range(r * per_row, min(n, (r + 1) * per_row)):
                    lines.append(f"  n{i - per_row} -> n{i} [style=invis];")
                # Passage à la ligne suivante, sans déformer la grille.
                lines.append(f"  n{r * per_row - 1} -> n{r * per_row} [constraint=false];")
    elif spec.kind == "process":
        lines.append("  " + " -> ".join(f"n{i}" for i in range(n)) + ";")
    else:  # hierarchy : le premier élément est relié à tous les autres
        lines.append(f'  n0 [fillcolor="#{brand["accent"]}", color="#{brand["accent"]}"];')
        lines += [f"  n0 -> n{i};" for i in range(1, len(spec.nodes))]
    lines.append("}")
    return "\n".join(lines)


def _dot_exe() -> str:
    if Path(config.GRAPHVIZ_DOT).exists():
        return config.GRAPHVIZ_DOT
    found = shutil.which("dot")
    if found:
        return found
    raise GraphvizError("Graphviz introuvable (tools/graphviz ou PATH) : diagramme rendu en puces")


def render_dot(dot: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [_dot_exe(), "-Tpng", f"-Gdpi={config.VISUAL_DPI}", "-o", str(path)],
        input=dot.encode("utf-8"), capture_output=True, timeout=60,
    )
    if result.returncode != 0 or not path.exists():
        raise GraphvizError(f"Graphviz : {result.stderr.decode('utf-8', 'replace').strip()}")
    return path
