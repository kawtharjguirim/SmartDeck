"""Compare deux campagnes de recette (même jeu de 10 documents, modèles différents).

Usage : python finetune/compare_campaigns.py output/acceptance output/acceptance_qwen3vl
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finetune.evaluate import evaluate_folder  # noqa: E402

rows = []
for folder in map(Path, sys.argv[1:]):
    m = evaluate_folder(folder, verbose=False)
    recette = json.loads((folder / "recette.json").read_text(encoding="utf-8"))
    seconds = sum(r["info"].get("secondes") or 0 for r in recette)
    passed = sum(not any(r["results"].values()) for r in recette)
    a_verifier = sum(r["info"].get("chiffres_a_verifier") or 0 for r in recette)
    rows.append((folder.name, passed, len(recette), m, a_verifier, seconds))

print("| Campagne | Docs 6/6 CA | Puces | Puces peu fidèles | Notes méta | Chiffres absents "
      "| À vérifier (rapport) | Durée totale |")
print("|---|---|---|---|---|---|---|---|")
for name, passed, n, m, a_verifier, seconds in rows:
    print(f"| {name} | {passed}/{n} | {m['puces']} | {m['puces_inventees_%']} % | "
          f"{m['notes_meta_%']} % ({m['notes_meta']}) | {m['chiffres_absents']} | {a_verifier} | "
          f"{seconds / 60:.0f} min |")
for name, *_ , m, _a, _s in [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]:
    print(f"\n{name} — exemples de puces peu fidèles :")
    for e in m["exemples"]["puces_inventees"][:6]:
        print(f"  - {e}")
