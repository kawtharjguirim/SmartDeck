"""Import d'un modèle PowerPoint d'entreprise (FR-11) : .pptx ou .potx.

Le modèle garde la main sur son apparence : fond, décor, couleurs et polices des
zones de texte viennent de ses masques et mises en page. SmartDeck y place le
contenu et ne fixe que la taille du texte (mesurée pour éviter le débordement).

Analyse à l'import, avec un rapport lisible :
1. mises en page choisies par leur contenu (zones titre et texte), pas par leur nom ;
2. polices du masque (sinon du thème), cherchées parmi les polices installées ;
   absente → mesure avec Arial et avertissement (PowerPoint la remplacera) ;
3. couleurs des graphiques : palette du thème du modèle, texte clair ou foncé selon
   la luminosité du fond, mesurée sur un rendu réel (LibreOffice) ;
4. aperçu : 3 slides d'exemple construites avec le modèle.
Refus si aucune mise en page n'a de zone de titre et de zone de texte.
"""
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path

import pymupdf
from lxml import etree
from PIL import Image, ImageFont, ImageStat
from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

import config
from build.themes import Theme

IMPORT_DIR = config.TEMPLATES_DIR / "imported"
PREFIX = "modele_"
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
TITLE = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}
BODY = {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT}
SUBTITLE = {PP_PLACEHOLDER.SUBTITLE}
FONT_DIRS = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
FALLBACK = ("Arial", "arial.ttf", "arialbd.ttf")


class TemplateError(ValueError):
    """Modèle inutilisable (fichier illisible, aucune mise en page exploitable)."""


# --- Polices installées ---------------------------------------------------------

_font_index: dict[tuple[str, bool], str] | None = None


def installed_fonts() -> dict[tuple[str, bool], str]:
    """(famille en minuscules, gras ?) → fichier, pour les polices installées."""
    global _font_index
    if _font_index is None:
        _font_index = {}
        for folder in FONT_DIRS:
            if not folder.is_dir():
                continue
            for f in folder.iterdir():
                if f.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                    continue
                try:
                    family, style = ImageFont.truetype(str(f), 12).getname()
                except OSError:
                    continue
                bold = "bold" in style.lower() and "italic" not in style.lower()
                regular = style.lower() in ("regular", "normal", "book", "roman")
                if bold or regular:
                    _font_index.setdefault((family.lower(), bold), str(f))
    return _font_index


def font_files(name: str) -> tuple[str, str] | None:
    """(normal, gras) d'une police installée ; None si absente."""
    fonts = installed_fonts()
    regular = fonts.get((name.lower(), False))
    if regular is None:
        return None
    return regular, fonts.get((name.lower(), True), regular)


# --- Lecture du modèle ----------------------------------------------------------

def _open(path: Path, workdir: Path) -> tuple[Presentation, Path]:
    """Ouvre le modèle ; un .potx est converti en .pptx (seul le type de contenu change)."""
    target = workdir / (path.stem + ".pptx")
    if path.suffix.lower() == ".potx":
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    data = data.replace(b"presentationml.template.main+xml",
                                        b"presentationml.presentation.main+xml")
                dst.writestr(item, data)
    else:
        shutil.copy(path, target)
    try:
        return Presentation(str(target)), target
    except Exception as e:  # fichier corrompu, autre format renommé…
        raise TemplateError(f"fichier PowerPoint illisible : {e}") from e


def normalize_placeholders(prs: Presentation) -> int:
    """Numéros (idx) en double dans une mise en page : une zone de slide hérite de la zone
    de la mise en page qui a le même idx. Si titre et texte ont tous deux idx 0 (fréquent
    dans les modèles exportés par LibreOffice), le texte prend la place du titre.
    On donne un idx unique aux zones autres que le titre. Renvoie le nombre de zones corrigées."""
    fixed = 0
    for layout in prs.slide_layouts:
        seen: set[int] = set()
        phs = sorted(layout.placeholders,
                     key=lambda ph: ph.placeholder_format.type not in TITLE)  # titre d'abord
        top = max((ph.placeholder_format.idx for ph in phs), default=0)
        for ph in phs:
            idx = ph.placeholder_format.idx
            if idx in seen:
                top += 1
                ph._element.ph.set("idx", str(top + 100))
                fixed += 1
            else:
                seen.add(idx)
    return fixed


def _types(layout) -> set:
    return {ph.placeholder_format.type for ph in layout.placeholders}


def _area(layout, types) -> int:
    return max((ph.width * ph.height for ph in layout.placeholders
                if ph.placeholder_format.type in types and ph.width and ph.height), default=0)


def choose_layouts(prs: Presentation) -> tuple[int, int]:
    """(mise en page de titre, mise en page de contenu), par leurs zones."""
    layouts = list(prs.slide_layouts)
    content = [i for i, l in enumerate(layouts) if _types(l) & TITLE and _types(l) & BODY]
    if not content:
        raise TemplateError("aucune mise en page n'a à la fois une zone de titre et une zone "
                            "de texte : ajoutez-en une (« Titre et contenu ») dans le modèle")
    # Contenu : la plus grande zone de texte (place pour les puces et les visuels).
    content_i = max(content, key=lambda i: _area(layouts[i], BODY))
    # Titre : titre centré ou titre + sous-titre ; sinon la mise en page de contenu.
    title = [i for i, l in enumerate(layouts)
             if PP_PLACEHOLDER.CENTER_TITLE in _types(l) or (_types(l) & TITLE and _types(l) & SUBTITLE)]
    return (title[0] if title else content_i), content_i


