"""Agent relecteur : Qwen3-VL relit la présentation générée et la corrige.

Option au-dessus du pipeline, qui reste inchangé et déterministe :
1. le code mesure les défauts de chaque slide (agent/checks.py) ;
2. l'agent, un modèle multimodal qui appelle des outils, reçoit ce bilan et peut
   - regarder une slide rendue (image) : texte qui déborde, visuel illisible… ;
   - réécrire une slide avec une consigne précise ;
   - terminer, avec un résumé ;
3. le code ne garde une réécriture que si les défauts mesurés n'augmentent pas
   (garde-fou), puis reconstruit PPTX et PDF.

L'utilisateur peut aussi donner un objectif (« raccourcis les puces de la slide 3 »).
Budget borné : AGENT_MAX_STEPS appels d'outils, AGENT_MAX_REWRITES réécritures.
Tout reste local (Ollama) ; aucune donnée ne sort du PC.
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import ollama
import pymupdf

import config
from agent.checks import Checker, SlideIssues
from build.pdf_export import PdfExportError, export_pdf
from build.pptx_builder import build_pptx
from generate import Run, rebuild, replace_slide, save
from llm.client import LLMError, unload
from writer import rewrite_slide

Log = Callable[[str], None]

SYSTEM = """Tu es le relecteur d'une présentation générée automatiquement à partir d'un document.
Tu améliores la présentation en appelant des outils, un appel à la fois.
- voir_slide : regarder l'image d'une slide (mise en page, texte qui déborde, visuel lisible).
- reecrire_slide : faire réécrire une slide, avec une consigne courte et précise.
- terminer : quand il n'y a plus rien d'utile à faire, avec un résumé en une ou deux phrases.
Règles :
- Traite les slides dans l'ordre de priorité donné ; ignore celles sans défaut,
  sauf si l'objectif de l'utilisateur les concerne.
- La consigne décrit le défaut à corriger, pas le texte à écrire (ex. « retirer le
  chiffre 12 %, absent du document », « notes adressées directement au public »,
  « ne pas répéter le conseil de 9 membres, déjà dit slide 3 »).
- Ne fais jamais une simple reformulation : si un défaut ne se corrige pas, passe.
- voir_slide sert pour les slides avec graphique ou diagramme, ou si un texte semble
  trop long. Ne regarde pas chaque slide.
- Ne réécris jamais la slide 1 (titre). N'ajoute aucune information absente du document."""

TOOLS = [
    {"type": "function", "function": {
        "name": "voir_slide",
        "description": "Montre l'image de la slide numéro `numero` (1 = slide de titre).",
        "parameters": {"type": "object", "required": ["numero"], "properties": {
            "numero": {"type": "integer", "description": "numéro de la slide"}}}}},
    {"type": "function", "function": {
        "name": "reecrire_slide",
        "description": "Réécrit les puces et les notes de la slide `numero` selon `consigne`.",
        "parameters": {"type": "object", "required": ["numero", "consigne"], "properties": {
            "numero": {"type": "integer", "description": "numéro de la slide (2 ou plus)"},
            "consigne": {"type": "string", "description": "ce qu'il faut changer"}}}}},
    {"type": "function", "function": {
        "name": "terminer",
        "description": "Termine la relecture.",
        "parameters": {"type": "object", "required": ["resume"], "properties": {
            "resume": {"type": "string", "description": "ce qui a été fait"}}}}},
]


# Relecture guidée (sans objectif utilisateur) : le code choisit la slide, l'agent décide.
SLIDE_SYSTEM = """Tu es le relecteur d'une slide générée automatiquement à partir d'un document.
On te donne la slide, ses défauts mesurés et parfois son image. Appelle un seul outil :
- reecrire_slide : si un défaut peut être corrigé, avec une consigne qui décrit le défaut
  à corriger (ex. « retirer le chiffre 12 %, absent du document », « notes adressées
  directement au public », « ne pas répéter le conseil de 9 membres, déjà dit ailleurs »).
  Ne dicte pas le texte et ne demande pas une simple reformulation.
- passer : si la slide est correcte ou si le défaut ne peut pas être corrigé.
N'ajoute jamais d'information absente du document."""

SLIDE_TOOLS = [
    {"type": "function", "function": {
        "name": "reecrire_slide",
        "description": "Fait réécrire la slide selon `consigne`.",
        "parameters": {"type": "object", "required": ["consigne"], "properties": {
            "consigne": {"type": "string", "description": "le défaut à corriger"}}}}},
    {"type": "function", "function": {
        "name": "passer",
        "description": "Laisse la slide telle quelle.",
        "parameters": {"type": "object", "required": ["raison"], "properties": {
            "raison": {"type": "string", "description": "pourquoi"}}}}},
]


