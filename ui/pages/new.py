"""Nouvelle présentation : source + réglages → plan proposé (à valider sur la page du projet)."""
import time
from pathlib import Path

import streamlit as st

import config
from agent.theme_advisor import AUTO
from build.themes import all_themes
from generate import draft_outline, save_draft
from ingest import IngestError, load_document, load_pasted_text
from llm.client import LLMError
from ui import common, store, style

PLAN_STEPS = [("Lecture", "du document"), ("Plan", "des slides"), ("Validation", "par vous")]


def new_page() -> None:
    user = common.current_user()
    prefs = user.prefs
    style.page_header("Nouvelle présentation",
                      "Donnez une source à SmartDeck. Vous relirez le plan avant qu'une seule "
                      "slide ne soit rédigée.")
    problem = common.ollama_problem()
    if problem:
        st.error(problem)

    left, right = st.columns([3, 2], gap="large")
    with left:
        title = st.text_input("Titre de la présentation", placeholder="Revue produit T3",
                              help="Facultatif : sinon, le titre proposé par le plan.")
        tab_file, tab_text = st.tabs(["📄 Fichier", "✏️ Coller un texte"])
        with tab_file:
            uploaded = st.file_uploader("Document", type=common.FILE_TYPES,
                                        help="Texte .txt/.md, PDF (natif ou scanné), "
                                             "image .png/.jpg/.webp")
        with tab_text:
            pasted = st.text_area("Texte source", height=260, max_chars=config.MAX_TEXT_CHARS,
                                  placeholder="Collez le contenu à transformer en slides…")
    with right:
        with st.container(border=True):
            st.markdown("**Réglages**")
            n_slides = st.slider("Nombre de slides (titre compris)", config.MIN_SLIDES,
                                 config.MAX_SLIDES, int(prefs["slides"]))
            languages = list(common.LANGUAGES)
            default_lang = next((k for k, v in common.LANGUAGES.items()
                                 if v == prefs["language"]), languages[0])
            language = common.LANGUAGES[st.selectbox("Langue", languages,
                                                      index=languages.index(default_lang))]
            themes = all_themes()
            names = ([AUTO] if common.agent_available() else []) + list(themes)
            default_theme = prefs["theme"] if prefs["theme"] in names else names[0]
            theme = st.selectbox("Thème", names, index=names.index(default_theme),
                                 format_func=lambda n: "🤖 Auto (choisi par l'agent)" if n == AUTO
                                 else themes[n].label)
            preview = common.theme_preview(theme) if theme != AUTO else None
            if preview:
                st.image(str(preview), width="stretch")
            st.caption("🤖 L'agent lira le document pour choisir." if theme == AUTO else
                       "Le thème se change aussi après coup, sans rien réécrire.")

    has_input = uploaded is not None or bool(pasted.strip())
    if not st.button("Générer le plan", type="primary", disabled=not has_input or bool(problem)):
        return

    source_name = uploaded.name if uploaded is not None else "texte collé"
    project = store.create_project(user, title or Path(source_name).stem, source_name,
                                   n_slides, theme)
    progress = common.ProgressView("Lecture du document et plan…", steps=PLAN_STEPS)
    status = progress.status
    try:
        t = time.perf_counter()
        if uploaded is not None:  # le fichier est prioritaire sur le texte collé
            progress(1, 5, "Lecture du document…")
            document = load_document(common.save_upload(uploaded, user,
                                                        f"projet_{project.id}"))
        else:
            if len(pasted) > config.MAX_TEXT_CHARS:
                raise IngestError(f"texte de {len(pasted)} caractères, "
                                  f"limite {config.MAX_TEXT_CHARS}")
            document = load_pasted_text(pasted)
        for note in document.notes:
            status.write(f"ℹ {note}")
        draft = draft_outline(document, source_name, n_slides, language, progress,
                              time.perf_counter() - t)
        if title.strip():
            draft.outline.title = title.strip()
        save_draft(Path(project.stem), draft)
        progress.finish("Plan prêt : à vous de le relire", step=3)
        store.update_project(project, title=draft.outline.title, status="outline")
        common.flash("Plan prêt : relisez-le avant la rédaction", "🧭")
        common.open_project(project.id)
    except (IngestError, ValueError, LLMError) as e:
        progress.fail("Plan impossible")
        store.update_project(project, status="failed")
        st.error(f"Plan impossible : {e}")
