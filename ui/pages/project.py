"""Page d'un projet : plan à valider, puis slides (aperçu, édition, régénération),
thème, agent relecteur et export."""
import json
from pathlib import Path

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from agent import review
from agent.theme_advisor import AUTO, suggest_theme
from build.themes import all_themes
from generate import (Run, build_from_draft, load_draft, load_run, rebuild, regenerate_slide,
                      replace_slide, save_draft)
from llm.client import LLMError
from schemas import Section, Slide
from ui import common, store, style
from ui.viewer import slide_viewer

BUILD_STEPS = [("Lecture", "du document"), ("Plan", "validé"), ("Rédaction", "puces et notes"),
               ("Mise en page", "PPTX et visuels"), ("Export", "PDF")]
LAYOUTS = {"bullets": "Puces", "chart": "Graphique", "diagram": "Diagramme", "title": "Titre",
           "image": "Image"}


def project_page() -> None:
    user = common.current_user()
    project = store.get_project(user, st.session_state.get("project_id", -1))
    if project is None:
        style.page_header("Projet introuvable", "Ce projet n'existe pas ou n'est pas le vôtre.")
        if st.button("Retour aux projets"):
            st.switch_page(common.PAGES["projets"])
        return
    head, status = st.columns([5, 1.3], vertical_alignment="center")
    with head:
        style.page_header(project.title, f"Source : {project.source}")
    status.markdown(style.badge(project.status), unsafe_allow_html=True)

    if project.status == "outline":
        outline_review(user, project)
    elif project.status == "ready":
        ready_view(user, project)
    else:
        st.error("La génération de ce projet a échoué. Créez une nouvelle présentation.")
    st.divider()
    with st.expander("Supprimer ce projet"):
        st.warning("Supprime le projet et ses fichiers (PPTX, PDF). Action définitive.")
        if st.button("Supprimer définitivement", key="delete_project"):
            store.delete_project(user, project)
            st.switch_page(common.PAGES["projets"])


# --- Étape 1 : relire et valider le plan ----------------------------------------------

def outline_review(user: store.User, project: store.Project) -> None:
    stem = Path(project.stem)
    try:
        draft = load_draft(stem)
    except FileNotFoundError:
        st.error("Le plan de ce projet est introuvable.")
        return
    st.subheader("Relisez votre plan")
    st.caption("Modifiez les titres et les idées principales, décochez les slides inutiles. "
               "Les visuels (graphique, diagramme) sont détectés dans le document.")
    new_title = st.text_input("Titre de la présentation", draft.outline.title)
    rows = [{"Section": sec.title, "Titre de la slide": s.title, "Idée principale": s.key_point,
             "Visuel": LAYOUTS.get(s.layout, s.layout), "Garder": True}
            for sec in draft.outline.sections for s in sec.slides]
    edited = st.data_editor(
        pd.DataFrame(rows), hide_index=True, width="stretch", num_rows="fixed",
        disabled=["Section", "Visuel"], key=f"outline_{project.id}",
        column_config={"Idée principale": st.column_config.TextColumn(width="large"),
                       "Garder": st.column_config.CheckboxColumn(width="small")})
    kept = int(edited["Garder"].sum())
    st.caption(f"{kept + 1} slides avec la slide de titre "
               f"(demandé : {project.slides}).")
    for w in draft.warnings:
        st.caption(f"⚠ {w}")

    c1, c2, c3 = st.columns([1.2, 1.2, 2])
    pdf = c1.toggle("Exporter aussi en PDF", value=user.prefs["pdf"])
    agent_ok = common.agent_available()
    with_agent = c2.toggle("🤖 Relecture par l'agent", value=user.prefs["agent"] and agent_ok,
                           disabled=not agent_ok)
    if not c3.button("Valider le plan et créer les slides", type="primary", width="stretch",
                     disabled=kept == 0):
        return

    # Plan modifié → Outline (les champs cachés : extraits, données des visuels, sont gardés).
    i, sections = 0, []
    for sec in draft.outline.sections:
        slides = []
        for s in sec.slides:
            row = edited.iloc[i]
            i += 1
            if row["Garder"]:
                title = str(row["Titre de la slide"]).strip() or s.title
                point = str(row["Idée principale"]).strip() or s.key_point
                slides.append(s.model_copy(update={"title": title, "key_point": point}))
        if slides:
            sections.append(Section(title=sec.title, slides=slides))
    draft.outline = draft.outline.model_copy(update={"title": new_title.strip() or
                                                     draft.outline.title, "sections": sections})
    save_draft(stem, draft)
    store.update_project(project, status="generating", title=draft.outline.title)
    steps = BUILD_STEPS + ([("Agent", "relecture")] if with_agent else [])
    progress = common.ProgressView("Rédaction des slides…", end=0.9 if with_agent else 1.0,
                                   first_step=3, steps=steps)
    try:
        run = build_from_draft(draft, pdf=pdf, progress=progress, theme=project.theme,
                               logo=_logo(user), stem=stem)
        if with_agent:
            progress._show(len(steps), "relit les slides")
            progress.bar.progress(0.92, text="Relecture par l'agent…")
            review(run, pdf=pdf, log=progress.status.write)
        progress.finish("Présentation prête")
        store.update_project(project, status="ready", slides=len(run.deck.slides),
                             theme=run.theme, title=run.deck.title)
        common.flash(f"Présentation prête : {len(run.deck.slides)} slides", "🎉", celebrate=True)
        st.rerun()
    except (ValueError, LLMError) as e:
        progress.fail("Rédaction impossible")
        store.update_project(project, status="outline")
        st.error(f"Rédaction impossible : {e}")


