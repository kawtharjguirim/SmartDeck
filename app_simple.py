"""Étape 13 : interface Streamlit de SmartDeck.

Lancer :  .venv\\Scripts\\streamlit run app.py   puis ouvrir http://localhost:8501

Dépôt d'un fichier ou texte collé (FR-01), nombre de slides et langue (FR-04),
progression, aperçu, chiffres à vérifier (FR-12), téléchargement PPTX / PDF (FR-10)
et régénération d'une seule slide (FR-13). Tout tourne en local (NFR-01).
Option : agent relecteur (Qwen3-VL) qui relit, regarde les slides et corrige.
Thèmes : choix du thème (avec aperçu) et d'un logo ; changement de thème sans rappeler le LLM.
"""
import json
import re
from pathlib import Path

import pymupdf
import streamlit as st

import config
from agent import review
from build.template_import import IMPORT_DIR, TemplateError, delete_template, import_template
from build.theme_previews import ensure_previews
from agent.theme_advisor import AUTO, suggest_theme
from build.themes import DEFAULT_THEME, all_themes
from generate import Run, generate, generate_text, rebuild, regenerate_slide, safe_stem
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


@st.cache_resource(show_spinner="Préparation des aperçus de thèmes…")
def theme_previews() -> dict[str, Path | None]:
    """Vignettes des thèmes (générées une fois, puis lues dans templates/previews)."""
    return ensure_previews()


def preview_of(name: str) -> Path | None:
    """Vignette d'un thème intégré ou d'un modèle importé."""
    path = theme_previews().get(name) or IMPORT_DIR / f"{name}.png"
    return path if path.exists() else None


def theme_picker(label: str, key: str, default: str = DEFAULT_THEME, auto: bool = False) -> str:
    themes = all_themes()
    names = ([AUTO] if auto else []) + list(themes)
    if st.session_state.get(key) not in names:  # modèle supprimé entre-temps
        st.session_state.pop(key, None)
    if key not in st.session_state:  # valeur initiale (ensuite, l'état du widget fait foi)
        st.session_state[key] = default if default in names else names[0]
    return st.selectbox(label, names, key=key,
                        format_func=lambda n: "🤖 Auto (choisi par l'agent)" if n == AUTO
                        else themes[n].label)


def save_logo(logo_file) -> Path | None:
    if logo_file is None:
        return None
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / ("logo" + Path(logo_file.name).suffix.lower())
    path.write_bytes(logo_file.getvalue())
    return path


def ollama_status() -> str | None:
    """Message d'erreur si Ollama ou un modèle manque, sinon None."""
    try:
        missing = missing_models([config.PLAN_MODEL, config.WRITE_MODEL])
    except LLMError as e:
        return str(e)
    if missing:
        return "Modèles absents d'Ollama : " + ", ".join(missing)
    return None


