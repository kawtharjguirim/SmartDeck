"""Rendu d'un ChartSpec en image PNG (Matplotlib), aux couleurs de la marque (FR-07)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # pas de fenêtre : rendu en fichier uniquement
import matplotlib.pyplot as plt  # noqa: E402

import config  # noqa: E402
from build.themes import Theme, get_theme  # noqa: E402
from schemas import ChartSpec  # noqa: E402


def format_number(value: float, unit: str = "") -> str:
    """Format français : 1 020 · 4,2 · 34 %."""
    if value == int(value):
        text = f"{int(value):,}".replace(",", " ")  # espace fine insécable
    else:
        text = f"{value:,.2f}".rstrip("0").rstrip(".").replace(",", " ").replace(".", ",")
    if unit == "%":
        return f"{text} %"
    return f"{text} {unit}" if unit else text


def _is_light(hex_color: str) -> bool:
    """Couleur claire (luminance perçue > 60 %) : on y écrit en sombre."""
    r, g, b = (int(hex_color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b > 153


def render_chart(spec: ChartSpec, path: Path, width_in: float, height_in: float,
                 theme: Theme | None = None) -> Path:
    theme = theme or get_theme(None)
    PALETTE = theme.palette  # noqa: N806
    plt.rcParams["font.family"] = [theme.font, "DejaVu Sans"]
    text_color = "#" + theme.text
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=config.VISUAL_DPI)
    labels = [format_number(v, spec.unit) for v in spec.values]

    if spec.kind == "pie":
        _, _, percents = ax.pie(
            spec.values, labels=spec.labels, colors=PALETTE[: len(spec.values)],
            autopct=lambda p: format_number(round(p, 1), "%"), startangle=90,
            counterclock=False,
            wedgeprops={"edgecolor": "#" + (theme.background or "FFFFFF"), "linewidth": 2},
            textprops={"fontsize": 13, "color": text_color})
        for t, color in zip(percents, PALETTE):  # pourcentage lisible sur la part
            t.set_color("#1F2937" if _is_light(color) else "white")
        ax.axis("equal")
    else:
        if spec.kind == "bar":
            bars = ax.bar(spec.labels, spec.values, color=PALETTE[0], width=0.6)
            ax.bar_label(bars, labels=labels, padding=4, fontsize=13, color=text_color)
        else:  # line
            ax.plot(spec.labels, spec.values, color=PALETTE[0], linewidth=3, marker="o",
                    markersize=8, markerfacecolor=PALETTE[1], markeredgecolor=PALETTE[1])
            for x, y, text in zip(spec.labels, spec.values, labels):
                ax.annotate(text, (x, y), textcoords="offset points", xytext=(0, 10),
                            ha="center", fontsize=12, color=text_color)
        ax.set_ylim(0, max(spec.values) * 1.15 if max(spec.values) > 0 else 1)
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color("#" + theme.muted)
        ax.tick_params(colors=text_color, labelsize=12)
        ax.yaxis.set_major_formatter(lambda v, _: format_number(v))
        ax.grid(axis="y", color="#" + theme.grid, linewidth=0.8)
        ax.set_axisbelow(True)
        ylabel = f"{spec.title} ({spec.unit})" if spec.unit else spec.title
        ax.set_ylabel(ylabel, fontsize=12, color=text_color)

    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, transparent=True)
    plt.close(fig)
    return path
