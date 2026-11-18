"""Fine-tuning, étape 2 : jeu d'entraînement du modèle de rédaction (FT-01).

1. collect : pour chaque document fictif (data/sources), le vrai pipeline tourne
   (plan 3B → rédaction 7B) et chaque réponse du rédacteur est enregistrée avec
   le prompt exact de production (llm.client.RECORDER).
2. select : pour chaque slide, on garde la meilleure réponse qui passe tous les
   filtres, associée au prompt de la 1re tentative (sans les consignes de correction) :
   le modèle apprend à réussir du premier coup.
     - JSON valide (SlideContent : 3 à 5 puces, notes)
     - aucun chiffre absent du document (FR-12)
     - chaque puce : au moins 75 % de ses mots dans les extraits fournis
     - notes : au moins 60 % de leurs mots dans les extraits, pas de « Cette slide… »
3. Répartition 80/10/10 par document source (jamais un même document dans deux jeux).

Usage :
  python finetune/build_dataset.py collect     (≈ 3 min par document, reprend où il s'est arrêté)
  python finetune/build_dataset.py select      (quelques secondes)
"""
import hashlib
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import llm.client as client  # noqa: E402
from ingest import load_document  # noqa: E402
from planner import plan  # noqa: E402
from quality.faithfulness import (content_words, is_meta_note, source_vocabulary,  # noqa: E402
                                  support)
from quality.numbers import source_numbers, unsupported_numbers  # noqa: E402
from schemas import SlideContent  # noqa: E402
from writer import write  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
SOURCES, RAW = DATA / "sources", DATA / "raw"
BULLET_SUPPORT, NOTES_SUPPORT = 0.75, 0.6
_FEEDBACK = re.compile(r"\nATTENTION : .*\n")
_TITLE = re.compile(r"^Titre de la slide : (.*)$", re.MULTILINE)
_EXTRACT = re.compile(r'Extraits du document :\n"""\n(.*)\n"""', re.DOTALL)


# --- 1. Collecte ---------------------------------------------------------------

def collect() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    sources = sorted(SOURCES.glob("*.md"))
    for path in sources:
        n_slides = rng.randint(6, 8)  # tirage fait même si le document est déjà traité
        out = RAW / f"{path.stem}.json"
        if out.exists():
            continue
        records: dict[str, dict] = {}

        def recorder(model, messages, schema, raw):
            if schema is not SlideContent:
                return
            prompt = _FEEDBACK.sub("\n", messages[1]["content"])  # prompt de la 1re tentative
            title = _TITLE.search(prompt).group(1)
            rec = records.setdefault(title, {"system": messages[0]["content"],
                                             "prompt": prompt, "candidates": []})
            rec["candidates"].append(raw)

        try:
            document = load_document(path)
            outline = plan(document, n_slides=n_slides).outline
            client.RECORDER = recorder
            write(outline, document)
        except Exception as e:  # un document raté ne bloque pas la collecte
            print(f"{path.name} : ignoré ({type(e).__name__}: {e})", flush=True)
            continue
        finally:
            client.RECORDER = None
        out.write_text(json.dumps({"source": path.name, "document": document.model_dump(),
                                   "slides": records}, ensure_ascii=False), encoding="utf-8")
        n = sum(len(r["candidates"]) for r in records.values())
        print(f"{path.name} : {len(records)} slides, {n} réponses", flush=True)


# --- 2. Sélection -----------------------------------------------------------

def check(raw: str, extract: str, known: set[float]) -> list[str]:
    """Problèmes d'une réponse du rédacteur ; liste vide = exemple valide."""
    try:
        content = SlideContent.model_validate_json(raw)
    except Exception:
        return ["JSON invalide"]
    problems = []
    vocab = source_vocabulary(extract)
    missing = unsupported_numbers(" ".join(content.bullets) + " " + content.notes, known)
    if missing:
        problems.append(f"chiffres absents : {missing}")
    for b in content.bullets:
        if support(b, vocab) < BULLET_SUPPORT:
            problems.append(f"puce peu fidèle : {b}")
    if is_meta_note(content.notes):
        problems.append("note méta")
    if content_words(content.notes) and support(content.notes, vocab) < NOTES_SUPPORT:
        problems.append("notes peu fidèles")
    return problems


def split_of(source: str) -> str:
    h = int(hashlib.sha1(source.encode()).hexdigest(), 16) % 10
    return "train" if h < 8 else ("valid" if h == 8 else "test")


def select() -> None:
    from schemas import Document
    stats = {"slides": 0, "gardees": 0, "rejets": {}}
    splits = {"train": [], "valid": [], "test": []}
    review_file = DATA / "review.json"
    review = json.loads(review_file.read_text(encoding="utf-8")) if review_file.exists() else {}
    for raw_file in sorted(RAW.glob("*.json")):
        data = json.loads(raw_file.read_text(encoding="utf-8"))
        known = source_numbers(Document.model_validate(data["document"]))
        for title, rec in data["slides"].items():
            stats["slides"] += 1
            extract = _EXTRACT.search(rec["prompt"]).group(1)
            best = None
            for raw in rec["candidates"]:
                problems = check(raw, extract, known)
                if not problems:
                    best = raw
                    break
                for p in problems:
                    key = p.split(" :")[0]
                    stats["rejets"][key] = stats["rejets"].get(key, 0) + 1
            if best is None:
                continue
            content = SlideContent.model_validate_json(best)
            decision = review.get(f"{data['source']}::{title}", {})
            if decision.get("decision") == "rejete":  # relecture humaine (review_app.py)
                stats["rejets"]["relecture"] = stats["rejets"].get("relecture", 0) + 1
                continue
            if decision.get("decision") == "corrige":
                content = SlideContent(bullets=decision["bullets"], notes=decision["notes"])
            stats["gardees"] += 1
            answer = json.dumps(content.model_dump(), ensure_ascii=False)
            splits[split_of(data["source"])].append({
                "source": data["source"], "title": title,
                "messages": [{"role": "system", "content": rec["system"]},
                             {"role": "user", "content": rec["prompt"]},
                             {"role": "assistant", "content": answer}]})
    for name, rows in splits.items():
        with (DATA / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    stats |= {k: len(v) for k, v in splits.items()}
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    {"collect": collect, "select": select}[sys.argv[1]]()
