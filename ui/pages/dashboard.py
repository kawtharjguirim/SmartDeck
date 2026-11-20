"""Tableau de bord et liste des projets (cartes animées, miniatures, recherche)."""
from datetime import datetime
from pathlib import Path

import streamlit as st

from ui import common, store, style


def _when(ts: float) -> str:
    delta = datetime.now() - datetime.fromtimestamp(ts)
    if delta.days == 0 and delta.seconds < 3600:
        return f"il y a {max(1, delta.seconds // 60)} min"
    if delta.days == 0:
        return f"il y a {delta.seconds // 3600} h"
    if delta.days == 1:
        return "hier"
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y")


def _thumbnail(project: store.Project) -> bytes | None:
    pdf = Path(f"{project.stem}.pdf")
    if project.status != "ready" or not pdf.exists():
        return None
    try:
        return common.pdf_pages(str(pdf), pdf.stat().st_mtime, dpi=36)[0]
    except Exception:  # PDF illisible : la carte s'affiche sans miniature
        return None


def project_card(project: store.Project, key: str) -> None:
    """Carte de projet : miniature de la 1re slide, titre, état, date ; clic → ouvrir."""
    with st.container(border=True, key=f"sd-hover-{key}-{project.id}"):
        thumb = _thumbnail(project)
        with st.container(key=f"sd-thumb-{key}-{project.id}"):
            if thumb:
                st.image(thumb, width="stretch")
            else:
                st.markdown(
                    "<div style='aspect-ratio:16/9;border-radius:.7rem;display:flex;"
                    "align-items:center;justify-content:center;font-size:2rem;"
                    "background:linear-gradient(135deg,#EDE9FE,#FAE8FF)'>"
                    f"{'🧭' if project.status == 'outline' else '✦'}</div>",
                    unsafe_allow_html=True)
        st.markdown(f"**{style.esc(project.title)}**", unsafe_allow_html=True)
        meta = f"{project.slides} slides · " if project.status == "ready" else ""
        st.markdown(f"{style.badge(project.status)} "
                    f"<span style='color:#64748B;font-size:.82rem'>{meta}"
                    f"{_when(project.updated)}</span>", unsafe_allow_html=True)
        label = "Relire le plan" if project.status == "outline" else "Ouvrir"
        if st.button(label, key=f"open_{key}_{project.id}", width="stretch",
                     type="primary" if project.status == "outline" else "secondary"):
            common.open_project(project.id)


def project_grid(projects: list[store.Project], key: str, columns: int = 3) -> None:
    for start in range(0, len(projects), columns):
        cols = st.columns(columns)
        for col, project in zip(cols, projects[start:start + columns]):
            with col:
                project_card(project, key)


def dashboard() -> None:
    user = common.current_user()
    projects = store.list_projects(user)
    hour = datetime.now().hour
    hello = "Bonjour" if 5 <= hour < 18 else "Bonsoir"
    pending = sum(p.status == "outline" for p in projects)
    style.banner(f"{hello} {user.name.split()[0]} 👋",
                 f"{pending} plan(s) attendent votre validation." if pending
                 else "Prêt à transformer un nouveau document en présentation ?")
    ready = [p for p in projects if p.status == "ready"]
    a, b, c = st.columns(3)
    with a:
        style.stat(len(projects), "Présentations", "🗂️")
    with b:
        style.stat(sum(p.slides for p in ready), "Slides créées", "🖼️")
    with c:
        style.stat(sum(1 for p in ready if Path(f"{p.stem}.pptx").exists()), "Exports prêts", "📤")

    st.markdown("#### Démarrer")
    actions = [("📄", "Depuis un PDF", "Rapport, cahier des charges, PDF scanné"),
               ("✏️", "Depuis un texte", "Collez des notes ou un article"),
               ("🖼️", "Depuis une image", "Photo d'un tableau, d'un graphique, d'un schéma")]
    for i, (col, (icon, title, text)) in enumerate(zip(st.columns(3), actions)):
        with col, st.container(border=True, key=f"sd-hover-start-{i}"):
            st.markdown(f'<span class="sd-icon">{icon}</span>', unsafe_allow_html=True)
            st.markdown(f"**{title}**  \n<span style='color:#64748B;font-size:.88rem'>{text}</span>",
                        unsafe_allow_html=True)
            if st.button("Commencer", key=f"start_{i}", width="stretch"):
                st.switch_page(common.PAGES["nouveau"])

    head, action = st.columns([3, 1], vertical_alignment="bottom")
    head.markdown("#### Récents")
    if projects and action.button("Voir tous les projets →", type="tertiary", width="stretch"):
        st.switch_page(common.PAGES["projets"])
    if not projects:
        style.card("✨", "Aucune présentation pour l'instant",
                   "Partez d'un paragraphe de texte, d'un PDF ou d'une photo de vos notes.")
        return
    project_grid(projects[:3], "recent")


def projects_page() -> None:
    user = common.current_user()
    style.page_header("Projets", "Toutes les présentations que vous avez générées, au même endroit.")
    c1, c2 = st.columns([3, 1.3])
    search = c1.text_input("Rechercher", placeholder="🔎 Rechercher par titre",
                           label_visibility="collapsed")
    status = c2.segmented_control("État", ["Toutes", "Prêtes", "Plans à valider"],
                                  default="Toutes", label_visibility="collapsed")
    projects = store.list_projects(user, search)
    if status == "Prêtes":
        projects = [p for p in projects if p.status == "ready"]
    elif status == "Plans à valider":
        projects = [p for p in projects if p.status == "outline"]
    if not projects:
        style.card("🔎", "Aucun projet", "Aucun titre ne correspond." if search or status != "Toutes"
                   else "Créez votre première présentation depuis « Nouvelle présentation ».")
        return
    st.caption(f"{len(projects)} projet(s)")
    project_grid(projects, "list")
