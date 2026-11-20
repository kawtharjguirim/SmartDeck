"""Interface SmartDeck (Streamlit), au style de la maquette SmartDeck-app.html.

Lancer :  .venv\\Scripts\\streamlit run app.py   puis ouvrir http://localhost:8501

Parcours : compte local → nouvelle présentation (source, réglages) → plan à relire et
valider → slides (aperçu, édition, régénération, thème, agent) → export PPTX / PDF.
Tout tourne sur ce PC (NFR-01) : comptes et projets dans data/smartdeck.db.
L'ancienne interface sur une seule page reste disponible : app_simple.py.
"""
import streamlit as st

from ui import common, style
from ui.pages import auth, dashboard, new, project, settings

st.set_page_config(page_title="SmartDeck", page_icon="📊", layout="wide")
style.apply()

user = common.current_user()
if user is None:  # pages publiques uniquement
    pages = {
        "accueil": st.Page(auth.welcome, title="Accueil", icon="🏠", default=True),
        "connexion": st.Page(auth.login, title="Connexion", url_path="connexion"),
        "inscription": st.Page(auth.signup, title="Inscription", url_path="inscription"),
        "oubli": st.Page(auth.forgot, title="Mot de passe oublié", url_path="mot-de-passe"),
    }
    common.PAGES.update(pages)
    style.brand()
    with st.sidebar:
        st.page_link(pages["accueil"], label="Accueil", icon="🏠")
        st.page_link(pages["connexion"], label="Connexion", icon="🔑")
        st.page_link(pages["inscription"], label="Créer un compte", icon="✨")
else:
    pages = {
        "tableau": st.Page(dashboard.dashboard, title="Tableau de bord", default=True),
        "nouveau": st.Page(new.new_page, title="Nouvelle présentation", url_path="nouveau"),
        "projets": st.Page(dashboard.projects_page, title="Projets", url_path="projets"),
        "projet": st.Page(project.project_page, title="Projet", url_path="projet"),
        "modeles": st.Page(settings.templates_page, title="Modèles", url_path="modeles"),
        "parametres": st.Page(settings.settings_page, title="Paramètres", url_path="parametres"),
    }
    common.PAGES.update(pages)
    style.brand(user.name)
    with st.sidebar:
        st.page_link(pages["tableau"], label="Tableau de bord", icon="📊")
        st.page_link(pages["nouveau"], label="Nouvelle présentation", icon="➕")
        st.page_link(pages["projets"], label="Projets", icon="🗂️")
        st.page_link(pages["modeles"], label="Modèles", icon="🎨")
        st.page_link(pages["parametres"], label="Paramètres", icon="⚙️")
        st.divider()
        problem = common.ollama_problem()
        st.caption(f"⚠️ {problem}" if problem else "🟢 Ollama prêt")
        st.caption("Tout reste sur ce PC : aucun document n'est envoyé sur Internet.")
        if st.button("Se déconnecter", type="tertiary"):
            common.logout()
            st.rerun()

common.show_flash()
page = st.navigation(list(pages.values()), position="hidden")
style.active_link("" if page.url_path == list(pages.values())[0].url_path else page.url_path)
page.run()
