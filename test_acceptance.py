"""Étape 14 : critères d'acceptation CA-01 à CA-06 sur le jeu de test (CDC section 10).

Le jeu (samples/acceptance.json) : 2 textes, 3 PDF natifs, 2 PDF scannés, 3 images.
Chaque document passe par tout le pipeline (ingestion → plan → rédaction → PPTX → PDF),
réseau coupé pour Python et connexions surveillées pour les autres outils.

  CA-01  chaque type d'entrée produit un deck valide
  CA-02  aucune valeur de graphique absente de la source
  CA-03  aucune puce ne dépasse sa zone (mesure Pillow dans le PPTX final)
  CA-04  le PPTX s'ouvre dans PowerPoint et dans LibreOffice
  CA-05  nombre de slides demandé respecté à ±1
  CA-06  aucun appel réseau pendant la génération

Usage :
  python test_acceptance.py              → tout le jeu (≈ 30 min), résultats dans output/acceptance/
  python test_acceptance.py verdi        → seulement les documents dont le nom contient « verdi »
  python test_acceptance.py --checks     → refait les contrôles sans régénérer
"""
import ipaddress
import json
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil
import pymupdf
from pptx import Presentation
from pptx.util import Emu

import config
from build import pptx_builder as pb
from generate import Run, generate, load_run, save
from quality.numbers import source_numbers
from schemas import MAX_WORDS_PER_BULLET, Deck

SAMPLES = config.ROOT_DIR / "samples"
OUT = config.OUTPUT_DIR / "acceptance"
CRITERIA = ["CA-01", "CA-02", "CA-03", "CA-04", "CA-05", "CA-06"]
WATCHED = ("ollama", "soffice", "tesseract", "dot")


# --- CA-06 : surveillance du réseau ------------------------------------------

def _is_local(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip.split("%")[0]).is_loopback
    except ValueError:
        return False


