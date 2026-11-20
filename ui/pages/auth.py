"""Pages publiques : accueil, connexion, inscription, mot de passe oublié."""
import streamlit as st

from ui import common, store, style


def _go(name: str) -> None:
    st.switch_page(common.PAGES[name])


def welcome() -> None:
    st.html(style.hero_html())
    _, c1, c2, _ = st.columns([2, 1.1, 1.3, 2])
    if c1.button("Commencer", type="primary", width="stretch"):
        _go("inscription")
    if c2.button("J'ai déjà un compte", width="stretch"):
        _go("connexion")
    st.write("")
    a, b, c = st.columns(3)
    with a:
        style.card("📄", "Texte, PDF ou image", "Collez un texte, déposez un PDF ou photographiez "
                   "un tableau : SmartDeck lit tout, même les scans.")
    with b:
        style.card("🧭", "Le plan d'abord", "Relisez et modifiez le plan proposé avant qu'une "
                   "seule slide ne soit rédigée.")
    with c:
        style.card("📤", "Export PPTX ou PDF", "Mise en page, notes orateur et visuels : "
                   "un fichier prêt à présenter, éditable dans PowerPoint.")
    st.write("")
    st.markdown("<h3 style='text-align:center;margin:1.2rem 0 .8rem'>Comment ça marche</h3>",
                unsafe_allow_html=True)
    steps = [("1", "Déposez", "un PDF, une image ou un texte"),
             ("2", "Validez le plan", "titres et idées, avant la rédaction"),
             ("3", "Personnalisez", "thème, logo, modèle d'entreprise"),
             ("4", "Exportez", "PowerPoint ou PDF, en un clic")]
    for col, (n, title, text) in zip(st.columns(4), steps):
        with col:
            style.card(n, title, text)


def _centered():
    """Colonne centrale étroite pour les formulaires de compte."""
    return st.columns([1, 1.4, 1])[1]


def login() -> None:
    with _centered():
        style.page_header("Connexion", "Bon retour. Reprenez là où vous en étiez.")
        with st.form("login"):
            email = st.text_input("E-mail", autocomplete="email")
            password = st.text_input("Mot de passe", type="password",
                                     autocomplete="current-password")
            submitted = st.form_submit_button("Se connecter", type="primary", width="stretch")
        if submitted:
            try:
                common.login(store.authenticate(email, password))
                st.rerun()  # la navigation des pages connectées est construite au rechargement
            except store.AuthError as e:
                st.error(str(e))
        c1, c2 = st.columns(2)
        if c1.button("Mot de passe oublié ?", type="tertiary"):
            _go("oubli")
        if c2.button("Créer un compte", type="tertiary"):
            _go("inscription")


def signup() -> None:
    with _centered():
        if "new_recovery_code" in st.session_state:  # compte créé : code de secours à noter
            style.page_header("Notez votre code de secours",
                              "Il remplace l'e-mail de réinitialisation : SmartDeck n'envoie rien "
                              "sur Internet. Il ne sera plus affiché.")
            st.code(st.session_state.new_recovery_code, language=None)
            st.warning("Sans ce code, un mot de passe oublié ne pourra pas être réinitialisé.")
            if st.button("J'ai noté mon code, continuer", type="primary"):
                user_id = st.session_state.pop("new_recovery_code_user")
                del st.session_state.new_recovery_code
                common.login(store.get_user(user_id))
                st.rerun()  # la navigation des pages connectées est construite au rechargement
            return
        style.page_header("Créer votre compte", "Commencez avec un document : votre première "
                          "présentation est à quelques minutes.")
        with st.form("signup"):
            name = st.text_input("Nom complet", autocomplete="name")
            email = st.text_input("E-mail", autocomplete="email")
            password = st.text_input("Mot de passe", type="password", autocomplete="new-password",
                                     help=f"Au moins {store.MIN_PASSWORD} caractères, lettres et "
                                          "chiffres mélangés.")
            confirm = st.text_input("Confirmer le mot de passe", type="password",
                                    autocomplete="new-password")
            submitted = st.form_submit_button("Créer le compte", type="primary", width="stretch")
        if submitted:
            if password != confirm:
                st.error("Les deux mots de passe ne sont pas identiques.")
            else:
                try:
                    user, code = store.create_user(email, name, password)
                    st.session_state.new_recovery_code = code
                    st.session_state.new_recovery_code_user = user.id
                    st.rerun()
                except store.AuthError as e:
                    st.error(str(e))
        if st.button("J'ai déjà un compte", type="tertiary"):
            _go("connexion")


def forgot() -> None:
    with _centered():
        if "reset_code" in st.session_state:
            style.page_header("Mot de passe changé", "Voici votre nouveau code de secours : "
                              "l'ancien ne fonctionne plus.")
            st.code(st.session_state.reset_code, language=None)
            if st.button("Retour à la connexion", type="primary"):
                del st.session_state.reset_code
                _go("connexion")
            return
        style.page_header("Réinitialiser le mot de passe",
                          "Indiquez votre e-mail et le code de secours reçu à l'inscription.")
        with st.form("forgot"):
            email = st.text_input("E-mail", autocomplete="email")
            code = st.text_input("Code de secours", placeholder="XXXX-XXXX-XXXX")
            password = st.text_input("Nouveau mot de passe", type="password",
                                     autocomplete="new-password")
            confirm = st.text_input("Confirmer", type="password", autocomplete="new-password")
            submitted = st.form_submit_button("Changer le mot de passe", type="primary",
                                              width="stretch")
        if submitted:
            if password != confirm:
                st.error("Les deux mots de passe ne sont pas identiques.")
            else:
                try:
                    st.session_state.reset_code = store.reset_password(email, code, password)
                    st.rerun()
                except store.AuthError as e:
                    st.error(str(e))
        if st.button("Retour à la connexion", type="tertiary"):
            _go("connexion")
