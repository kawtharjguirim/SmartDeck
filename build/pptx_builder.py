"""Étape 8 : construit le PPTX à partir d'un Deck validé (FR-06, FR-10, FR-11).

- Template : templates/brand.pptx s'il existe, sinon un template 16:9 généré.
- Texte placé dans les espaces réservés (placeholders) : le PPTX reste éditable.
- Taille de police choisie en mesurant le texte avec Pillow (CA-03 : pas de débordement).
- Notes orateur écrites dans chaque slide.
- Étape 11 : slides « chart » (Matplotlib) et « diagram » (Graphviz) en image,
  avec les puces à côté ou dessous.
"""
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PIL import Image, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, PP_PLACEHOLDER
from pptx.enum.text import MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

import config
from schemas import Deck, Slide
from quality.text import is_rtl
from visuals.charts import render_chart
from visuals.diagrams import GraphvizError, render_dot

TITLE_TYPES = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}
BODY_TYPES = {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT, PP_PLACEHOLDER.SUBTITLE}

SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)  # 16:9
LINE_SPACING = 1.2       # hauteur d'une ligne = 1,2 × taille de police
PARA_SPACE = 0.5         # espace après une puce = 0,5 × taille de police
BULLET_INDENT = Inches(0.4)
RTL_FONT = "Arial"  # police installée sous Windows et LibreOffice, avec l'arabe
MARGIN_X, MARGIN_Y = Inches(0.1), Inches(0.05)  # marges internes par défaut d'une zone de texte


@dataclass
class BuildResult:
    path: Path
    warnings: list[str] = field(default_factory=list)


def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color)


# --- Template ---------------------------------------------------------------

def _place(ph, left, top, width, height):
    ph.left, ph.top, ph.width, ph.height = left, top, width, height


