"""Thèmes de présentation intégrés (FR-11) : couleurs, polices et décor.

Un thème s'applique à la construction du PPTX, aux graphiques (Matplotlib) et aux
diagrammes (Graphviz). Il ne touche pas au contenu : changer de thème reconstruit
la présentation sans rappeler le modèle de langue.

Polices : uniquement des polices livrées avec Windows, pour que la mesure du texte
(CA-03, pas de débordement) se fasse avec le vrai fichier de police, et que
LibreOffice les trouve à l'export PDF. L'arabe utilise toujours Arial (glyphes).
"""
from dataclasses import dataclass, field

DEFAULT_THEME = "classique"


@dataclass(frozen=True)
class Theme:
    name: str
    label: str
    description: str
    font: str                 # texte courant
    font_file: str            # fichier dans C:\Windows\Fonts, pour mesurer le texte
    title_font: str           # titres
    title_font_file: str      # version grasse : les titres sont en gras
    primary: str              # couleur principale : titres, nœuds des diagrammes
    accent: str               # filets, flèches, second plan des graphiques
    text: str                 # puces
    muted: str                # pied de page, sous-titre, axes
    title_color: str          # titres des slides de contenu
    background: str | None    # fond des slides de contenu (None : blanc du modèle)
    title_bg: str | None      # fond de la slide de titre
    title_slide_text: str     # titre de la présentation sur la slide de titre
    title_slide_sub: str      # sous-titre (source · date)
    grid: str                 # quadrillage des graphiques
    palette: list[str] = field(default_factory=list)  # séries des graphiques (camembert)
    node_text: str = "FFFFFF"  # texte dans les nœuds des diagrammes
    title_rule: str = "short"  # slide de titre : "short" filet court, "none", "band" bande latérale
    content_rule: str = "short"  # sous le titre : "short", "full" (pleine largeur), "none"
    rounded: bool = False      # filets aux bouts arrondis
    # Modèle d'entreprise importé (build/template_import.py) :
    template: str | None = None        # fichier .pptx du modèle
    title_layout: int | None = None    # index des mises en page choisies par leur contenu
    content_layout: int | None = None
    inherit: bool = False              # couleurs et polices du texte : celles du modèle


THEMES: dict[str, Theme] = {t.name: t for t in [
    Theme("classique", "Classique", "Bleu nuit et orange, bandeau de titre. Rapports, usage général.",
          font="Calibri", font_file="calibri.ttf",
          title_font="Calibri", title_font_file="calibrib.ttf",
          primary="1F3A5F", accent="E07A2E", text="222222", muted="6B7280",
          title_color="1F3A5F", background=None, title_bg="1F3A5F",
          title_slide_text="FFFFFF", title_slide_sub="D6DEE8", grid="E5E7EB",
          palette=["#1F3A5F", "#E07A2E", "#4A6B8A", "#F2B38A", "#8FA3B8", "#6B7280"]),
    Theme("minimal", "Minimal", "Beaucoup de blanc, un seul accent bleu. Présentations sobres.",
          font="Segoe UI", font_file="segoeui.ttf",
          title_font="Segoe UI", title_font_file="segoeuib.ttf",
          primary="1F2937", accent="2563EB", text="374151", muted="9CA3AF",
          title_color="111827", background=None, title_bg=None,
          title_slide_text="111827", title_slide_sub="6B7280", grid="EEF0F3",
          palette=["#2563EB", "#1F2937", "#60A5FA", "#9CA3AF", "#1E40AF", "#D1D5DB"],
          content_rule="none"),
    Theme("sombre", "Sombre", "Fond anthracite, accent cyan. Conférences, projection.",
          font="Segoe UI", font_file="segoeui.ttf",
          title_font="Segoe UI", title_font_file="segoeuib.ttf",
          primary="0E7490", accent="22D3EE", text="E6E9EE", muted="8B95A3",
          title_color="FFFFFF", background="1E2228", title_bg="14171C",
          title_slide_text="FFFFFF", title_slide_sub="9AA4B2", grid="2F3640",
          palette=["#22D3EE", "#F59E0B", "#A78BFA", "#34D399", "#F472B6", "#94A3B8"]),
    Theme("institutionnel", "Institutionnel", "Bordeaux et gris, titres à empattements. "
          "Administrations, finance.",
          font="Arial", font_file="arial.ttf",
          title_font="Georgia", title_font_file="georgiab.ttf",
          primary="7A1F2B", accent="7A1F2B", text="1F2937", muted="6B7280",
          title_color="7A1F2B", background=None, title_bg=None,
          title_slide_text="7A1F2B", title_slide_sub="4B5563", grid="E5E7EB",
          palette=["#7A1F2B", "#9CA3AF", "#B45360", "#4B5563", "#D6A3AA", "#1F2937"],
          title_rule="band", content_rule="full"),
    Theme("nature", "Nature / Éducation", "Vert et jaune, formes arrondies. Associations, écoles.",
          font="Calibri", font_file="calibri.ttf",
          title_font="Candara", title_font_file="Candarab.ttf",
          primary="2F6B3A", accent="E9B949", text="26352A", muted="6B7A6E",
          title_color="2F6B3A", background=None, title_bg="EEF5E9",
          title_slide_text="2F6B3A", title_slide_sub="5B6B5E", grid="E6EDE3",
          palette=["#2F6B3A", "#E9B949", "#7FB069", "#C9DCA0", "#A3683A", "#6B7A6E"],
          rounded=True),
]}


def get_theme(name: str | None) -> Theme:
    """Thème par son nom ; ValueError si inconnu (liste des noms valides dans le message)."""
    name = (name or DEFAULT_THEME).lower()
    if name in THEMES:
        return THEMES[name]
    from build.template_import import imported_themes  # modèles d'entreprise importés
    imported = imported_themes()
    if name in imported:
        return imported[name]
    raise ValueError(f"thème inconnu « {name} » : {', '.join([*THEMES, *imported])}")


def all_themes() -> dict[str, Theme]:
    """Thèmes intégrés puis modèles importés."""
    from build.template_import import imported_themes
    return THEMES | imported_themes()


def recolor_dot(dot: str, theme: Theme) -> str:
    """Les diagrammes sont écrits aux couleurs du thème Classique (dans le .deck.json) :
    on les remplace par celles du thème choisi au moment du rendu."""
    base = THEMES[DEFAULT_THEME]
    return (dot.replace(f"#{base.primary}", f"#{theme.primary}")
               .replace(f"#{base.accent}", f"#{theme.accent}")
               .replace(f'fontname="{base.font}"', f'fontname="{theme.font}"')
               .replace('fontcolor="white"', f'fontcolor="#{theme.node_text}"'))
