"""Bonus : l'agent (Qwen3-VL) propose un thème adapté au document.

Il reçoit le titre de la présentation, le début du document et la liste des thèmes
disponibles (intégrés et modèles d'entreprise importés), avec leur description. Il
répond en JSON validé : un nom de thème pris dans la liste et une raison courte.
L'utilisateur garde la main : la proposition s'applique ou se change en un clic.
"""
from typing import Literal

from pydantic import Field, create_model

import config
from build.themes import DEFAULT_THEME, all_themes
from llm.client import LLMError, generate_structured, unload
from schemas import Document

AUTO = "auto"  # valeur spéciale : le thème est choisi par l'agent après la rédaction

SYSTEM = ("Tu choisis le thème visuel d'une présentation d'après son sujet et son public. "
          "Tu réponds uniquement en JSON, avec un thème de la liste.")


def suggest_theme(document: Document, deck_title: str, model: str | None = None
                  ) -> tuple[str, str]:
    """(nom du thème, raison). En cas d'échec du modèle : (Classique, explication)."""
    themes = all_themes()
    names = tuple(themes)
    choice = create_model("ThemeChoice",
                          theme=(Literal[names], Field(description="nom du thème choisi")),
                          raison=(str, Field(description="une phrase : pourquoi ce thème")))
    listing = "\n".join(f"- {n} : {t.label}. {t.description}" for n, t in themes.items())
    has_company = any(n.startswith("modele_") for n in names)
    prompt = f"""Présentation : « {deck_title} » (langue : {document.language}).

Début du document :
\"\"\"
{document.full_text()[:1500]}
\"\"\"

Thèmes disponibles :
{listing}

Règles :
- Rapport financier, administration, juridique → sobre (institutionnel, minimal, classique).
- Association, école, environnement, agriculture → nature.
- Conférence, technologie, projection en salle → sombre.
{"- Un modèle d'entreprise (modele_…) n'est choisi que si le document parle de cette entreprise." if has_company else ""}
Réponds avec le nom exact d'un thème et une phrase de raison, en français."""
    model = model or config.AGENT_MODEL
    try:
        answer = generate_structured(prompt, choice, system=SYSTEM, model=model, max_tokens=200)
    except LLMError as e:
        return DEFAULT_THEME, f"proposition impossible ({e}) : thème Classique"
    finally:
        if model not in (config.PLAN_MODEL, config.WRITE_MODEL):
            unload(model)  # libère la VRAM pour la suite
    return answer.theme, answer.raison.strip()