class NetworkGuard:
    """Coupe le réseau de Python (sauf la boucle locale vers Ollama) et surveille les
    connexions des autres processus de la génération (Ollama, LibreOffice, Tesseract…)."""

    def __init__(self):
        self.blocked: list[str] = []
        self.seen: set[str] = set()
        self._stop = threading.Event()
        self._original = socket.socket.connect

    def __enter__(self):
        guard = self

        def connect(sock, address):
            host = address[0] if isinstance(address, tuple) else str(address)
            if isinstance(address, tuple) and not _is_local(host):
                guard.blocked.append(f"python → {host}:{address[1]}")
                raise OSError(f"réseau coupé par le test (CA-06) : {host}")
            return guard._original(sock, address)

        socket.socket.connect = connect
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        socket.socket.connect = self._original

    def _processes(self):
        me = psutil.Process()
        procs = [me, *me.children(recursive=True)]
        for p in psutil.process_iter(["name"]):
            name = (p.info["name"] or "").lower()
            # « ollama app.exe » (icône de la barre des tâches) cherche des mises à jour :
            # ce n'est pas la génération. Le serveur et ses runners sont surveillés.
            if name.startswith(WATCHED) and "app" not in name:
                procs.append(p)
        return procs

    def _watch(self):
        while not self._stop.is_set():
            for p in self._processes():
                try:
                    for c in p.net_connections(kind="inet"):
                        if c.raddr and not _is_local(c.raddr.ip):
                            self.seen.add(f"{p.name()} → {c.raddr.ip}:{c.raddr.port}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self._stop.wait(0.3)

    def problems(self) -> list[str]:
        return sorted(set(self.blocked) | self.seen)


# --- Contrôles ---------------------------------------------------------------

def check_deck(run: Run, expected: dict) -> list[str]:
    """CA-01 : deck valide, conforme au type d'entrée, contenu complet."""
    problems = []
    doc, deck = run.document, run.deck
    if doc.origin != expected["origin"]:
        problems.append(f"type {doc.origin}, attendu {expected['origin']}")
    if deck.language != expected["language"]:
        problems.append(f"langue {deck.language}, attendue {expected['language']}")
    text = doc.full_text()
    missing = [f for f in expected["facts"] if f not in text]
    if missing:
        problems.append(f"faits absents du Document extrait : {missing}")
    Deck.model_validate_json(run.path("deck.json").read_text(encoding="utf-8"))
    prs = Presentation(str(run.path("pptx")))
    if len(prs.slides) != len(deck.slides):
        problems.append(f"PPTX : {len(prs.slides)} slides pour {len(deck.slides)}")
    for i, s in enumerate(deck.slides[1:], 2):
        low, high = (1, config.VISUAL_BULLETS) if s.layout in ("chart", "diagram") else (3, 5)
        if not low <= len(s.bullets) <= high:
            problems.append(f"slide {i} : {len(s.bullets)} puces")
        if len(s.notes) < 20:
            problems.append(f"slide {i} : notes orateur absentes")
    return problems


def check_chart_values(run: Run) -> list[str]:
    """CA-02 : chaque valeur de graphique est dans les blocs extraits."""
    known = source_numbers(run.document)
    return [f"slide {i} « {s.title} » : {v:g} absent de la source"
            for i, s in enumerate(run.deck.slides, 1) if s.chart
            for v in s.chart.values if round(v, 6) not in known]


def check_overflow(pptx: Path) -> list[str]:
    """CA-03 : chaque zone de texte du PPTX final est mesurée (Pillow, police réelle)."""
    problems = []
    prs = Presentation(str(pptx))
    for n, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if not shape.has_text_frame or not shape.text_frame.text.strip():
                continue
            paragraphs = [p for p in shape.text_frame.paragraphs if p.text.strip()]
            sizes = [r.font.size.pt for p in paragraphs for r in p.runs if r.font.size]
            if not sizes:
                continue
            size = max(sizes)
            bold = any(r.font.bold for p in paragraphs for r in p.runs)
            texts = [p.text for p in paragraphs]
            # Retrait des puces : seulement dans la zone de texte principale (comme le builder).
            is_body = shape.is_placeholder and shape.placeholder_format.type in (
                pb.PP_PLACEHOLDER.BODY, pb.PP_PLACEHOLDER.OBJECT)
            indent = pb.BULLET_INDENT if is_body else Emu(0)
            _, fits = pb.fit_size(texts, shape.width, shape.height, (int(size),),
                                  indent=indent, bold=bold)
            if not fits:
                problems.append(f"slide {n} : « {texts[0][:40]}… » déborde en {size:g} pt")
            for t in texts:
                if len(t.split()) > MAX_WORDS_PER_BULLET + 2:
                    problems.append(f"slide {n} : texte de {len(t.split())} mots")
    return problems


def check_libreoffice(run: Run) -> list[str]:
    """CA-04 (LibreOffice) : le PDF a été produit par LibreOffice avec toutes les pages."""
    pdf = run.report.get("fichiers", {}).get("pdf")
    if not pdf or not Path(pdf).exists():
        return ["LibreOffice : PDF non produit"]
    if any("PDF exporté avec" in w for w in run.report.get("avertissements", [])):
        return ["LibreOffice absent : PDF fait par un autre outil"]
    with pymupdf.open(pdf) as d:
        if d.page_count != len(run.deck.slides):
            return [f"LibreOffice : {d.page_count} pages pour {len(run.deck.slides)} slides"]
    return []


def check_powerpoint(pptx_files: list[Path]) -> dict[str, list[str]]:
    """CA-04 (PowerPoint) : ouverture de tous les PPTX dans une seule session COM."""
    script = config.ROOT_DIR / "tools" / "check_open_pptx.ps1"
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(script), *map(str, pptx_files)],
                            capture_output=True, text=True, encoding="utf-8", timeout=600)
    opened = dict(line.split("|", 1) for line in result.stdout.splitlines() if "|" in line)
    out = {}
    for f in pptx_files:
        status = opened.get(f.name, "non ouvert")
        out[f.name] = [] if status.isdigit() else [f"PowerPoint : {status}"]
    return out


# --- Campagne ------------------------------------------------------------------

def guard_self_test() -> None:
    """Le garde-fou de CA-06 doit bloquer et consigner une connexion sortante.
    192.0.2.1 est une adresse de test réservée (RFC 5737) : jamais routée sur Internet."""
    with NetworkGuard() as guard:
        try:
            socket.create_connection(("192.0.2.1", 80), timeout=1)
        except OSError:
            pass
    if not guard.blocked:
        sys.exit("Garde-fou CA-06 inopérant : connexion sortante non détectée")
    print(f"Garde-fou CA-06 vérifié : {guard.blocked[0]} bloqué", flush=True)