def _theme_xml(prs: Presentation):
    try:
        return etree.fromstring(prs.slide_master.part.part_related_by(RT.THEME).blob)
    except (KeyError, etree.XMLSyntaxError):
        return None


def _scheme(theme_xml) -> dict[str, str]:
    colors = {}
    scheme = theme_xml.find(".//a:clrScheme", NS) if theme_xml is not None else None
    for c in scheme if scheme is not None else []:
        if len(c):
            value = c[0].get("val") if c[0].tag.endswith("srgbClr") else c[0].get("lastClr")
            if value and re.fullmatch(r"[0-9A-Fa-f]{6}", value):
                colors[etree.QName(c).localname] = value.upper()
    return colors


def _placeholder_font(prs: Presentation, types: set) -> str | None:
    """Police écrite dans le masque pour ce type de zone, ou dans ses styles de texte."""
    master = prs.slide_master
    for ph in master.placeholders:
        if ph.placeholder_format.type in types:
            latin = ph._element.find(".//a:latin", NS)
            if latin is not None and not latin.get("typeface", "+").startswith("+"):
                return latin.get("typeface")
    style = "p:titleStyle" if types & TITLE else "p:bodyStyle"
    latin = master._element.find(f".//{style}//a:latin", NS)
    if latin is not None and not latin.get("typeface", "+").startswith("+"):
        return latin.get("typeface")
    return None


def _theme_font(theme_xml, kind: str) -> str | None:
    if theme_xml is None:
        return None
    latin = theme_xml.find(f".//a:{kind}Font/a:latin", NS)
    return latin.get("typeface") if latin is not None else None


def _resolve_font(name: str | None, warnings: list[str], role: str) -> tuple[str, str, str]:
    """(nom, fichier normal, fichier gras) ; police absente → Arial pour mesurer."""
    if name:
        files = font_files(name)
        if files:
            return name, *files
        warnings.append(f"Police {role} « {name} » absente de ce PC : le texte est mesuré avec "
                        f"Arial ; PowerPoint ou LibreOffice afficheront une police de remplacement.")
    return FALLBACK


def _luminance(image: Image.Image) -> float:
    r, g, b = ImageStat.Stat(image.convert("RGB")).median
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


# --- Import -----------------------------------------------------------------------

def slug(name: str) -> str:
    s = re.sub(r"[^\w-]+", "_", Path(name).stem.lower(), flags=re.UNICODE).strip("_")
    return PREFIX + (s[:40] or "modele")


def analyse(path: Path, label: str | None = None) -> tuple[Theme, list[str]]:
    """Lit le modèle et en déduit un Theme (sans rendu). Lève TemplateError si inutilisable."""
    warnings: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        prs, _ = _open(path, Path(tmp))
        title_i, content_i = choose_layouts(prs)
        if title_i == content_i:
            warnings.append("Pas de mise en page de titre : la slide de titre utilise la mise "
                            "en page de contenu.")
        ratio = prs.slide_width / prs.slide_height
        if abs(ratio - 16 / 9) > 0.05:
            warnings.append(f"Format {prs.slide_width / 914400:.1f} × "
                            f"{prs.slide_height / 914400:.1f} in (pas 16:9) : accepté, les "
                            "visuels s'adaptent à la zone de texte.")
        theme_xml = _theme_xml(prs)
        colors = _scheme(theme_xml)
        title_name = _placeholder_font(prs, TITLE) or _theme_font(theme_xml, "major")
        body_name = _placeholder_font(prs, BODY) or _theme_font(theme_xml, "minor")
    title_font, _, title_bold = _resolve_font(title_name, warnings, "des titres")
    body_font, body_file, _ = _resolve_font(body_name, warnings, "du texte")
    accents = [colors.get(f"accent{i}") for i in range(1, 7)]
    if accents[:2] == ["18A303", "0369A3"]:
        # Palette par défaut de LibreOffice : elle ne dit rien du design du modèle.
        warnings.append("Le modèle ne définit pas ses propres couleurs de thème : graphiques "
                        "et diagrammes en gris et bleu neutres.")
        accents = ["334155", "2563EB", "94A3B8", "0F766E", "CBD5E1", "1E293B"]
    palette = ["#" + c for c in accents if c] or ["#1F3A5F", "#E07A2E", "#4A6B8A", "#8FA3B8"]
    theme = Theme(
        name=slug(path.name), label=label or f"Modèle : {path.stem}",
        description=f"Modèle importé ({path.name}) : fond, décor et styles du modèle.",
        font=body_font, font_file=body_file, title_font=title_font, title_font_file=title_bold,
        primary=palette[0].lstrip("#"), accent=(palette[1] if len(palette) > 1 else palette[0]).lstrip("#"),
        text=colors.get("dk1", "222222"), muted="6B7280", title_color=colors.get("dk2", "222222"),
        background=None, title_bg=None, title_slide_text=colors.get("dk2", "222222"),
        title_slide_sub="6B7280", grid="E5E7EB", palette=palette,
        template=None, title_layout=title_i, content_layout=content_i, inherit=True)
    return theme, warnings


