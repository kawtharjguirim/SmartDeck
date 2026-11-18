"""Modèles de données de SmartDeck (cahier des charges, section 9).

Le LLM ne peut produire que des objets validés par ces classes.
Lancer `python schemas.py` pour une démonstration : un Deck valide, puis un rejet attendu.
"""
from typing import Annotated, Literal, Optional

from pydantic import AfterValidator, BaseModel, Field, ValidationError, model_validator
from pydantic.json_schema import SkipJsonSchema


def _plain(value: str) -> str:
    """Refuse un texte qui ressemble à du JSON (erreur fréquente des petits modèles)."""
    v = value.strip()
    if v.startswith(("{", "[")) or '"content":' in v:
        raise ValueError("ce champ doit être du texte simple, pas du JSON")
    return v


PlainText = Annotated[str, AfterValidator(_plain)]

# --- Document normalisé (sortie de l'ingestion) --------------------------

BlockKind = Literal["title", "text", "table", "figure"]
Origin = Literal["text", "pdf", "scanned_pdf", "image"]


class Block(BaseModel):
    """Morceau de document extrait (titre, paragraphe, tableau ou figure)."""

    kind: BlockKind
    content: str = Field(min_length=1)
    page: Optional[int] = Field(default=None, ge=1)  # None pour un texte collé
    source: str  # nom du fichier d'origine
    needs_review: bool = False  # True si OCR ou vision : valeur à vérifier


class Document(BaseModel):
    """Entrée normalisée, quelle que soit sa source."""

    origin: Origin
    language: str = "fr"
    blocks: list[Block] = Field(min_length=1)
    notes: list[str] = []  # remarques de l'ingestion (ex. valeurs lues par la vision)

    def full_text(self) -> str:
        return "\n\n".join(b.content for b in self.blocks)


# --- Présentation (sortie du LLM) ---------------------------------------

ChartKind = Literal["bar", "line", "pie"]
SlideLayout = Literal["title", "section", "bullets", "chart", "diagram"]


class ChartSpec(BaseModel):
    """Spécification d'un graphique, rendu ensuite par Matplotlib."""

    kind: ChartKind
    title: str
    labels: list[str] = Field(min_length=1)
    values: list[float] = Field(min_length=1)
    unit: str = ""  # %, k€… (affichée sur l'axe et les étiquettes)

    @model_validator(mode="after")
    def check_lengths(self) -> "ChartSpec":
        # Règle du CDC : labels et values ont la même longueur.
        if len(self.labels) != len(self.values):
            raise ValueError(
                f"labels ({len(self.labels)}) et values ({len(self.values)}) "
                "doivent avoir la même longueur"
            )
        if self.kind == "pie" and any(v < 0 for v in self.values):
            raise ValueError("un camembert ne peut pas contenir de valeur négative")
        return self


class Slide(BaseModel):
    """Une diapositive."""

    layout: SlideLayout = "bullets"
    title: PlainText = Field(min_length=1, description="Titre court de la slide, texte simple")
    bullets: list[PlainText] = Field(
        default_factory=list, max_length=6,
        description="Puces de la slide : phrases courtes en texte simple",
    )
    notes: PlainText = Field(
        default="", description="Notes orateur : 2 ou 3 phrases en texte simple"
    )  # FR-06
    chart: Optional[ChartSpec] = None
    diagram_dot: Optional[str] = None  # code Graphviz (FR-08)

    @model_validator(mode="after")
    def check_layout(self) -> "Slide":
        if self.layout == "chart" and self.chart is None:
            raise ValueError("une slide 'chart' doit contenir un graphique")
        if self.layout == "diagram" and not self.diagram_dot:
            raise ValueError("une slide 'diagram' doit contenir diagram_dot")
        return self


class Deck(BaseModel):
    """Présentation complète produite par le LLM."""

    title: PlainText = Field(min_length=1, description="Titre de la présentation, texte simple")
    language: str = "fr"
    slides: list[Slide] = Field(min_length=1)


# --- Plan (sortie du planner, étape 6 ; FR-03) ----------------------------

