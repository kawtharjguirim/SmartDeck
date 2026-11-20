"""Modèles (thèmes et modèles d'entreprise) et paramètres du compte."""
from pathlib import Path

import streamlit as st

import config
from build.template_import import IMPORT_DIR, TemplateError, delete_template, import_template
from build.theme_previews import ensure_previews
from build.themes import THEMES, all_themes
from ui import common, store, style


@st.cache_resource(show_spinner="Préparation des aperçus de thèmes…")
def _previews() -> dict:
    return ensure_previews()


def templates_page() -> None:
    style.page_header("Modèles", "Thèmes intégrés et modèles PowerPoint de votre entreprise.")
    previews = _previews()
    st.subheader("Thèmes intégrés")
    cols = st.columns(2)
    for i, (name, theme) in enumerate(THEMES.items()):
        with cols[i % 2], st.container(border=True):
            st.markdown(f"**{style.esc(theme.label)}**  \n"
                        f"<span style='color:#64748B'>{style.esc(theme.description)}</span>",
                        unsafe_allow_html=True)
            if previews.get(name):
                st.image(str(previews[name]), width="stretch")

    st.subheader("Modèles d'entreprise")
    imported = {n: t for n, t in all_themes().items() if n not in THEMES}
    if not imported:
        st.caption("Aucun modèle importé.")
    cols = st.columns(2)
    for i, (name, theme) in enumerate(imported.items()):
        with cols[i % 2], st.container(border=True):
            st.markdown(f"**{style.esc(theme.label)}**")
            preview = IMPORT_DIR / f"{name}.png"
            if preview.exists():
                st.image(str(preview), width="stretch")
            if st.button("Supprimer", key=f"del_{name}"):
                delete_template(name)
                st.rerun()

    with st.container(border=True):
        st.markdown("**Importer un modèle (.pptx ou .potx)**  \nSmartDeck garde son fond, son "
                    "décor et ses styles de texte, et vérifie qu'il est exploitable.")
        uploaded = st.file_uploader("Modèle PowerPoint", type=["pptx", "potx"],
                                    label_visibility="collapsed")
        if uploaded is not None and st.button("Importer ce modèle", type="primary"):
            path = common.save_upload(uploaded, common.current_user())
            with st.spinner("Analyse du modèle et aperçu…"):
                try:
                    theme, notes, _ = import_template(path)
                except TemplateError as e:
                    st.error(f"Modèle refusé : {e}")
                    return
            st.success(f"{theme.label} importé.")
            for n in notes:
                st.caption(f"⚠ {n}")


def settings_page() -> None:
    user = common.current_user()
    style.page_header("Paramètres", "Votre profil, vos réglages par défaut et votre compte.")
    tab_profile, tab_security = st.tabs(["Profil et réglages", "Sécurité"])
    with tab_profile, st.form("profile"):
        name = st.text_input("Nom affiché", user.name)
        st.text_input("E-mail", user.email, disabled=True)
        c1, c2 = st.columns(2)
        languages = list(common.LANGUAGES)
        current_lang = next((k for k, v in common.LANGUAGES.items()
                             if v == user.prefs["language"]), languages[0])
        language = c1.selectbox("Langue par défaut", languages,
                                index=languages.index(current_lang))
        slides = c2.slider("Slides par présentation", config.MIN_SLIDES, config.MAX_SLIDES,
                           int(user.prefs["slides"]))
        themes = all_themes()
        names = list(themes)
        theme = c1.selectbox("Thème par défaut", names,
                             index=names.index(user.prefs["theme"])
                             if user.prefs["theme"] in names else 0,
                             format_func=lambda n: themes[n].label)
        pdf = c2.toggle("Exporter aussi en PDF", value=user.prefs["pdf"])
        agent = c2.toggle("Relecture par l'agent", value=user.prefs["agent"])
        logo = st.file_uploader("Logo (affiché sur chaque slide)", type=["png", "jpg", "jpeg"])
        remove_logo = st.checkbox("Retirer le logo actuel", disabled=not user.prefs.get("logo"))
        if st.form_submit_button("Enregistrer le profil", type="primary"):
            prefs = {"language": common.LANGUAGES[language], "slides": slides, "theme": theme,
                     "pdf": pdf, "agent": agent}
            if logo is not None:
                prefs["logo"] = str(common.save_upload(logo, user, "logo"))
            elif remove_logo:
                prefs["logo"] = None
            try:
                store.update_profile(user, name, prefs)
                st.success("Profil enregistré.")
            except store.AuthError as e:
                st.error(str(e))
    with tab_security:
        with st.form("password"):
            current = st.text_input("Mot de passe actuel", type="password",
                                    autocomplete="current-password")
            new = st.text_input("Nouveau mot de passe", type="password",
                                autocomplete="new-password")
            confirm = st.text_input("Confirmer", type="password", autocomplete="new-password")
            if st.form_submit_button("Changer le mot de passe"):
                if new != confirm:
                    st.error("Les deux mots de passe ne sont pas identiques.")
                else:
                    try:
                        store.change_password(user, current, new)
                        st.success("Mot de passe changé.")
                    except store.AuthError as e:
                        st.error(str(e))
        st.divider()
        st.markdown("**Session**  \nSe déconnecter de SmartDeck sur cet appareil.")
        if st.button("Se déconnecter"):
            common.logout()
            st.rerun()