def _logo(user: store.User) -> Path | None:
    logo = user.prefs.get("logo")
    return Path(logo) if logo and Path(logo).exists() else None


# --- Étape 2 : présentation prête -------------------------------------------------------

def ready_view(user: store.User, project: store.Project) -> None:
    try:
        run = load_run(Path(f"{project.stem}.deck.json"))
    except (FileNotFoundError, ValueError) as e:
        st.error(f"Présentation introuvable : {e}")
        return
    report = run.report
    pdf_file = report.get("fichiers", {}).get("pdf")
    has_pdf = bool(pdf_file and Path(pdf_file).exists())
    a, b, c, d = st.columns(4)
    with a:
        style.stat(len(run.deck.slides), "Slides")
    with b:
        style.stat(f"{report.get('durees', {}).get('total_s', 0):.0f} s", "Durée")
    with c:
        style.stat(len(report.get("a_verifier", [])), "Chiffres à vérifier")
    with d:
        style.stat(all_themes().get(run.theme).label if run.theme in all_themes()
                   else run.theme, "Thème")
    st.write("")
    tabs = st.tabs(["🖼️ Slides", "📤 Exporter", "🎨 Thème", "🤖 Agent", "🔎 À vérifier"])
    with tabs[0]:
        slides_tab(user, project, run, has_pdf, pdf_file)
    with tabs[1]:
        export_tab(run, has_pdf, pdf_file)
    with tabs[2]:
        theme_tab(project, run, has_pdf)
    with tabs[3]:
        agent_tab(project, run, has_pdf)
    with tabs[4]:
        review_tab(report)


def _after_change(project: store.Project, run: Run, message: str, icon: str) -> None:
    store.update_project(project, slides=len(run.deck.slides), theme=run.theme,
                         title=run.deck.title)
    common.flash(message, icon)
    st.rerun()


