"""Fine-tuning : relecture humaine d'un échantillon du jeu d'entraînement (FT-01).

Lancer :  .venv\\Scripts\\streamlit run finetune\\review_app.py --server.port 8502

Pour chaque exemple tiré au hasard : les extraits fournis au modèle, puis la réponse
retenue par les filtres. Trois choix : Valider, Corriger (puces / notes modifiables),
Rejeter. Les décisions vont dans finetune/data/review.json et sont appliquées par
`build_dataset.py select`. Le taux de validation mesure la précision des filtres.
"""
import json
import random
import re
from pathlib import Path

import streamlit as st

DATA = Path(__file__).resolve().parent / "data"
REVIEW = DATA / "review.json"
SAMPLE_SIZE = 60
_EXTRACT = re.compile(r'Extraits du document :\n"""\n(.*)\n"""', re.DOTALL)
_VISUAL = re.compile(r"^La slide affiche aussi .*$", re.MULTILINE)

st.set_page_config(page_title="Relecture SmartDeck", page_icon="📝", layout="wide")


def key(row: dict) -> str:
    return f"{row['source']}::{row['title']}"


@st.cache_data
def sample() -> list[dict]:
    rows = [json.loads(line) for line in (DATA / "train.jsonl").open(encoding="utf-8")]
    return random.Random(14).sample(rows, min(SAMPLE_SIZE, len(rows)))


def load_review() -> dict:
    return json.loads(REVIEW.read_text(encoding="utf-8")) if REVIEW.exists() else {}


rows, review = sample(), load_review()
done = sum(key(r) in review for r in rows)
st.title("Relecture du jeu d'entraînement")
st.progress(done / len(rows), text=f"{done} / {len(rows)} exemples relus")
counts = {d: sum(v["decision"] == d for v in review.values()) for d in ("ok", "corrige", "rejete")}
st.caption(f"Validés : {counts['ok']} · Corrigés : {counts['corrige']} · Rejetés : {counts['rejete']}")

pending = [r for r in rows if key(r) not in review]
if not pending:
    st.success("Échantillon entièrement relu. Relancez « build_dataset.py select » pour "
              "appliquer les décisions.")
    st.stop()

row = pending[0]
prompt, answer = row["messages"][1]["content"], json.loads(row["messages"][2]["content"])
st.subheader(row["title"])
st.caption(f"Source : {row['source']} (document fictif)")
left, right = st.columns(2)
with left:
    st.markdown("**Extraits fournis au modèle**")
    visual = _VISUAL.search(prompt)
    if visual:
        st.info(visual.group(0))
    st.text_area("Extraits", _EXTRACT.search(prompt).group(1), height=420, disabled=True,
                 label_visibility="collapsed")
with right:
    st.markdown("**Réponse retenue** : chaque puce doit être vraie d'après les extraits, "
                "les notes doivent s'adresser au public.")
    bullets = st.text_area("Puces (une par ligne)", "\n".join(answer["bullets"]), height=180)
    notes = st.text_area("Notes orateur", answer["notes"], height=150)
    edited = (bullets.strip().splitlines() != answer["bullets"]) or notes.strip() != answer["notes"]
    c1, c2, c3 = st.columns(3)
    if c1.button("✅ Valider", type="primary", width="stretch", disabled=edited):
        review[key(row)] = {"decision": "ok"}
    if c2.button("✏️ Enregistrer la correction", width="stretch", disabled=not edited):
        review[key(row)] = {"decision": "corrige", "bullets": [b.strip() for b in
                            bullets.splitlines() if b.strip()], "notes": notes.strip()}
    if c3.button("🗑️ Rejeter", width="stretch"):
        review[key(row)] = {"decision": "rejete"}
    if key(row) in review:
        REVIEW.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        st.rerun()