def ollama_ok_models(models: list[str]) -> list[str]:
    """Modèles absents (liste vide si Ollama ne répond pas : l'erreur est affichée ailleurs)."""
    try:
        return missing_models(models)
    except LLMError:
        return []


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
    agent_missing = ollama_ok_models([config.AGENT_MODEL])
    n_slides = st.slider("Nombre de slides (titre compris)", config.MIN_SLIDES,
                         config.MAX_SLIDES, config.DEFAULT_SLIDES)
    language = LANGUAGES[st.selectbox("Langue", list(LANGUAGES))]
    with_pdf = st.toggle("Exporter aussi en PDF", value=True)
    st.divider()
    if "pending_theme" in st.session_state:  # modèle tout juste importé : on le sélectionne
        st.session_state.theme = st.session_state.pop("pending_theme")
    theme = theme_picker("🎨 Thème", "theme", auto=not agent_missing)
    st.caption("L'agent lit le début du document et choisit le thème le plus adapté."
               if theme == AUTO else all_themes()[theme].description)
    preview = None if theme == AUTO else preview_of(theme)
    if preview:
        st.image(str(preview), width="stretch")
    with st.expander("🏢 Importer un modèle d'entreprise"):
        st.caption("Fichier .pptx ou .potx. SmartDeck garde son fond, son décor et ses styles "
                   "de texte, et vérifie qu'il est exploitable.")
        template_file = st.file_uploader("Modèle PowerPoint", type=["pptx", "potx"],
                                         key="template_file")
        if template_file is not None and st.button("Importer ce modèle", width="stretch"):
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            source = UPLOAD_DIR / (safe_stem(template_file.name)
                                   + Path(template_file.name).suffix.lower())
            source.write_bytes(template_file.getvalue())
            with st.spinner("Analyse du modèle et aperçu…"):
                try:
                    imported, notes, _ = import_template(source)
                    st.session_state.import_notes = (imported.label, notes)
                    st.session_state.pending_theme = imported.name  # sélectionné au rechargement
                except TemplateError as e:
                    st.session_state.import_notes = (None, [str(e)])
            st.rerun()
        if "import_notes" in st.session_state:
            label, notes = st.session_state.import_notes
            if label:
                st.success(f"{label} importé et sélectionné.")
            else:
                st.error(f"Modèle refusé : {notes[0]}")
                notes = []
            for n in notes:
                st.caption(f"⚠ {n}")
        if theme.startswith("modele_") and st.button("Supprimer ce modèle", width="stretch"):
            delete_template(theme)
            st.session_state.pop("theme", None)
            st.session_state.pop("import_notes", None)
            st.rerun()
    logo_file = st.file_uploader("Logo (facultatif)", type=["png", "jpg", "jpeg"],
                                 help="Affiché en haut à droite de chaque slide.")
    st.divider()
    with_agent = st.toggle("🤖 Relecture par l'agent", value=False,
                           disabled=bool(agent_missing),
                           help=f"Après la génération, {config.AGENT_MODEL} regarde les slides, "
                                "réécrit celles qui ont des défauts mesurés et ne garde une "
                                "version que si elle n'est pas pire. Plus lent.")
    st.divider()
    problem = ollama_status()
    if problem:
        st.error(problem)
    else:
        st.success("Ollama prêt")
    if agent_missing:
        st.caption(f"Agent indisponible : ollama pull {config.AGENT_MODEL}")
    st.caption(f"Plan : {config.PLAN_MODEL} · Rédaction : {config.WRITE_MODEL} · "
               f"Vision : {config.VISION_MODEL} · Agent : {config.AGENT_MODEL}")
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
                run = generate(path, n_slides, language, pdf=with_pdf, progress=progress,
                               theme=theme, logo=save_logo(logo_file))
            else:
                run = generate_text(pasted, n_slides, language, pdf=with_pdf,
                                    progress=progress, theme=theme, logo=save_logo(logo_file))
            if with_agent:
                progress.bar.progress(0.95, text="Relecture par l'agent…")
                review(run, pdf=with_pdf, log=status.write)
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

    agent_report = report.get("agent")
    with st.expander("🤖 Agent relecteur", expanded=bool(agent_report)):
        if agent_report:
            st.markdown(f"**{agent_report['resume']}** — défauts mesurés "
                        f"{agent_report['defauts_avant']} → {agent_report['defauts_apres']}, "
                        f"{agent_report['secondes']:.0f} s")
            if agent_report.get("commentaire_agent"):
                st.caption(f"Commentaire de l'agent : {agent_report['commentaire_agent']}")
            for a in agent_report["actions"]:
                if a["outil"] == "reecrire_slide":
                    verdict = "gardée" if a["gardee"] else "rejetée (pas meilleure)"
                    st.markdown(f"- Slide {a['slide']} réécrite — {a['consigne']} → {verdict} "
                                f"({a['score_avant']} → {a['score_apres']})")
                elif a["outil"] == "passer":
                    st.markdown(f"- Slide {a['slide']} laissée telle quelle — {a['raison']}")
                else:
                    st.markdown(f"- Slide {a['slide']} regardée (image)")
        goal = st.text_input("Consigne pour l'agent (facultatif)",
                             placeholder="ex. « raccourcis les puces de la slide 3 »")
        if st.button("Lancer l'agent",
                     disabled=busy or problem is not None or bool(agent_missing)):
            with st.status("Relecture par l'agent…", expanded=True) as agent_status:
                try:
                    result = review(run, goal=goal, pdf=bool(pdf_file), log=agent_status.write)
                    agent_status.update(label=f"Agent : {result.summary}", state="complete")
                except (ValueError, LLMError) as e:
                    st.error(f"Agent impossible : {e}")
            st.rerun()

    current = all_themes().get(run.theme)
    with st.expander(f"🎨 Thème : {current.label if current else run.theme}"):
        st.caption("Change l'apparence sans rien réécrire : PPTX et PDF sont reconstruits "
                   "en quelques secondes.")
        t1, t2 = st.columns([2, 1], vertical_alignment="bottom")
        with t1:
            if "pending_result_theme" in st.session_state:  # proposition de l'agent
                st.session_state.theme_result = st.session_state.pop("pending_result_theme")
            new_theme = theme_picker("Nouveau thème", "theme_result", default=run.theme)
        if t2.button("Appliquer ce thème", disabled=busy or new_theme == run.theme,
                     width="stretch"):
            with st.spinner("Reconstruction…"):
                rebuild(run, pdf=bool(pdf_file), theme=new_theme)
            st.rerun()
        if report.get("theme_agent"):
            st.caption(f"🤖 Choix de l'agent : {report['theme_agent']}")
        if st.button("🤖 Proposer un thème", disabled=busy or bool(agent_missing),
                     help="L'agent lit le début du document et propose un thème."):
            with st.spinner("L'agent réfléchit…"):
                name, reason = suggest_theme(run.document, run.deck.title)
            st.session_state.pending_result_theme = name
            st.session_state.theme_suggestion = (name, reason)
            st.rerun()
        if "theme_suggestion" in st.session_state:
            name, reason = st.session_state.theme_suggestion
            st.info(f"Proposition : **{all_themes()[name].label}** — {reason} "
                    "(sélectionnée ci-dessus, cliquez sur « Appliquer ce thème »)")
        preview = preview_of(new_theme)
        if preview:
            st.image(str(preview), width="stretch")

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
