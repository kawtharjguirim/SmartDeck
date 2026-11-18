"""Fine-tuning, étape 5 : comparaison des modèles de rédaction (FT-03, FT-04).

Chaque modèle réécrit les slides des 10 documents du jeu de test (samples/acceptance.json,
jamais vus à l'entraînement), à partir des MÊMES plans (output/acceptance/*.work.json) :
seule la rédaction change.

  python finetune/compare.py write qwen2.5:7b          → output/compare/<modèle>/
  python finetune/compare.py judge qwen2.5:7b          → avis du juge sur chaque puce
  python finetune/compare.py report                    → finetune/rapport_evaluation.md

Mesures : réponses JSON valides du premier coup, chiffres absents de la source, notes
« méta », puces peu fidèles (mesure par les mots), puces non appuyées selon un juge
(qwen2.5:7b, qui lit l'extrait et la puce), durée de rédaction.
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, Field  # noqa: E402

import config  # noqa: E402
import llm.client as client  # noqa: E402
from finetune.evaluate import evaluate_folder  # noqa: E402
from llm.client import generate_structured  # noqa: E402
from schemas import Document, Outline, SlideContent  # noqa: E402
from writer import select_context, write  # noqa: E402

ACCEPTANCE = config.OUTPUT_DIR / "acceptance"
COMPARE = config.OUTPUT_DIR / "compare"
JUDGE_MODEL = "qwen2.5:7b"


def folder(model: str) -> Path:
    return COMPARE / re.sub(r"[^\w.-]+", "_", model)


def load_work(work_file: Path) -> tuple[Document, Outline]:
    work = json.loads(work_file.read_text(encoding="utf-8"))
    return Document.model_validate(work["document"]), Outline.model_validate(work["outline"])


def write_all(model: str) -> None:
    out = folder(model)
    out.mkdir(parents=True, exist_ok=True)
    config.WRITE_MODEL = model
    stats = {"modele": model, "slides": 0, "appels": 0, "json_invalides": 0, "secondes": 0.0}

    def recorder(_model, messages, schema, raw):
        if schema is SlideContent:
            stats["appels"] += 1
            try:
                SlideContent.model_validate_json(raw)
            except Exception:
                stats["json_invalides"] += 1

    for work_file in sorted(ACCEPTANCE.glob("*.work.json")):
        stem = work_file.name.removesuffix(".work.json")
        document, outline = load_work(work_file)
        client.RECORDER = recorder
        t = time.perf_counter()
        try:
            result = write(outline, document)
        finally:
            client.RECORDER = None
        stats["secondes"] += time.perf_counter() - t
        stats["slides"] += len(result.deck.slides) - 1
        (out / f"{stem}.deck.json").write_text(result.deck.model_dump_json(indent=2), encoding="utf-8")
        (out / f"{stem}.work.json").write_text(work_file.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"{model} · {stem} : {len(result.deck.slides)} slides", flush=True)
    stats["secondes"] = round(stats["secondes"])
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


class Verdict(BaseModel):
    supported: bool = Field(description="true si l'extrait affirme ou implique clairement la puce")


JUDGE_SYSTEM = ("Tu vérifies des puces de présentation. Une puce est appuyée si l'extrait "
                "l'affirme ou l'implique clairement, sans détail ajouté ni chiffre modifié. "
                "Une reformulation fidèle est appuyée. Tu réponds uniquement en JSON.")


def judge(model: str) -> None:
    out = folder(model)
    verdicts = []
    for deck_file in sorted(out.glob("*.deck.json")):
        stem = deck_file.name.removesuffix(".deck.json")
        document, outline = load_work(out / f"{stem}.work.json")
        deck = json.loads(deck_file.read_text(encoding="utf-8"))
        for slide, planned in zip(deck["slides"][1:], outline.planned_slides()):
            extract = select_context(document, planned)
            for bullet in slide["bullets"]:
                prompt = f'Extrait :\n"""\n{extract}\n"""\n\nPuce : « {bullet} »\n' \
                         "Cette puce est-elle appuyée par l'extrait ?"
                v = generate_structured(prompt, Verdict, system=JUDGE_SYSTEM, model=JUDGE_MODEL)
                verdicts.append({"deck": stem, "slide": slide["title"], "bullet": bullet,
                                 "supported": v.supported})
        print(f"juge · {model} · {stem}", flush=True)
    (out / "judge.json").write_text(json.dumps(verdicts, ensure_ascii=False, indent=2),
                                    encoding="utf-8")


def report() -> None:
    lines = ["# Évaluation du fine-tuning (FT-03, FT-04)", "",
             "Jeu de test : les 10 documents de samples/acceptance.json (jamais vus à "
             "l'entraînement). Mêmes plans pour tous les modèles : seule la rédaction change.",
             "", "| Modèle | JSON valides | Chiffres absents | Notes méta | Puces peu fidèles "
             "(mots) | Puces non appuyées (juge) | Durée |", "|---|---|---|---|---|---|---|"]
    for out in sorted(COMPARE.iterdir()):
        stats_file = out / "stats.json"
        if not stats_file.exists():
            continue
        stats = json.loads(stats_file.read_text(encoding="utf-8"))
        m = evaluate_folder(out, verbose=False)
        judge_file = out / "judge.json"
        if judge_file.exists():
            v = json.loads(judge_file.read_text(encoding="utf-8"))
            judged = f"{100 * sum(not x['supported'] for x in v) / len(v):.1f} % ({len(v)} puces)"
        else:
            judged = "—"
        valid = 100 * (stats["appels"] - stats["json_invalides"]) / max(stats["appels"], 1)
        lines.append(f"| {stats['modele']} | {valid:.0f} % | {m['chiffres_absents']} | "
                     f"{m['notes_meta_%']} % | {m['puces_inventees_%']} % | {judged} | "
                     f"{stats['secondes'] / 60:.0f} min |")
    path = Path(__file__).resolve().parent / "rapport_evaluation.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "report":
        report()
    else:
        {"write": write_all, "judge": judge}[action](sys.argv[2])