@dataclass
class AgentResult:
    summary: str
    actions: list[dict] = field(default_factory=list)
    score_before: int = 0
    score_after: int = 0
    seconds: float = 0.0
    changed: bool = False


class _Session:
    """État d'une relecture : le run, les défauts, le rendu des slides."""

    def __init__(self, run: Run, goal: str, log: Log, model: str):
        self.run, self.goal, self.log, self.model = run, goal, log, model
        self.checker = Checker(run.document)
        self.issues: dict[int, SlideIssues] = self.checker.deck(run.deck)
        self.rewrites: dict[int, int] = {}
        self.tried: dict[int, set[str]] = {}  # consignes déjà essayées, par slide
        self.actions: list[dict] = []
        self.changed = False
        self._pdf: Path | None = None
        pdf = run.report.get("fichiers", {}).get("pdf")
        if pdf and Path(pdf).exists():
            self._pdf = Path(pdf)
        self._client = ollama.Client(host=config.OLLAMA_HOST)

    # --- Ce que l'agent voit ----------------------------------------------

    def overview(self) -> str:
        lines = [f"Présentation « {self.run.deck.title} », {len(self.run.deck.slides)} slides, "
                 f"langue {self.run.deck.language}."]
        for i, slide in enumerate(self.run.deck.slides):
            if i == 0:
                lines.append(f"Slide 1 (titre) : {slide.title}")
                continue
            lines.append(f"Slide {i + 1} [{slide.layout}] « {slide.title} »")
            for b in slide.bullets:
                lines.append(f"   - {b}")
            lines.append(f"   notes : {slide.notes}")
            lines.append(f"   défauts : {self.issues[i].describe()}")
        ranked = sorted((i for i in self.issues if self.issues[i].score),
                        key=lambda i: -self.issues[i].score)
        lines.append("Priorité (slide : points de défaut) : "
                     + (", ".join(f"{i + 1} : {self.issues[i].score}" for i in ranked)
                        or "aucun défaut mesuré"))
        return "\n".join(lines)

    def _render(self, index: int) -> bytes:
        """Image PNG de la slide (PDF existant, sinon export dans .cache/agent)."""
        if self._pdf is None:
            out = config.ROOT_DIR / ".cache" / "agent"
            out.mkdir(parents=True, exist_ok=True)
            pptx = out / "relecture.pptx"
            build_pptx(self.run.deck, pptx, source=self.run.report.get("source", ""),
                       theme=self.run.theme, logo=self.run.logo)
            self._pdf, _ = export_pdf(pptx, out)
        with pymupdf.open(self._pdf) as doc:
            return doc[index].get_pixmap(dpi=config.AGENT_IMAGE_DPI).tobytes("png")

    # --- Outils -----------------------------------------------------------

    def _index(self, args: dict) -> int:
        try:
            n = int(args.get("numero"))
        except (TypeError, ValueError):
            raise ValueError("numéro de slide manquant ou invalide")
        if not 1 <= n <= len(self.run.deck.slides):
            raise ValueError(f"il n'y a pas de slide {n} (1 à {len(self.run.deck.slides)})")
        return n - 1

    def voir_slide(self, args: dict) -> tuple[str, bytes | None]:
        index = self._index(args)
        try:
            image = self._render(index)
        except PdfExportError as e:
            return f"Rendu impossible : {e}", None
        slide = self.run.deck.slides[index]
        defauts = self.issues[index].describe() if index else "slide de titre"
        return (f"Image de la slide {index + 1} « {slide.title} » ci-dessous. "
                f"Défauts mesurés : {defauts}."), image

    def reecrire_slide(self, args: dict) -> str:
        index = self._index(args)
        if index == 0:
            return "Refusé : la slide 1 (titre) est écrite par le code."
        if sum(self.rewrites.values()) >= config.AGENT_MAX_REWRITES:
            return "Refusé : budget de réécritures épuisé. Appelle terminer."
        if self.rewrites.get(index, 0) >= 2:
            return f"Refusé : la slide {index + 1} a déjà été réécrite deux fois."
        consigne = str(args.get("consigne", "")).strip()[:300]
        if not consigne:
            return "Refusé : la consigne est vide."
        if consigne.lower() in self.tried.setdefault(index, set()):
            return "Refusé : cette consigne a déjà été essayée sur cette slide."
        self.tried[index].add(consigne.lower())
        self.rewrites[index] = self.rewrites.get(index, 0) + 1
        before = self.issues[index]

        self.log(f"Réécriture de la slide {index + 1} : {consigne}")
        if config.AGENT_WRITE_MODEL != self.model:
            unload(self.model)  # 4 Go de VRAM : l'agent laisse la place au rédacteur
        try:
            slide, warnings = rewrite_slide(self.run.outline, self.run.document, self.run.deck,
                                            index, instruction=consigne,
                                            model=config.AGENT_WRITE_MODEL)
        except (ValueError, LLMError) as e:
            return f"Échec de la réécriture : {e}"
        after = self.checker.slide(self.run.deck, index, slide)
        action = {"outil": "reecrire_slide", "slide": index + 1, "consigne": consigne,
                  "score_avant": before.score, "score_apres": after.score}
        # Garde-fou : en relecture, la nouvelle version doit être strictement meilleure ;
        # avec un objectif utilisateur (non mesurable), elle ne doit pas être pire.
        if after.score > before.score or (not self.goal and after.score == before.score):
            action["gardee"] = False
            self.actions.append(action)
            self.log(f"   version rejetée (défauts {before.score} → {after.score})")
            return (f"Nouvelle version REJETÉE : défauts {before.score} → {after.score} "
                    f"({after.describe()}). L'ancienne version est conservée.")
        replace_slide(self.run, index, slide, warnings, by="agent")
        self.issues = self.checker.deck(self.run.deck)  # les doublons dépendent des autres slides
        self.changed, self._pdf = True, None  # le rendu n'est plus à jour
        action["gardee"] = True
        self.actions.append(action)
        self.log(f"   version gardée (défauts {before.score} → {after.score})")
        bullets = "\n".join(f"- {b}" for b in slide.bullets)
        return (f"Slide {index + 1} réécrite et gardée.\n{bullets}\nnotes : {slide.notes}\n"
                f"Défauts mesurés : {self.issues[index].describe()}.")

    # --- Boucle -------------------------------------------------------------

    def _chat(self, messages: list[dict], tools: list[dict] = TOOLS):
        # Seule la dernière image reste jointe : le contexte (8k tokens) ne tient pas plus.
        last = max((i for i, m in enumerate(messages) if m.get("images")), default=-1)
        sent = [m if i == last or not m.get("images")
                else {k: v for k, v in m.items() if k != "images"} for i, m in enumerate(messages)]
        try:
            return self._client.chat(model=self.model, messages=sent, tools=tools,
                                     options={"temperature": 0.1, "seed": config.SEED,
                                              "num_ctx": config.NUM_CTX, "num_predict": 400})
        except ConnectionError as e:
            raise LLMError(f"Ollama injoignable sur {config.OLLAMA_HOST}") from e
        except ollama.ResponseError as e:
            raise LLMError(f"Erreur Ollama : {e.error}") from e

    def loop(self) -> str:
        return self.free_loop() if self.goal else self.guided_loop()

    def guided_loop(self) -> str:
        """Relecture : slides par priorité (défauts mesurés), l'agent décide pour chacune."""
        done: set[int] = set()
        while sum(self.rewrites.values()) < config.AGENT_MAX_REWRITES:
            todo = [i for i in sorted(self.issues, key=lambda i: -self.issues[i].score)
                    if self.issues[i].score and i not in done]
            if not todo:
                break
            done.add(todo[0])
            self._review_slide(todo[0])
        return "Relecture guidée terminée."

    def _review_slide(self, index: int) -> None:
        slide = self.run.deck.slides[index]
        bullets = "\n".join(f"- {b}" for b in slide.bullets)
        user: dict = {"role": "user", "content": (
            f"Présentation « {self.run.deck.title} ». Slide {index + 1} [{slide.layout}] "
            f"« {slide.title} »\n{bullets}\nnotes : {slide.notes}\n"
            f"Défauts mesurés : {self.issues[index].describe()}")}
        if slide.layout in ("chart", "diagram"):  # un visuel ne se juge que sur l'image
            try:
                user["images"] = [self._render(index)]
                user["content"] += "\nImage de la slide jointe."
                self.actions.append({"outil": "voir_slide", "slide": index + 1})
            except PdfExportError:
                pass
        messages = [{"role": "system", "content": SLIDE_SYSTEM}, user]
        for _ in range(2):  # une seconde chance après un rejet
            calls = self._chat(messages, SLIDE_TOOLS).message.tool_calls or []
            if not calls or calls[0].function.name != "reecrire_slide":
                raison = (str(dict(calls[0].function.arguments or {}).get("raison", ""))
                          if calls else "aucun outil appelé")
                self.log(f"Slide {index + 1} : laissée telle quelle ({raison})")
                self.actions.append({"outil": "passer", "slide": index + 1, "raison": raison})
                return
            args = dict(calls[0].function.arguments or {}) | {"numero": index + 1}
            self.log(f"Agent → reecrire_slide({json.dumps(args, ensure_ascii=False)})")
            result = self.reecrire_slide(args)
            rejected = result.startswith(("Nouvelle version REJETÉE", "Refusé : cette consigne"))
            if not rejected or sum(self.rewrites.values()) >= config.AGENT_MAX_REWRITES:
                return
            messages.append({"role": "assistant", "content": "",
                             "tool_calls": [calls[0].model_dump()]})
            messages.append({"role": "tool", "tool_name": "reecrire_slide",
                             "content": result + " Propose une autre consigne, ou passe."})

    def free_loop(self) -> str:
        """Objectif de l'utilisateur : l'agent choisit les slides et les outils."""
        goal = (f"Objectif donné par l'utilisateur : {self.goal}\n"
                "Ne touche qu'aux slides que cet objectif désigne ; s'il cite une slide, "
                "ne modifie que celle-là, puis appelle terminer.\n")
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"{goal}\n{self.overview()}\n\n"
                                                "Appelle un outil."}]
        nudged = False
        for _ in range(config.AGENT_MAX_STEPS):
            message = self._chat(messages).message
            calls = message.tool_calls or []
            if not calls:
                if nudged:  # deux réponses sans outil : on s'arrête
                    return (message.content or "").strip() or "Relecture arrêtée."
                nudged = True
                messages.append({"role": "assistant", "content": message.content or ""})
                messages.append({"role": "user", "content": "Réponds en appelant un outil "
                                 "(voir_slide, reecrire_slide ou terminer)."})
                continue
            nudged = False
            messages.append({"role": "assistant", "content": message.content or "",
                             "tool_calls": [c.model_dump() for c in calls[:1]]})
            call = calls[0]  # un appel à la fois : le résultat peut changer la suite
            name, args = call.function.name, dict(call.function.arguments or {})
            self.log(f"Agent → {name}({json.dumps(args, ensure_ascii=False)})")
            image = None
            try:
                if name == "terminer":
                    return str(args.get("resume", "")).strip() or "Relecture terminée."
                if name == "voir_slide":
                    result, image = self.voir_slide(args)
                    self.actions.append({"outil": name, "slide": args.get("numero")})
                elif name == "reecrire_slide":
                    result = self.reecrire_slide(args)
                else:
                    result = f"Outil inconnu : {name}"
            except ValueError as e:
                result = f"Erreur : {e}"
            messages.append({"role": "tool", "tool_name": name, "content": result})
            if image:  # l'image accompagne un message utilisateur (format Ollama)
                messages.append({"role": "user", "content": f"Slide {args.get('numero')} :",
                                 "images": [image]})
        return "Relecture arrêtée : nombre maximal d'étapes atteint."


