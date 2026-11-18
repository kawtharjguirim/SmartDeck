"""Étape 4 : vérifie que le LLM local produit un Deck JSON valide.

Usage : python test_llm.py   → affiche OK si tout fonctionne.
"""
import time

import config
from llm.client import LLMError, generate_structured
from schemas import Deck

SOURCE = """
L'entreprise Verdi a réalisé un chiffre d'affaires de 4,2 millions d'euros en 2025,
en hausse de 12 % par rapport à 2024. Les ventes en ligne représentent désormais
38 % du total. L'entreprise compte 45 salariés et prévoit d'ouvrir une agence à Lyon
en 2026. Le principal défi reste le recrutement de profils techniques.
"""

SYSTEM = (
    "Tu es un assistant qui crée des présentations. Tu réponds uniquement en JSON "
    "conforme au schéma fourni. N'invente aucun chiffre : utilise seulement ceux du texte."
)

PROMPT = f"""Crée une présentation en français de 3 slides à partir de ce texte.
Chaque slide (sauf la première, de type "title") contient 3 puces courtes et des notes orateur.
Tous les champs sont du texte simple, jamais un objet JSON imbriqué.

Exemple de format attendu (contenu à remplacer) :
{{"title": "Titre de la présentation", "language": "fr", "slides": [
  {{"layout": "title", "title": "Titre de la présentation", "bullets": [], "notes": "Accueillir le public."}},
  {{"layout": "bullets", "title": "Titre de la slide", "bullets": ["Première idée", "Deuxième idée", "Troisième idée"], "notes": "Ce que l'orateur dit."}}
]}}

Texte :
{SOURCE}"""


def main() -> None:
    print(f"Modèle : {config.TEXT_MODEL} — génération en cours…")
    start = time.perf_counter()
    try:
        deck = generate_structured(PROMPT, Deck, system=SYSTEM)
    except LLMError as e:
        raise SystemExit(f"ÉCHEC : {e}")
    elapsed = time.perf_counter() - start

    print(f"\nTitre : {deck.title}")
    for i, slide in enumerate(deck.slides, 1):
        print(f"  {i}. [{slide.layout}] {slide.title}")
        for b in slide.bullets:
            print(f"     - {b}")

    # Contrôles de qualité minimaux : un JSON valide ne suffit pas.
    problems = []
    if "{" in deck.title:
        problems.append("le titre contient du JSON")
    for i, slide in enumerate(deck.slides, 1):
        if slide.layout == "title":
            continue
        if not 3 <= len(slide.bullets) <= 5:
            problems.append(f"slide {i} : {len(slide.bullets)} puces (attendu 3 à 5)")
        if not slide.notes.strip():
            problems.append(f"slide {i} : pas de notes orateur")
    if problems:
        raise SystemExit("ÉCHEC :\n  - " + "\n  - ".join(problems))

    print(f"\nOK : Deck valide, {len(deck.slides)} slides, en {elapsed:.1f} s")


if __name__ == "__main__":
    main()