def slides_tab(user, project, run: Run, has_pdf: bool, pdf_file) -> None:
    pages = common.pdf_pages(pdf_file, Path(pdf_file).stat().st_mtime, dpi=96) if has_pdf else []
    thumbs = common.pdf_pages(pdf_file, Path(pdf_file).stat().st_mtime, dpi=30) if has_pdf else []
    if pages:  # visionneuse : flèches, miniatures, notes, diaporama, plein écran
        slide_viewer(pages, [s.title for s in run.deck.slides],
                     [s.notes for s in run.deck.slides],
                     start=st.session_state.get("viewer_start", 0))
    else:
        st.info("Aperçu indisponible sans PDF : créez-le dans l'onglet « Exporter ».")
    st.markdown("#### Modifier les slides")
    problem = common.ollama_problem()
    for i, slide in enumerate(run.deck.slides):
        with st.container(border=True, key=f"sd-hover-slide-{i}"):
            c0, c1, c2, c3 = st.columns([1.1, 4, 1.3, 1.3], vertical_alignment="center")
            if i < len(thumbs):
                c0.image(thumbs[i], width="stretch")
            c1.markdown(f"**{i + 1}. {style.esc(slide.title)}**<br>"
                        f"<span style='color:#64748B;font-size:.85rem'>"
                        f"{LAYOUTS.get(slide.layout, slide.layout)} · {len(slide.bullets)} puce(s)"
                        "</span>", unsafe_allow_html=True)
            if i == 0:
                c2.caption("Slide de titre")
                continue
            if c2.button("🔄 Régénérer", key=f"regen_{i}", width="stretch",
                         disabled=problem is not None,
                         help="Réécrit cette slide avec le modèle, sans toucher aux autres."):
                with st.spinner(f"Régénération de la slide {i + 1}…"):
                    try:
                        regenerate_slide(run, i, pdf=has_pdf)
                    except (ValueError, LLMError) as e:
                        st.error(f"Régénération impossible : {e}")
                        return
                st.session_state.viewer_start = i
                _after_change(project, run, f"Slide {i + 1} régénérée", "🔄")
            with c3.popover("✏️ Modifier", width="stretch"):
                edit_slide_form(project, run, i, has_pdf)


def edit_slide_form(project, run: Run, i: int, has_pdf: bool) -> None:
    slide = run.deck.slides[i]
    with st.form(f"edit_{i}"):
        title = st.text_input("Titre de la slide", slide.title)
        bullets = st.text_area("Puces (une par ligne)", "\n".join(slide.bullets), height=150)
        notes = st.text_area("Notes orateur", slide.notes, height=120)
        if not st.form_submit_button("Enregistrer", type="primary"):
            return
    try:
        new = Slide.model_validate(slide.model_dump() | {
            "title": title.strip(), "notes": notes.strip(),
            "bullets": [b.strip() for b in bullets.splitlines() if b.strip()]})
    except ValidationError as e:
        st.error("Slide refusée : " + "; ".join(err["msg"] for err in e.errors()))
        return
    replace_slide(run, i, new, [], by="édition manuelle")
    st.session_state.viewer_start = i
    with st.spinner("Reconstruction…"):
        rebuild(run, pdf=has_pdf)
    _after_change(project, run, f"Slide {i + 1} enregistrée", "✏️")


def export_tab(run: Run, has_pdf: bool, pdf_file) -> None:
    st.markdown("Choisissez un format. Les fichiers restent sur ce PC.")
    pptx = run.path("pptx")
    title = run.deck.title
    c1, c2, c3 = st.columns(3)
    with c1, st.container(border=True):
        st.markdown("**PowerPoint (.pptx)**  \nÉditable, avec notes orateur.")
        st.download_button("Télécharger le PPTX", pptx.read_bytes(),
                           file_name=f"{common_name(title)}.pptx", type="primary",
                           mime="application/vnd.openxmlformats-officedocument."
                                "presentationml.presentation", width="stretch")
    with c2, st.container(border=True):
        st.markdown("**PDF (.pdf)**  \nPour partager ou imprimer.")
        if has_pdf:
            st.download_button("Télécharger le PDF", Path(pdf_file).read_bytes(),
                               file_name=f"{common_name(title)}.pdf", mime="application/pdf",
                               width="stretch")
        elif st.button("Créer le PDF", width="stretch"):
            with st.spinner("Export PDF…"):
                rebuild(run, pdf=True)
            st.rerun()
    with c3, st.container(border=True):
        st.markdown("**Rapport (.json)**  \nAvertissements, chiffres à vérifier, durées.")
        st.download_button("Télécharger le rapport",
                           json.dumps(run.report, ensure_ascii=False, indent=2),
                           file_name=f"{common_name(title)}.report.json",
                           mime="application/json", width="stretch")


