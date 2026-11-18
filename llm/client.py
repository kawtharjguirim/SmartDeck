"""Appels à Ollama avec sortie JSON contrainte et validée par Pydantic.

Principe (CDC, section 7) : le LLM ne produit que du JSON. On donne le schéma
Pydantic à Ollama (`format=`), puis on valide la réponse. En cas d'échec, on
relance en renvoyant l'erreur au modèle pour qu'il se corrige.
"""
from typing import Optional, TypeVar

import ollama
from pydantic import BaseModel, ValidationError

import config

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Le modèle n'a pas produit de JSON valide après toutes les tentatives."""


_client = ollama.Client(host=config.OLLAMA_HOST)

# Fine-tuning (section 14) : si défini, appelé après chaque réponse avec
# (modèle, messages envoyés, schéma, réponse brute). Sert à constituer le jeu
# d'entraînement avec exactement les prompts de production.
RECORDER = None

TRUNCATED = ("Ta réponse était trop longue et a été coupée. "
             "Recommence en JSON, avec des textes courts.")


def strict_schema(schema: type[BaseModel]) -> dict:
    """Schéma JSON où les champs non nullables sont obligatoires.

    Pydantic rend facultatifs les champs qui ont une valeur par défaut
    (bullets, notes…). Un petit modèle les omet alors. On les rend
    obligatoires, sauf les champs nullables (chart, diagram_dot) : les forcer
    pousse le modèle à inventer des objets, voire à boucler.
    """
    js = schema.model_json_schema()

    def nullable(prop: dict) -> bool:
        return any(o.get("type") == "null" for o in prop.get("anyOf", []))

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = [
                    k for k, p in node["properties"].items() if not nullable(p)
                ]
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(js)
    return js


def _options(max_tokens: Optional[int] = None) -> dict:
    return {
        "temperature": config.TEMPERATURE,
        "seed": config.SEED,
        "num_ctx": config.NUM_CTX,
        "num_predict": max_tokens or config.MAX_OUTPUT_TOKENS,  # évite les boucles infinies
    }


def generate_structured(
    prompt: str,
    schema: type[T],
    system: Optional[str] = None,
    model: Optional[str] = None,
    retries: int = config.LLM_RETRIES,
    images: Optional[list[bytes]] = None,
    max_tokens: Optional[int] = None,
) -> T:
    """Envoie `prompt` (et d'éventuelles images) au modèle ; renvoie un objet `schema` validé."""
    model = model or config.TEXT_MODEL
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    user = {"role": "user", "content": prompt}
    if images:  # modèle vision : images jointes au message (PNG/JPEG en octets)
        user["images"] = images
    messages.append(user)

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = _client.chat(
                model=model,
                messages=messages,
                format=strict_schema(schema),
                options=_options(max_tokens),
            )
        except ConnectionError as e:
            raise LLMError(
                f"Ollama injoignable sur {config.OLLAMA_HOST} : lancez l'application Ollama."
            ) from e
        except ollama.ResponseError as e:
            raise LLMError(f"Erreur Ollama : {e.error}") from e

        raw = response.message.content
        if RECORDER is not None:
            RECORDER(model, [dict(m) for m in messages], schema, raw)
        if response.done_reason == "length":
            # Réponse coupée (le modèle a bouclé) : ne pas la renvoyer au modèle,
            # elle remplirait le contexte. On redemande simplement plus court.
            last_error = LLMError(f"réponse coupée à {response.eval_count} tokens")
            retry = {"role": "user", "content": TRUNCATED}
            if messages[-1] != retry:
                messages.append(retry)
            continue
        try:
            return schema.model_validate_json(raw)
        except ValidationError as e:
            last_error = e
            # On montre au modèle sa réponse et l'erreur, puis on relance.
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": (
                    "Ta réponse ne respecte pas le schéma. Erreurs :\n"
                    f"{e}\nCorrige et renvoie uniquement le JSON complet."
                ),
            })

    raise LLMError(
        f"JSON invalide après {retries + 1} tentatives : {last_error}"
    )


def generate_text(prompt: str, system: Optional[str] = None,
                  model: Optional[str] = None) -> str:
    """Appel libre (sans schéma), pour les cas simples."""
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": prompt})
    response = _client.chat(model=model or config.TEXT_MODEL,
                            messages=messages, options=_options())
    return response.message.content


def missing_models(models: list[str]) -> list[str]:
    """Modèles absents d'Ollama. LLMError si Ollama ne répond pas (application non lancée)."""
    try:
        installed = {m.model for m in _client.list().models}
    except Exception as e:
        raise LLMError(f"Ollama injoignable sur {config.OLLAMA_HOST} : lancez l'application Ollama.") from e
    return [m for m in models if m not in installed and f"{m}:latest" not in installed]


def unload(model: str) -> None:
    """Libère un modèle de la VRAM (ex. le modèle vision avant la rédaction)."""
    _client.generate(model=model, prompt="", keep_alive=0)
