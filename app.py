"""Étape 13 : interface Streamlit de SmartDeck.

Lancer :  .venv\\Scripts\\streamlit run app.py   puis ouvrir http://localhost:8501

Dépôt d'un fichier ou texte collé (FR-01), nombre de slides et langue (FR-04),
progression, aperçu, chiffres à vérifier (FR-12), téléchargement PPTX / PDF (FR-10)
et régénération d'une seule slide (FR-13). Tout tourne en local (NFR-01).
"""
import json
import re
from pathlib import Path

import pymupdf
import streamlit as st

import config
from generate import Run, generate, generate_text, regenerate_slide, safe_stem
from ingest import IngestError
from llm.client import LLMError, missing_models

UPLOAD_DIR = config.ROOT_DIR / ".cache" / "uploads"
LANGUAGES = {"Auto (langue du document)": None, "Français": "fr", "English": "en",
             "العربية": "ar"}
FILE_TYPES = ["txt", "md", "pdf", "png", "jpg", "jpeg", "webp"]

st.set_page_config(page_title="SmartDeck", page_icon="📊", layout="wide")


# --- Outils -------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def pdf_pages(pdf_path: str, mtime: float) -> list[bytes]:
    """Aperçu : chaque page du PDF en PNG (mtime invalide le cache après régénération)."""
    with pymupdf.open(pdf_path) as doc:
        return [page.get_pixmap(dpi=72).tobytes("png") for page in doc]


def ollama_status() -> str | None:
    """Message d'erreur si Ollama ou un modèle manque, sinon None."""
    try:
        missing = missing_models([config.PLAN_MODEL, config.WRITE_MODEL])
    except LLMError as e:
        return str(e)
    if missing:
        return "Modèles absents d'Ollama : " + ", ".join(missing)
    return None


class ProgressView:
    """Relie la progression du pipeline (étape, total, message) à l'interface."""

    def __init__(self, status):
        self.status = status
        self.bar = st.progress(0.0)

    def __call__(self, step: int, total: int, message: str) -> None:
        m = re.search(r"Rédaction (\d+)/(\d+)", message)
        if m:  # la rédaction est l'étape la plus longue : progression slide par slide
            fraction = 0.25 + 0.6 * (int(m.group(1)) - 1) / int(m.group(2))
        else:
            fraction = {1: 0.05, 2: 0.15, 3: 0.85, 4: 0.9, 5: 0.95}.get(step)
        if fraction is not None:
            self.bar.progress(fraction, text=message)
        self.status.update(label=message)
        self.status.write(message)


# --- Barre latérale : paramètres ---------------------------------------------

with st.sidebar:
    st.header("Paramètres")
    n_slides = st.slider("Nombre de slides (titre compris)", config.MIN_SLIDES,
                         config.MAX_SLIDES, config.DEFAULT_SLIDES)
    language = LANGUAGES[st.selectbox("Langue", list(LANGUAGES))]
    with_pdf = st.toggle("Exporter aussi en PDF", value=True)
    st.divider()
    problem = ollama_status()
    if problem:
        st.error(problem)
    else:
        st.success("Ollama prêt")
    st.caption(f"Plan : {config.PLAN_MODEL} · Rédaction : {config.WRITE_MODEL} · "
               f"Vision : {config.VISION_MODEL}")
    st.caption("Tout reste sur ce PC : aucun document n'est envoyé sur Internet.")

# --- Entrée ---------------------------------------------------------------------

st.title("SmartDeck")
st.write("Transforme un document (texte, PDF, PDF scanné ou image) en présentation PowerPoint.")

busy = st.session_state.get("busy", False)
tab_file, tab_text = st.tabs(["📄 Fichier", "✏️ Texte collé"])
with tab_file:
    uploaded = st.file_uploader("Document", type=FILE_TYPES,
                                help="Texte .txt/.md, PDF (natif ou scanné), image .png/.jpg/.webp")
with tab_text:
    pasted = st.text_area("Texte", height=220, max_chars=config.MAX_TEXT_CHARS,
                          placeholder="Collez ici le texte à transformer en présentation…")