def common_name(title: str) -> str:
    from generate import safe_stem
    return safe_stem(title)


def theme_tab(project, run: Run, has_pdf: bool) -> None:
    themes = all_themes()
    names = list(themes)
    st.caption("Change l'apparence sans rien réécrire : PPTX et PDF sont reconstruits en "
               "quelques secondes.")
    if "pending_theme_choice" in st.session_state:
        st.session_state.theme_choice = st.session_state.pop("pending_theme_choice")
    if st.session_state.get("theme_choice") not in names:
        st.session_state.theme_choice = run.theme if run.theme in names else names[0]
    c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="bottom")
    choice = c1.selectbox("Thème", names, key="theme_choice",
                          format_func=lambda n: themes[n].label)
    if c2.button("Appliquer", type="primary", width="stretch", disabled=choice == run.theme):
        with st.spinner("Reconstruction…"):
            rebuild(run, pdf=has_pdf, theme=choice)
        _after_change(project, run, f"Thème « {themes[choice].label} » appliqué", "🎨")
    if c3.button("🤖 Proposer", width="stretch", disabled=not common.agent_available()):
        with st.spinner("L'agent lit le document…"):
            name, reason = suggest_theme(run.document, run.deck.title)
        st.session_state.pending_theme_choice = name
        st.session_state.theme_reason = reason
        st.rerun()
    if st.session_state.get("theme_reason"):
        st.info(f"Proposition de l'agent : {st.session_state.theme_reason}")
    preview = common.theme_preview(choice)
    if preview:
        st.image(str(preview), width="stretch")


def agent_tab(project, run: Run, has_pdf: bool) -> None:
    agent_report = run.report.get("agent")
    if agent_report:
        st.markdown(f"**{agent_report['resume']}** — défauts mesurés "
                    f"{agent_report['defauts_avant']} → {agent_report['defauts_apres']}, "
                    f"{agent_report['secondes']:.0f} s")
        for a in agent_report["actions"]:
            if a["outil"] == "reecrire_slide":
                verdict = "gardée" if a["gardee"] else "rejetée (pas meilleure)"
                st.markdown(f"- Slide {a['slide']} réécrite — {a['consigne']} → {verdict}")
            elif a["outil"] == "passer":
                st.markdown(f"- Slide {a['slide']} laissée telle quelle — {a['raison']}")
    else:
        st.caption("L'agent relit les slides, réécrit celles qui ont des défauts mesurés et ne "
                   "garde une version que si elle est meilleure.")
    goal = st.text_input("Consigne (facultatif)",
                         placeholder="ex. « raccourcis les puces de la slide 3 »")
    if st.button("Lancer l'agent", type="primary", disabled=not common.agent_available()):
        with st.status("Relecture par l'agent…", expanded=True) as status:
            try:
                review(run, goal=goal, pdf=has_pdf, log=status.write)
            except (ValueError, LLMError) as e:
                st.error(f"Agent impossible : {e}")
                return
        _after_change(project, run, "Relecture de l’agent terminée", "🤖")


def review_tab(report: dict) -> None:
    items = report.get("a_verifier", []) + [
        f"Extrait à relire : {b}" for b in report.get("ingestion", {}).get("blocs_a_verifier", [])]
    if not items and not report.get("avertissements"):
        st.success("Rien à signaler.")
    for item in items:
        st.markdown(f"- 🔎 {item}")
    for item in report.get("ingestion", {}).get("remarques", []) + report.get("avertissements", []):
        st.markdown(f"- ℹ️ {item}")