PlannedLayout = Literal["bullets", "chart", "diagram"]


class PlannedSlide(BaseModel):
    """Une slide prévue dans le plan, avant rédaction."""

    title: PlainText = Field(min_length=1, description="Titre court de la slide")
    layout: PlannedLayout = Field(
        default="bullets",
        description="bullets par défaut ; chart seulement si le texte contient des chiffres "
                    "comparables ; diagram pour un processus ou une architecture",
    )
    key_point: PlainText = Field(
        min_length=1, description="Idée principale de la slide, en une phrase"
    )
    source_pages: list[int] = Field(
        default_factory=list, description="Pages du document où se trouve l'information"
    )
    # Rempli par le code (invisible pour le LLM) : indices des blocs de la section,
    # pour que le writer ne cherche ses extraits que dans cette section.
    source_blocks: SkipJsonSchema[list[int]] = Field(default_factory=list)
    # Étape 11, rempli par le code : données du graphique (reprises telles quelles d'un
    # tableau de la source, CA-02) ou étapes d'un schéma lu par la vision.
    chart: SkipJsonSchema[Optional[ChartSpec]] = None
    steps: SkipJsonSchema[list[str]] = Field(default_factory=list)


class DraftSection(BaseModel):
    """Plan, premier temps : une section regroupe des parties du document."""

    title: PlainText = Field(min_length=1, description="Titre court de la section")
    part_ids: list[int] = Field(
        min_length=1, description="Numéros des parties [P…] couvertes par la section"
    )


class DraftOutline(BaseModel):
    title: PlainText = Field(min_length=1, description="Titre de la présentation")
    sections: list[DraftSection] = Field(min_length=1)


class SectionSlides(BaseModel):
    """Plan, second temps : les slides d'une section."""

    slides: list[PlannedSlide] = Field(min_length=1)


class Section(BaseModel):
    title: PlainText = Field(min_length=1, description="Titre de la section")
    slides: list[PlannedSlide] = Field(min_length=1)


class Outline(BaseModel):
    """Plan de la présentation : titre, sections, slides (FR-03)."""

    title: PlainText = Field(min_length=1, description="Titre de la présentation")
    language: str = "fr"
    sections: list[Section] = Field(min_length=1)

    def planned_slides(self) -> list[PlannedSlide]:
        return [s for section in self.sections for s in section.slides]

    def slide_count(self) -> int:
        """Nombre total de slides, slide de titre comprise."""
        return 1 + len(self.planned_slides())

    def to_deck(self) -> Deck:
        """Squelette de Deck : titres en place, puces à rédiger (étape 7)."""
        slides = [Slide(layout="title", title=self.title)]
        slides += [
            # Les graphiques et diagrammes seront construits à l'étape 11.
            Slide(layout="bullets", title=s.title, notes=s.key_point)
            for s in self.planned_slides()
        ]
        return Deck(title=self.title, language=self.language, slides=slides)


# --- Rédaction (sortie du writer, étape 7 ; FR-05, FR-06) ----------------

MAX_WORDS_PER_BULLET = 20  # cible ≈ 12 mots, tolérance jusqu'à 20


def _short_bullet(value: str) -> str:
    words = len(value.split())
    if words > MAX_WORDS_PER_BULLET:
        raise ValueError(
            f"puce trop longue ({words} mots, maximum {MAX_WORDS_PER_BULLET}) : « {value} »"
        )
    return value


Bullet = Annotated[PlainText, AfterValidator(_short_bullet)]


class SlideContent(BaseModel):
    """Contenu rédigé d'une slide : ce que le LLM renvoie pour chaque slide."""

    bullets: list[Bullet] = Field(
        min_length=3, max_length=5,
        description="3 à 5 puces d'environ 12 mots chacune, en texte simple",
    )
    notes: PlainText = Field(
        min_length=20, description="Notes orateur : 2 à 4 phrases que l'orateur peut dire"
    )


# --- Diagramme (étape 11 ; FR-08) ------------------------------------------
# Le modèle donne une liste d'éléments, le code écrit le Graphviz : un petit modèle
# produit souvent du code DOT invalide.