def import_template(source: Path, label: str | None = None) -> tuple[Theme, list[str], Path]:
    """Analyse, copie dans templates/imported, mesure le fond, crée l'aperçu.

    Renvoie (thème, avertissements, aperçu). Le thème est ensuite disponible par son nom
    (get_theme) dans l'interface et en ligne de commande (--theme modele_xxx).
    """
    from build.pdf_export import PdfExportError, export_pdf
    from build.pptx_builder import build_pptx
    from build.theme_previews import DEMO

    theme, warnings = analyse(source, label)
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    stored = IMPORT_DIR / f"{theme.name}.pptx"
    with tempfile.TemporaryDirectory() as tmp:
        prs, _ = _open(source, Path(tmp))
        fixed = normalize_placeholders(prs)
        if fixed:
            warnings.append(f"{fixed} zone(s) réservée(s) renumérotée(s) : elles partageaient le "
                            "numéro de la zone de titre (position et style confondus).")
        prs.save(stored)
    theme = Theme(**(asdict(theme) | {"template": str(stored)}))

    # Rendu d'essai : vérifie que le modèle se construit, mesure la luminosité du fond.
    preview = IMPORT_DIR / f"{theme.name}.png"
    with tempfile.TemporaryDirectory() as tmp:
        pptx = Path(tmp) / "essai.pptx"
        result = build_pptx(DEMO, pptx, source="exemple.pdf", theme=theme, logo=Path("absent"))
        warnings += [f"Essai : {w}" for w in result.warnings]
        try:
            pdf, _ = export_pdf(pptx, Path(tmp))
            with pymupdf.open(pdf) as doc:
                pages = [doc[i].get_pixmap(dpi=40) for i in range(len(doc))]
        except PdfExportError as e:
            warnings.append(f"Aperçu impossible : {e}")
            pages = []
    images = [Image.frombytes("RGB", (p.width, p.height), p.samples) for p in pages]
    if images:
        # Fond de la slide de contenu : bande sous le titre, à droite (hors puces).
        content = images[1] if len(images) > 1 else images[0]
        w, h = content.size
        dark = _luminance(content.crop((int(w * 0.75), int(h * 0.35), w - 2, int(h * 0.9)))) < 0.45
        if dark:
            theme = Theme(**(asdict(theme) | {"text": "EEEEEE", "muted": "B0B7C3",
                                              "grid": "4B5563"}))
        else:
            theme = Theme(**(asdict(theme) | {"text": "222222"}))
        gap = 10
        sheet = Image.new("RGB", (len(images) * w + (len(images) - 1) * gap, h), "#D1D5DB")
        for i, im in enumerate(images):
            sheet.paste(im, (i * (w + gap), 0))
        sheet.save(preview)
        # L'essai a été fait avec les couleurs provisoires : on refait l'aperçu si elles changent.
        if dark:
            with tempfile.TemporaryDirectory() as tmp:
                pptx = Path(tmp) / "essai.pptx"
                build_pptx(DEMO, pptx, source="exemple.pdf", theme=theme, logo=Path("absent"))
                try:
                    pdf, _ = export_pdf(pptx, Path(tmp))
                    with pymupdf.open(pdf) as doc:
                        images = [Image.frombytes("RGB", (p.width, p.height), p.samples)
                                  for p in (pg.get_pixmap(dpi=40) for pg in doc)]
                    for i, im in enumerate(images):
                        sheet.paste(im, (i * (w + gap), 0))
                    sheet.save(preview)
                except PdfExportError:
                    pass
    (IMPORT_DIR / f"{theme.name}.json").write_text(
        json.dumps({"theme": asdict(theme), "avertissements": warnings, "source": source.name},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return theme, warnings, preview


def imported_themes() -> dict[str, Theme]:
    """Modèles déjà importés (templates/imported/*.json)."""
    themes = {}
    for f in sorted(IMPORT_DIR.glob(f"{PREFIX}*.json")) if IMPORT_DIR.is_dir() else []:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))["theme"]
            if Path(data["template"]).exists():
                themes[data["name"]] = Theme(**data)
        except (KeyError, TypeError, ValueError):
            continue
    return themes


def delete_template(name: str) -> None:
    for ext in ("pptx", "json", "png"):
        (IMPORT_DIR / f"{name}.{ext}").unlink(missing_ok=True)


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        try:
            t, warns, prev = import_template(Path(arg))
        except TemplateError as e:
            print(f"✘ {arg} : {e}")
            continue
        print(f"✔ {arg} → thème « {t.name} » (mises en page {t.title_layout}/{t.content_layout}, "
              f"polices {t.title_font} / {t.font}, texte #{t.text}) ; aperçu {prev}")
        for w in warns:
            print(f"   ⚠ {w}")
