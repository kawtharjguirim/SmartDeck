"""Rendu d'un ChartSpec en image PNG (Matplotlib), aux couleurs de la marque (FR-07)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # pas de fenêtre : rendu en fichier uniquement
import matplotlib.pyplot as plt  # noqa: E402

import config  # noqa: E402
from schemas import ChartSpec  # noqa: E402

PALETTE = ["#1F3A5F", "#E07A2E", "#4A6B8A", "#F2B38A", "#8FA3B8", "#6B7280"]


def format_number(value: float, unit: str = "") -> str:
    """Format français : 1 020 · 4,2 · 34 %."""
    if value == int(value):
        text = f"{int(value):,}".replace(",", " ")  # espace fine insécable
    else:
        text = f"{value:,.2f}".rstrip("0").rstrip(".").replace(",", " ").replace(".", ",")
    if unit == "%":
        return f"{text} %"
    return f"{text} {unit}" if unit else text


def render_chart(spec: ChartSpec, path: Path, width_in: float, height_in: float) -> Path:
    plt.rcParams["font.family"] = [config.BRAND["font"], "DejaVu Sans"]
    text_color = "#" + config.BRAND["text"]
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=config.VISUAL_DPI)
    labels = [format_number(v, spec.unit) for v in spec.values]

    if spec.kind == "pie":
        _, _, percents = ax.pie(
            spec.values, labels=spec.labels, colors=PALETTE[: len(spec.values)],
            autopct=lambda p: format_number(round(p, 1), "%"), startangle=90,
            counterclock=False, wedgeprops={"edgecolor": "white", "linewidth": 2},
            textprops={"fontsize": 13, "color": text_color})
        for t in percents:  # pourcentages à l'intérieur des parts : en blanc
            t.set_color("white")
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
        ax.spines[["left", "bottom"]].set_color("#" + config.BRAND["muted"])
        ax.tick_params(colors=text_color, labelsize=12)
        ax.yaxis.set_major_formatter(lambda v, _: format_number(v))
        ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
        ax.set_axisbelow(True)
        ylabel = f"{spec.title} ({spec.unit})" if spec.unit else spec.title
        ax.set_ylabel(ylabel, fontsize=12, color=text_color)

    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, transparent=True)
    plt.close(fig)
    return path