def review(run: Run, goal: str = "", pdf: bool = True, log: Log = print,
           model: str | None = None) -> AgentResult:
    """Lance l'agent relecteur sur une génération ; met à jour PPTX, PDF et rapport."""
    model = model or config.AGENT_MODEL
    t = time.perf_counter()
    session = _Session(run, goal.strip(), log, model)
    before = sum(i.score for i in session.issues.values())
    log(f"Agent relecteur ({model}) : {before} point(s) de défaut mesurés")
    try:
        comment = session.loop()
    finally:
        unload(model)
    after = sum(i.score for i in session.issues.values())
    # Résumé factuel calculé par le code : celui du modèle peut exagérer.
    rewrites = [a for a in session.actions if a["outil"] == "reecrire_slide"]
    kept = sorted({a["slide"] for a in rewrites if a["gardee"]})
    rejected = sum(not a["gardee"] for a in rewrites)
    summary = (f"{len(kept)} slide(s) modifiée(s) ({', '.join(map(str, kept))}), "
               f"{rejected} version(s) rejetée(s)" if kept
               else f"aucune slide modifiée ({rejected} version(s) rejetée(s))")
    result = AgentResult(summary, session.actions, before, after,
                         round(time.perf_counter() - t, 1), session.changed)
    run.report["agent"] = {"modele": model, "objectif": goal or None, "resume": summary,
                           "commentaire_agent": comment,
                           "actions": session.actions, "defauts_avant": before,
                           "defauts_apres": after, "secondes": result.seconds}
    if session.changed:
        log("Reconstruction du PPTX" + (" et du PDF…" if pdf else "…"))
        rebuild(run, pdf)
    else:
        save(run)
    log(f"Agent : {summary} — défauts {before} → {after}, {result.seconds:.0f} s")
    log(f"Commentaire de l'agent : {comment}")
    return result
