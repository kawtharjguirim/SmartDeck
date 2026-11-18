"""Fine-tuning, étape 1 : documents sources fictifs pour le jeu d'entraînement.

Le jeu de test (samples/acceptance.json) n'est jamais utilisé pour l'entraînement :
les sources d'entraînement sont donc des documents fictifs, rédigés localement par
le 3B sur des sujets variés (rapports, procédures, notes de projet…), avec des
chiffres, des titres, parfois un tableau ou une liste d'étapes — comme les vrais
documents que SmartDeck reçoit. Ils sont marqués « FICTIF ».

Usage : python finetune/make_sources.py [nombre]   (≈ 45 s par document)
"""
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ollama  # noqa: E402

import config  # noqa: E402

OUT = Path(__file__).resolve().parent / "data" / "sources"

DOMAINS = [
    "une PME de transport", "une mairie de taille moyenne", "un hôpital régional",
    "une start-up de logiciels", "une coopérative laitière", "une école d'ingénieurs",
    "une association sportive", "un musée", "une chaîne de boulangeries", "un club de lecture",
    "une usine de pièces automobiles", "une agence de voyages", "un cabinet comptable",
    "une bibliothèque municipale", "une ferme solaire", "un festival de musique",
    "un réseau de pharmacies", "une entreprise de BTP", "un incubateur", "une ONG d'aide alimentaire",
    "un service informatique interne", "une plateforme de e-commerce", "un laboratoire de recherche",
    "une compagnie de théâtre", "un centre de formation professionnelle", "une banque coopérative",
    "un port de plaisance", "une clinique vétérinaire", "une maison d'édition", "un parc naturel",
]
KINDS = [
    ("rapport annuel", "les résultats de l'année, les équipes, les projets et les perspectives"),
    ("procédure interne", "les étapes d'un processus, les rôles et les délais (avec une liste numérotée)"),
    ("note de projet", "le contexte, les objectifs, le calendrier, le budget et les risques"),
    ("bilan trimestriel", "les chiffres par trimestre (avec un tableau Markdown) et leur évolution"),
    ("compte rendu de réunion", "les décisions prises, les chiffres présentés et les actions à mener"),
    ("étude de marché", "la taille du marché, les concurrents, les clients et les tendances"),
    ("plan de formation", "les modules, les publics, la durée et l'évaluation"),
    ("rapport d'incident", "la chronologie, les causes, l'impact chiffré et les mesures correctives"),
]
LANGUAGES = [("fr", "français")] * 7 + [("en", "anglais")] * 2 + [("ar", "arabe")]

PROMPT = """Écris un document FICTIF de type « {kind} » pour {domain}, en {language}.
Il traite de : {focus}.
- 300 à 450 mots, en Markdown : un titre (#) puis 3 à 5 sections (##).
- Des faits précis et cohérents : noms, dates, chiffres, pourcentages, montants.
- Organisations, marques et personnes inventées : aucune entreprise ni personne réelle.
- Paragraphes rédigés (pas seulement des listes).
Réponds uniquement avec le document."""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower())[:40].strip("_")


def main(count: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "LISEZMOI.txt").write_text(
        "Documents FICTIFS, rédigés localement par le modèle de rédaction pour constituer\n"
        "le jeu d'entraînement du fine-tuning (cahier des charges, section 14).\n"
        "Toute ressemblance avec des organisations réelles est fortuite.\n", encoding="utf-8")
    client = ollama.Client(host=config.OLLAMA_HOST)
    rng = random.Random(2026)
    existing = len(list(OUT.glob("*.md")))
    for i in range(existing, existing + count):
        domain, (kind, focus), (lang, language) = \
            rng.choice(DOMAINS), rng.choice(KINDS), rng.choice(LANGUAGES)
        response = client.chat(
            model=config.PLAN_MODEL,  # 3B : 3 à 4 fois plus rapide, suffisant pour une source
            messages=[{"role": "user", "content": PROMPT.format(
                kind=kind, domain=domain, language=language, focus=focus)}],
            options={"temperature": 0.8, "seed": 1000 + i, "num_ctx": 4096,
                     "num_predict": 1200},
        )
        text = response.message.content.strip()
        if len(text) < 800:  # réponse trop courte : on passe
            print(f"{i:03d} ignoré ({len(text)} caractères)", flush=True)
            continue
        path = OUT / f"{i:03d}_{lang}_{slug(kind)}_{slug(domain)}.md"
        path.write_text(text + "\n", encoding="utf-8")
        print(f"{i:03d} {lang} {kind} / {domain} : {len(text)} caractères", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 80)
