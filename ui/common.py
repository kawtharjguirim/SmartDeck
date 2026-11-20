"""Outils partagés par les pages : session, aperçu, état d'Ollama, progression."""
import re
from pathlib import Path

import pymupdf
import streamlit as st

import config
from llm.client import LLMError, missing_models
from ui import store

UPLOAD_DIR = config.ROOT_DIR / ".cache" / "uploads"
LANGUAGES = {"Auto (langue du document)": None, "Français": "fr", "English": "en",
             "العربية": "ar"}
FILE_TYPES = ["txt", "md", "pdf", "png", "jpg", "jpeg", "webp"]


# --- Session ------------------------------------------------------------------------

def current_user() -> store.User | None:
    user_id = st.session_state.get("user_id")
    return store.get_user(user_id) if user_id else None


def login(user: store.User) -> None:
    st.session_state.clear()  # aucune donnée d'une session précédente ne reste
    st.session_state.user_id = user.id


def logout() -> None:
    st.session_state.clear()


def open_project(project_id: int) -> None:
    st.session_state.project_id = project_id
    st.switch_page(PAGES["projet"])


PAGES: dict[str, st.Page] = {}  # rempli par app.py (navigation)


def flash(message: str, icon: str = "✅", celebrate: bool = False) -> None:
    """Notification affichée au prochain affichage (survit à st.rerun et st.switch_page)."""
    st.session_state.setdefault("flash", []).append((message, icon, celebrate))


def show_flash() -> None:
    for message, icon, celebrate in st.session_state.pop("flash", []):
        st.toast(message, icon=icon)
        if celebrate:
            st.balloons()


# --- Moteur ---------------------------------------------------------------------------

def ollama_problem() -> str | None:
    """Message d'erreur si Ollama ou un modèle manque, sinon None."""
    try:
        missing = missing_models([config.PLAN_MODEL, config.WRITE_MODEL])
    except LLMError as e:
        return str(e)
    return "Modèles absents d'Ollama : " + ", ".join(missing) if missing else None


def agent_available() -> bool:
    try:
        return not missing_models([config.AGENT_MODEL])
    except LLMError:
        return False


@st.cache_data(show_spinner=False)
def pdf_pages(pdf_path: str, mtime: float, dpi: int = 72) -> list[bytes]:
    """Chaque page du PDF en PNG (mtime invalide le cache après une reconstruction)."""
    with pymupdf.open(pdf_path) as doc:
        return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]


def theme_preview(name: str) -> Path | None:
    """Vignette d'un thème intégré ou d'un modèle importé (si elle existe)."""
    from build.template_import import IMPORT_DIR
    from build.theme_previews import preview_path
    for path in (preview_path(name), IMPORT_DIR / f"{name}.png"):
        if path.exists():
            return path
    return None


def save_upload(uploaded, user: store.User, name: str | None = None) -> Path:
    """Fichier déposé → dossier privé de l'utilisateur (nom de fichier assaini)."""
    from generate import safe_stem
    folder = UPLOAD_DIR / str(user.id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ((name or safe_stem(uploaded.name)) + Path(uploaded.name).suffix.lower())
    path.write_bytes(uploaded.getvalue())
    return path


class ProgressView:
    """Relie la progression du pipeline (étape, total, message) à l'interface :
    étapes animées (style.steps_html), barre de progression et journal détaillé."""

    def __init__(self, label: str, start: float = 0.0, end: float = 1.0, first_step: int = 1,
                 steps=None):
        from ui import style
        self.style, self.start, self.end = style, start, end
        self.step_list = steps or style.STEPS
        self.steps = st.empty()
        self._show(first_step)
        self.bar = st.progress(start)
        self.status = st.status(label, expanded=False)  # journal détaillé, replié

    def __call__(self, step: int, total: int, message: str) -> None:
        m = re.search(r"Rédaction (\d+)/(\d+)", message)
        if m:  # la rédaction est l'étape la plus longue : progression slide par slide
            fraction = 0.25 + 0.6 * (int(m.group(1)) - 1) / int(m.group(2))
            self._show(3, f"slide {m.group(1)} sur {m.group(2)}")
        else:
            fraction = {1: 0.05, 2: 0.15, 3: 0.85, 4: 0.9, 5: 0.95}.get(step)
            if step:
                self._show(step)
        if fraction is not None:
            self.bar.progress(self.start + (self.end - self.start) * fraction, text=message)
        self.status.update(label=message)
        self.status.write(message)

    def _show(self, step: int, detail: str = "") -> None:
        self.steps.html(self.style.steps_html(step, detail, self.step_list))

    def finish(self, message: str = "Terminé", step: int | None = None) -> None:
        self._show(step or len(self.step_list) + 1)
        self.bar.progress(1.0, text=message)
        self.status.update(label=message, state="complete")

    def fail(self, message: str) -> None:
        self.status.update(label=message, state="error")