def run_campaign(only: str | None, checks_only: bool) -> None:
    if not checks_only:
        guard_self_test()
    spec = json.loads((SAMPLES / "acceptance.json").read_text(encoding="utf-8"))
    docs = [d for d in spec["documents"] if not only or only in d["file"]]
    config.OUTPUT_DIR = OUT  # les sorties de la campagne restent à part
    OUT.mkdir(parents=True, exist_ok=True)

    rows = []
    for d in docs:
        source = SAMPLES / d["file"]
        stem = OUT / Path(d["file"]).stem
        row = {"file": d["file"], "type": d["origin"], "requested": d["slides"],
               "results": {c: [] for c in CRITERIA}, "info": {}}
        print(f"\n▶ {d['file']} ({d['origin']}, {d['slides']} slides)", flush=True)
        t = time.perf_counter()
        try:
            if checks_only:
                run = load_run(Path(f"{stem}.deck.json"))
                row["results"]["CA-06"] = run.report.get(
                    "acceptance_network", ["réseau non surveillé (régénérer sans --checks)"])
            else:
                with NetworkGuard() as guard:
                    run = generate(source, d["slides"], None, pdf=True,
                                   progress=lambda s, n, m: print(f"   {m}", flush=True))
                row["results"]["CA-06"] = guard.problems()
                run.report["acceptance_network"] = guard.problems()
                save(run)  # résultat réseau conservé pour --checks
            seconds = time.perf_counter() - t
        except Exception as e:  # un échec de génération fait échouer CA-01 pour ce document
            row["results"]["CA-01"] = [f"génération impossible : {type(e).__name__}: {e}"]
            rows.append(row)
            print(f"   ✘ {e}", flush=True)
            continue

        produced = len(run.deck.slides)
        row["results"]["CA-01"] += check_deck(run, d)
        row["results"]["CA-02"] = check_chart_values(run)
        row["results"]["CA-03"] = check_overflow(run.path("pptx"))
        row["results"]["CA-04"] = check_libreoffice(run)
        if abs(produced - d["slides"]) > 1:
            row["results"]["CA-05"] = [f"{produced} slides pour {d['slides']} demandées"]
        layouts = [s.layout for s in run.deck.slides]
        row["info"] = {
            "slides": produced, "secondes": round(seconds) if not checks_only else None,
            "visuels": [l for l in layouts if l in ("chart", "diagram")],
            "visuels_attendus": d["visuals"],
            "chiffres_a_verifier": len(run.report.get("a_verifier", [])),
            "pptx": str(run.path("pptx")),
        }
        rows.append(row)
        print(f"   {produced} slides, visuels {row['info']['visuels']}, "
              f"{row['info']['chiffres_a_verifier']} chiffre(s) à vérifier", flush=True)

    pptx_files = [Path(r["info"]["pptx"]) for r in rows if r["info"].get("pptx")]
    if pptx_files:
        print("\n▶ CA-04 : ouverture dans PowerPoint…", flush=True)
        for name, problems in check_powerpoint(pptx_files).items():
            row = next(r for r in rows if Path(r["info"].get("pptx", "")).name == name)
            row["results"]["CA-04"] += problems

    write_report(rows, checks_only)


def write_report(rows: list[dict], checks_only: bool) -> None:
    # Campagne partielle : les autres documents gardent leur dernier résultat.
    previous = OUT / "recette.json"
    if previous.exists():
        done = {r["file"] for r in rows}
        order = [d["file"] for d in json.loads(
            (SAMPLES / "acceptance.json").read_text(encoding="utf-8"))["documents"]]
        kept = [r for r in json.loads(previous.read_text(encoding="utf-8"))
                if r["file"] not in done and r["file"] in order]
        rows = sorted(rows + kept, key=lambda r: order.index(r["file"]))
    ok = lambda r, c: not r["results"][c]  # noqa: E731
    header = "| Document | Type | " + " | ".join(CRITERIA) + " | Slides | Visuels | À vérifier |"
    lines = [f"# Recette SmartDeck — {datetime.now():%d/%m/%Y %H:%M}", "",
             f"Modèles : plan {config.PLAN_MODEL}, rédaction {config.WRITE_MODEL}, "
             f"vision {config.VISION_MODEL}" + (" (contrôles seuls)" if checks_only else ""), "",
             header, "|" + "---|" * (len(CRITERIA) + 5)]
    for r in rows:
        info = r["info"]
        visuals = ", ".join(info.get("visuels", [])) or "—"
        expected = ", ".join(info.get("visuels_attendus", [])) or "—"
        lines.append(f"| {r['file']} | {r['type']} | "
                     + " | ".join("✔" if ok(r, c) else "✘" for c in CRITERIA)
                     + f" | {info.get('slides', '—')}/{r['requested']} | {visuals} "
                       f"(attendu : {expected}) | {info.get('chiffres_a_verifier', '—')} |")
    passed = {c: sum(ok(r, c) for r in rows) for c in CRITERIA}
    lines += ["", "**Bilan : " + ", ".join(f"{c} {passed[c]}/{len(rows)}" for c in CRITERIA)
              + "**", "", "## Détail des échecs", ""]
    failures = [(r["file"], c, p) for r in rows for c in CRITERIA for p in r["results"][c]]
    lines += [f"- {f} — {c} : {p}" for f, c, p in failures] or ["Aucun."]
    report = "\n".join(lines) + "\n"
    (OUT / "recette.md").write_text(report, encoding="utf-8")
    (OUT / "recette.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    print("\n" + report)
    print(f"Rapport : {OUT / 'recette.md'}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run_campaign(args[0] if args else None, "--checks" in sys.argv)