def make_default_template(path: Path) -> None:
    """Template 16:9 : repositionne les zones de titre et de texte des mises en page."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H
    title_slide, content = prs.slide_layouts[0], prs.slide_layouts[1]
    for ph in title_slide.placeholders:
        t = ph.placeholder_format.type
        if t in TITLE_TYPES:
            _place(ph, Inches(0.9), Inches(2.3), Inches(11.5), Inches(1.9))
        elif t in BODY_TYPES:
            _place(ph, Inches(0.9), Inches(4.5), Inches(11.5), Inches(0.9))
    for ph in content.placeholders:
        t = ph.placeholder_format.type
        if t in TITLE_TYPES:
            _place(ph, Inches(0.8), Inches(0.45), Inches(11.7), Inches(1.1))
        elif t in BODY_TYPES:
            _place(ph, Inches(0.8), Inches(1.95), Inches(11.7), Inches(4.75))
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(path)


def _layout(prs: Presentation, name: str, index: int):
    for layout in prs.slide_layouts:
        if layout.name == name:
            return layout
    return prs.slide_layouts[index]


def _placeholder(slide, types):
    return next((ph for ph in slide.placeholders if ph.placeholder_format.type in types), None)


# --- Mesure du texte (CA-03) ---------------------------------------------

_fonts: dict[int, ImageFont.FreeTypeFont] = {}


def _font(size: int) -> ImageFont.FreeTypeFont | None:
    if size not in _fonts:
        try:
            _fonts[size] = ImageFont.truetype(config.BRAND["font_file"], size)
        except OSError:
            return None
    return _fonts[size]


def _line_count(text: str, size: int, width_pt: float) -> int:
    """Nombre de lignes après retour à la ligne automatique, mesuré avec la vraie police."""
    font = _font(size)
    if font is None:  # police introuvable : estimation (0,5 × taille par caractère)
        return max(1, -(-int(len(text) * size * 0.5) // int(width_pt)))
    lines, current = 1, ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if font.getlength(trial) <= width_pt or not current:
            current = trial
        else:
            lines, current = lines + 1, word
    return lines


def fit_size(paragraphs: list[str], width: Emu, height: Emu, sizes: tuple[int, ...],
             indent: Emu = Emu(0), bold: bool = False) -> tuple[int, bool]:
    """Plus grande taille pour laquelle le texte tient dans la zone. (taille, tient ?)"""
    width_pt = (width - 2 * MARGIN_X - indent) / 12700  # 1 pt = 12 700 EMU
    if bold:
        width_pt *= 0.92  # le gras est environ 8 % plus large que la police mesurée
    height_pt = (height - 2 * MARGIN_Y) / 12700
    for size in sizes:
        lines = sum(_line_count(p, size, width_pt) for p in paragraphs)
        needed = lines * size * LINE_SPACING + (len(paragraphs) - 1) * size * PARA_SPACE
        if needed <= height_pt:
            return size, True
    return sizes[-1], False


# --- Remplissage ----------------------------------------------------------

def _write(frame, paragraphs: list[str], size: int, color: str, bold=False,
           align=None, space_after=True) -> None:
    frame.clear()
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    for i, text in enumerate(paragraphs):
        p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        p.text = text
        p.level = 0
        rtl = is_rtl(text)
        if rtl:  # arabe : sens de lecture droite → gauche, sinon l'ordre des mots se brouille
            p._p.get_or_add_pPr().set("rtl", "1")
            p.alignment = PP_ALIGN.RIGHT
        elif align is not None:
            p.alignment = align
        if space_after:
            p.space_after = Pt(size * PARA_SPACE)
        for run in p.runs:
            run.font.size = Pt(size)
            run.font.name = config.BRAND["font"]
            run.font.bold = bold
            run.font.color.rgb = _rgb(color)
            if rtl:  # langue et police « complex script » (Calibri n'a pas de glyphes arabes)
                rpr = run._r.get_or_add_rPr()
                rpr.set("lang", "ar-SA")
                cs = rpr.makeelement(qn("a:cs"), {"typeface": RTL_FONT})
                rpr.append(cs)


def _rect(slide, left, top, width, height, color: str):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(color)
    shape.line.fill.background()
    shape.shadow.inherit = False
    # LibreOffice applique quand même l'ombre du style de thème (effectRef) : on l'annule.
    effect = shape._element.find(".//" + qn("a:effectRef"))
    if effect is not None:
        effect.set("idx", "0")
    return shape


def _send_to_back(slide, shape) -> None:
    tree = slide.shapes._spTree
    tree.remove(shape._element)
    tree.insert(2, shape._element)  # après les propriétés du groupe : tout au fond


def _footer(slide, text: str, number: str) -> None:
    """Pied de page : titre de la présentation à gauche, numéro de slide à droite."""
    for content, left, width, align in (
        (text, Inches(0.8), Inches(9.0), PP_ALIGN.LEFT),
        (number, Inches(10.5), Inches(2.0), PP_ALIGN.RIGHT),
    ):
        box = slide.shapes.add_textbox(left, Inches(6.95), width, Inches(0.35))
        _write(box.text_frame, [content], 11, config.BRAND["muted"], align=align, space_after=False)


def _logo(slide, prs) -> None:
    if config.LOGO.exists():
        slide.shapes.add_picture(str(config.LOGO), prs.slide_width - Inches(1.6),
                                 Inches(0.3), height=Inches(0.6))


def _title_slide(prs, deck: Deck, slide_data: Slide, decorate: bool, source: str) -> None:
    slide = prs.slides.add_slide(_layout(prs, "Title Slide", 0))
    brand = config.BRAND
    if decorate:  # fond bleu nuit et filet orange
        _send_to_back(slide, _rect(slide, 0, 0, prs.slide_width, prs.slide_height, brand["primary"]))
        rule_left = prs.slide_width - Inches(0.9 + 1.4) if is_rtl(deck.title) else Inches(0.9)
        _rect(slide, rule_left, Inches(4.25), Inches(1.4), Inches(0.08), brand["accent"])
    title = _placeholder(slide, TITLE_TYPES)
    if title is not None:
        size, _ = fit_size([deck.title], title.width, title.height, (44, 40, 36, 32, 28),
                           bold=True)
        _write(title.text_frame, [deck.title], size,
               "FFFFFF" if decorate else brand["primary"], bold=True,
               align=PP_ALIGN.LEFT, space_after=False)
    subtitle = _placeholder(slide, BODY_TYPES)
    if subtitle is not None:
        text = f"{source} · {date.today().strftime('%d/%m/%Y')}" if source else \
            date.today().strftime("%d/%m/%Y")
        _write(subtitle.text_frame, [text], 18, "D6DEE8" if decorate else brand["muted"],
               align=PP_ALIGN.LEFT, space_after=False)
    _logo(slide, prs)
    slide.notes_slide.notes_text_frame.text = slide_data.notes


def _picture(slide, path: Path, left, top, width, height) -> None:
    """Image centrée dans la zone, proportions gardées."""
    with Image.open(path) as im:
        ratio = im.width / im.height
    w, h = width, int(width / ratio)
    if h > height:
        w, h = int(height * ratio), height
    slide.shapes.add_picture(str(path), left + (width - w) // 2, top + (height - h) // 2, w, h)


def _visual(slide, body, data: Slide, number: int, workdir: Path, warnings: list[str]) -> None:
    """Graphique ou diagramme dans la zone de texte ; les puces se placent à côté ou dessous.

    Graphique et diagramme haut : image à gauche (62 %), puces à droite.
    Diagramme très large (processus) : image en haut, puces dessous.
    """
    left, top, width, height = body.left, body.top, body.width, body.height
    gap = Inches(0.3)
    try:
        if data.layout == "chart":
            img_w = int(width * 0.62)
            path = render_chart(data.chart, workdir / f"chart_{number}.png",
                                img_w / 914400, height / 914400)
        else:
            path = render_dot(data.diagram_dot, workdir / f"diagram_{number}.png")
    except (GraphvizError, OSError, ValueError) as e:
        warnings.append(f"Slide {number} « {data.title} » : visuel non rendu ({e}), "
                        "puces seules")
        return
    with Image.open(path) as im:
        wide = data.layout == "diagram" and im.width / im.height > 2.2
    # Toujours fixer les 4 dimensions : une seule modifiée, python-pptx met les autres à 0.
    if wide:
        img_h = int(height * 0.45)
        _picture(slide, path, left, top, width, img_h)
        _place(body, left, top + img_h + gap, width, height - img_h - gap)
    else:
        img_w = int(width * 0.62)
        _picture(slide, path, left, top, img_w, height)
        _place(body, left + img_w + gap, top, width - img_w - gap, height)


def _content_slide(prs, deck: Deck, data: Slide, number: int, total: int,
                   decorate: bool, warnings: list[str], workdir: Path) -> None:
    slide = prs.slides.add_slide(_layout(prs, "Title and Content", 1))
    brand = config.BRAND
    title = _placeholder(slide, TITLE_TYPES)
    if title is not None:
        size, ok = fit_size([data.title], title.width, title.height, config.TITLE_SIZES,
                            bold=True)
        if not ok:
            warnings.append(f"Slide {number} : titre trop long pour sa zone")
        _write(title.text_frame, [data.title], size, brand["primary"], bold=True,
               align=PP_ALIGN.LEFT, space_after=False)
        if decorate:  # filet sous le titre, du côté où le titre commence (arabe : à droite)
            rule_w = Inches(1.2)
            left = (title.left + title.width - MARGIN_X - rule_w) if is_rtl(data.title) \
                else title.left + MARGIN_X
            _rect(slide, left, title.top + title.height + Inches(0.05),
                  rule_w, Inches(0.06), brand["accent"])
    body = _placeholder(slide, BODY_TYPES)
    if body is not None and data.layout in ("chart", "diagram"):
        _visual(slide, body, data, number, workdir, warnings)
    if body is not None:
        if data.bullets:
            size, ok = fit_size(data.bullets, body.width, body.height, config.BODY_SIZES,
                                indent=BULLET_INDENT)
            if not ok:
                warnings.append(f"Slide {number} « {data.title} » : texte trop long, "
                                f"risque de débordement même en {size} pt")
            _write(body.text_frame, data.bullets, size, brand["text"])
        else:
            body._element.getparent().remove(body._element)  # pas de zone vide
    if decorate:
        _footer(slide, deck.title, f"{number} / {total}")
    _logo(slide, prs)
    slide.notes_slide.notes_text_frame.text = data.notes


def build_pptx(deck: Deck, out_path: Path, source: str = "") -> BuildResult:
    template = config.BRAND_TEMPLATE
    decorate = not template.exists()  # décor ajouté seulement avec notre template par défaut
    if decorate:
        template = config.TEMPLATES_DIR / "_default_16x9.pptx"
        if not template.exists():
            make_default_template(template)

    prs = Presentation(str(template))
    for sld in list(prs.slides._sldIdLst):  # un template peut contenir des slides d'exemple
        prs.part.drop_rel(sld.rId)
        prs.slides._sldIdLst.remove(sld)

    warnings: list[str] = []
    total = len(deck.slides)
    with tempfile.TemporaryDirectory() as tmp:  # images intégrées au PPTX puis supprimées
        for number, data in enumerate(deck.slides, start=1):
            if data.layout == "title" and number == 1:
                _title_slide(prs, deck, data, decorate, source)
            else:
                _content_slide(prs, deck, data, number, total, decorate, warnings, Path(tmp))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(out_path)
    return BuildResult(out_path, warnings)