MAX_WORDS_PER_NODE = 6


def _short_node(value: str) -> str:
    if len(value.split()) > MAX_WORDS_PER_NODE:
        raise ValueError(f"élément trop long (maximum {MAX_WORDS_PER_NODE} mots) : « {value} »")
    return value


NodeLabel = Annotated[PlainText, AfterValidator(_short_node)]


class DiagramSpec(BaseModel):
    """Contenu d'un diagramme : le code en tire le code Graphviz."""

    kind: Literal["process", "hierarchy"] = Field(
        description="process : étapes successives ; hierarchy : un élément central (le "
                    "premier) relié à tous les autres")
    # Jusqu'à 10 pour une liste numérotée détectée par le code ; le LLM est guidé vers 2 à 6.
    nodes: list[NodeLabel] = Field(min_length=2, max_length=10,
                                   description="2 à 6 éléments de 1 à 5 mots, dans l'ordre")


# --- Vision (sortie du modèle vision, étape 10 ; FR-09) --------------------

ImageKind = Literal["chart", "diagram", "table", "text", "photo", "other"]


class ImageAnalysis(BaseModel):
    """Ce que le modèle vision lit dans une image. Tout est « à vérifier »."""

    kind: ImageKind = Field(description="Type d'image")
    title: PlainText = Field(description="Titre visible dans l'image, sinon titre court descriptif")
    description: PlainText = Field(min_length=20,
                                   description="2 à 4 phrases : ce que montre l'image")
    chart_kind: Optional[ChartKind] = Field(default=None,
                                            description="Pour un graphique : bar, line ou pie")
    labels: list[str] = Field(default=[], description="Graphique : étiquettes lisibles, dans l'ordre")
    values: list[float] = Field(default=[], description="Graphique : valeur de chaque étiquette")
    unit: str = Field(default="", description="Graphique : unité des valeurs (%, k€…)")
    steps: list[str] = Field(default=[], description="Schéma : étapes ou éléments, dans l'ordre")

    @model_validator(mode="after")
    def check_values(self) -> "ImageAnalysis":
        # Erreur fréquente du petit modèle : un schéma pris pour un graphique, ses étapes
        # rangées dans labels sans aucune valeur. Corrigé ici plutôt que par une relance.
        if self.labels and not self.values:
            self.steps = self.steps or self.labels
            self.labels = []
            if self.kind == "chart":
                self.kind = "diagram"
            self.chart_kind = None
        if self.kind != "chart":  # valeurs sans objet hors graphique : ignorées
            self.labels, self.values, self.chart_kind = [], [], None
        if len(self.labels) != len(self.values):
            raise ValueError(f"labels ({len(self.labels)}) et values ({len(self.values)}) "
                             "doivent avoir la même longueur")
        return self


# --- Démonstration (vérification de l'étape 3) ---------------------------

if __name__ == "__main__":
    deck = Deck(
        title="Bilan annuel",
        slides=[
            Slide(layout="title", title="Bilan annuel 2026"),
            Slide(
                title="Chiffres clés",
                bullets=["Le chiffre d'affaires progresse de 12 % sur l'année"],
                notes="Insister sur la croissance du second semestre.",
            ),
            Slide(
                layout="chart",
                title="Ventes par trimestre",
                chart=ChartSpec(
                    kind="bar",
                    title="Ventes (k€)",
                    labels=["T1", "T2", "T3", "T4"],
                    values=[120, 135, 150, 170],
                ),
            ),
        ],
    )
    print(f"OK : Deck valide « {deck.title} » avec {len(deck.slides)} slides")

    print("\nTest d'un graphique invalide (3 labels, 2 valeurs) :")
    try:
        ChartSpec(kind="pie", title="Parts", labels=["A", "B", "C"], values=[50, 50])
    except ValidationError as e:
        print("REJET ATTENDU :", e.errors()[0]["msg"])
    else:
        raise SystemExit("ERREUR : le graphique invalide aurait dû être rejeté")
