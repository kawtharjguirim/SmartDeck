"""Paramètres globaux de SmartDeck (voir cahier des charges, sections 8 et 12)."""
import os
from pathlib import Path

# --- Chemins -------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT_DIR / "output"
TEMPLATES_DIR = ROOT_DIR / "templates"
BRAND_TEMPLATE = TEMPLATES_DIR / "brand.pptx"

# --- Modèles (Ollama) ----------------------------------------------------
# Comparaison du 2026-11-17 (cahier des charges, 10 slides, RTX 2050 4 Go) :
#   - plan : le code pilote la structure, le 3B suffit (24 s contre 151 s en 7B) ;
#   - rédaction : le 7B fait 2 à 4 fois moins de doublons et de vraies notes orateur,
#     mais tourne à 58 % sur CPU (5,4 Go > 4 Go de VRAM).
# Surchargeables sans modifier le code : $env:SMARTDECK_WRITE_MODEL="qwen2.5:3b"
PLAN_MODEL = os.environ.get("SMARTDECK_PLAN_MODEL", "qwen2.5:3b")
WRITE_MODEL = os.environ.get("SMARTDECK_WRITE_MODEL", "qwen2.5:7b")
TEXT_MODEL = os.environ.get("SMARTDECK_TEXT_MODEL", PLAN_MODEL)  # appels génériques (test_llm.py)
# Vision (étape 10) : qwen2.5vl:3b (3,2 Go) au lieu du 7B prévu, trop lourd pour 4 Go.
VISION_MODEL = os.environ.get("SMARTDECK_VISION_MODEL", "qwen2.5vl:3b")
VISION_MAX_SIDE = 1024  # côté max de l'image envoyée au modèle vision (mémoire)
VISION_MAX_TOKENS = 800  # réponse attendue ≈ 200 tokens ; au-delà, le modèle boucle
VISION_RETRIES = 1
OLLAMA_HOST = "http://127.0.0.1:11434"  # local uniquement (NFR-01)

# --- Marque (FR-11) -----------------------------------------------------
# Si templates/brand.pptx existe, ses mises en page sont utilisées ; sinon un
# template 16:9 est créé. Un logo optionnel : templates/logo.png.
LOGO = TEMPLATES_DIR / "logo.png"
BRAND = {
    "font": "Calibri",           # police installée sous Windows (mesurée avec Pillow)
    "font_file": "calibri.ttf",  # fichier dans C:\Windows\Fonts pour mesurer le texte
    "primary": "1F3A5F",         # bleu nuit : titres, bandeau
    "accent": "E07A2E",          # orange : filet décoratif
    "text": "222222",
    "muted": "6B7280",           # gris : pied de page
}
TITLE_SIZES = (36, 32, 28, 24)          # tailles essayées pour un titre, en points
BODY_SIZES = (24, 22, 20, 18, 16, 14)   # tailles essayées pour les puces

# --- Génération (NFR-07 : reproductibilité) ------------------------------
TEMPERATURE = 0.2
SEED = 42
NUM_CTX = 8192  # taille du contexte ; à réduire si la VRAM sature
LLM_RETRIES = 2  # nouvelles tentatives si le JSON est invalide
MAX_OUTPUT_TOKENS = 4096  # longueur max d'une réponse du modèle

# --- Limites (FR-04, FR-05, section 3) -----------------------------------
MIN_SLIDES = 5
MAX_SLIDES = 30
DEFAULT_SLIDES = 10
MIN_BULLETS = 3
MAX_BULLETS = 5
TARGET_WORDS_PER_BULLET = 12
DEFAULT_LANGUAGE = "fr"

# Plan en deux temps (planner.py) — environ 4 caractères par token.
PART_MAX_CHARS = 2_500        # taille max d'une « partie » du document
SECTION_CONTEXT_CHARS = 6_000  # extraits envoyés pour planifier les slides d'une section
MAX_SECTIONS = 5
MAX_SLIDES_PER_CALL = 4        # au-delà, une section est planifiée en plusieurs appels
PLAN_COUNT_RETRIES = 1         # nouvelle tentative si le nombre de slides est faux

# Rédaction : extraits du document envoyés pour chaque slide.
WRITE_CONTEXT_CHARS = 4_000
WRITE_RETRIES = 2  # nouvelles tentatives si chiffre absent de la source ou puces répétées
DUPLICATE_THRESHOLD = 0.5  # part de mots communs au-delà de laquelle une puce est un doublon

# OCR (étape 9) : Tesseract, langues dans tessdata/ (fra, ara, eng, osd).
TESSERACT_CMD = os.environ.get("SMARTDECK_TESSERACT",
                               r"C:\Program Files\Tesseract-OCR\tesseract.exe")
TESSDATA_DIR = ROOT_DIR / "tessdata"
OCR_DPI = 300                # résolution de rendu des pages scannées
OCR_LATIN_LANGS = "fra+eng"  # écriture latine ; "ara" si l'OSD détecte de l'arabe
OCR_MIN_CONFIDENCE = 80      # confiance moyenne (0-100) sous laquelle un bloc est « à vérifier »
OCR_MIN_WIDTH = 2000         # image plus étroite → agrandie avant OCR (petits caractères)

# Visuels (étape 11) : Matplotlib pour les graphiques, Graphviz pour les diagrammes.
GRAPHVIZ_DOT = os.environ.get("SMARTDECK_DOT",
                              str(ROOT_DIR / "tools" / "graphviz" / "bin" / "dot.exe"))
VISUAL_DPI = 200          # résolution des images insérées dans les slides
MAX_DIAGRAM_NODES = 10    # au-delà de 5, le processus passe sur deux lignes
DIAGRAM_ROW = 5           # éléments par ligne dans un processus
VISUAL_BULLETS = 3        # puces gardées à côté d'un graphique ou d'un diagramme
# Diagrammes seulement à partir d'étapes trouvées par le code (liste numérotée, schéma lu
# par la vision). True : le LLM peut aussi en proposer (souvent sans objet avec le 3B).
LLM_DIAGRAMS = False

# Export PDF (étape 12) : LibreOffice sans fenêtre, extrait dans tools/libreoffice.
SOFFICE = os.environ.get("SMARTDECK_SOFFICE",
                         str(ROOT_DIR / "tools" / "libreoffice" / "program" / "soffice.exe"))
LIBREOFFICE_PROFILE = ROOT_DIR / ".cache" / "lo_profile"  # profil dédié, sur D:
PDF_TIMEOUT = 300  # secondes (le tout premier lancement crée le profil : ~1 min)

MAX_TEXT_CHARS = 50_000
MAX_PDF_PAGES = 100
MAX_SCANNED_PAGES = 30
MAX_IMAGE_MB = 10