has_input = uploaded is not None or bool(pasted.strip())
if st.button("Générer la présentation", type="primary",
             disabled=busy or not has_input or problem is not None):
    st.session_state.busy = True
    st.session_state.pop("run", None)
    try:
        with st.status("Génération en cours…", expanded=True) as status:
            progress = ProgressView(status)
            if uploaded is not None:  # le fichier déposé est prioritaire sur le texte collé
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                name = safe_stem(uploaded.name) + Path(uploaded.name).suffix.lower()
                path = UPLOAD_DIR / name
                path.write_bytes(uploaded.getvalue())
                run = generate(path, n_slides, language, pdf=with_pdf, progress=progress)
            else:
                run = generate_text(pasted, n_slides, language, pdf=with_pdf,
                                    progress=progress)
            progress.bar.progress(1.0, text="Terminé")
            status.update(label=f"Terminé en {run.report['durees']['total_s']:.0f} s",
                          state="complete", expanded=False)
        st.session_state.run = run
    except (IngestError, ValueError, LLMError) as e:
        st.error(f"Génération impossible : {e}")
    finally:
        st.session_state.busy = False

# --- Résultat -------------------------------------------------------------------

run: Run | None = st.session_state.get("run")
if run:
    report = run.report
    st.divider()
    st.subheader(run.deck.title)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Slides", f"{report['slides_produites']} / {report['slides_demandees']}")
    c2.metric("Durée", f"{report['durees']['total_s']:.0f} s")
    c3.metric("Chiffres à vérifier", len(report["a_verifier"]))
    c4.metric("Source", report["ingestion"]["origine"])

    d1, d2, d3 = st.columns(3)
    pptx = run.path("pptx")
    d1.download_button("⬇️ PowerPoint (.pptx)", pptx.read_bytes(), file_name=pptx.name,
                       mime="application/vnd.openxmlformats-officedocument."
                            "presentationml.presentation", width="stretch")
    pdf_file = report["fichiers"].get("pdf")
    if pdf_file and Path(pdf_file).exists():
        d2.download_button("⬇️ PDF", Path(pdf_file).read_bytes(), file_name=Path(pdf_file).name,
                           mime="application/pdf", width="stretch")
    d3.download_button("⬇️ Rapport (.json)", json.dumps(report, ensure_ascii=False, indent=2),
                       file_name=run.path("report.json").name, mime="application/json",
                       width="stretch")

    to_review = report["a_verifier"] + [f"Extrait à relire : {b}"
                                        for b in report["ingestion"]["blocs_a_verifier"]]
    if to_review:
        with st.expander(f"🔎 À vérifier ({len(to_review)})", expanded=True):
            for item in to_review:
                st.markdown(f"- {item}")
    if report["avertissements"] or report["ingestion"]["remarques"]:
        with st.expander("ℹ️ Remarques et avertissements"):
            for item in report["ingestion"]["remarques"] + report["avertissements"]:
                st.markdown(f"- {item}")

    st.subheader("Aperçu")
    pages = []
    if pdf_file and Path(pdf_file).exists():
        pages = pdf_pages(pdf_file, Path(pdf_file).stat().st_mtime)
    for i, slide in enumerate(run.deck.slides):
        left, right = st.columns([3, 2], vertical_alignment="top")
        with left:
            if i < len(pages):
                st.image(pages[i], width="stretch")
            else:
                st.markdown(f"**{i + 1}. {slide.title}**")
                for b in slide.bullets:
                    st.markdown(f"- {b}")
        with right:
            st.markdown(f"**Slide {i + 1}** · {slide.layout}")
            st.caption("Notes orateur")
            st.write(slide.notes or "—")
            if i > 0 and st.button("🔄 Régénérer cette slide", key=f"regen_{i}",
                                   disabled=busy or problem is not None):
                with st.spinner(f"Régénération de la slide {i + 1}…"):
                    try:
                        regenerate_slide(run, i, pdf=bool(pdf_file))
                    except (ValueError, LLMError) as e:
                        st.error(f"Régénération impossible : {e}")
                st.rerun()
        st.divider()
