"""Fine-tuning, étape 4 : fusion de l'adaptateur et import dans Ollama (déploiement).

À lancer avec le venv d'entraînement :  .venv-ft\\Scripts\\python finetune\\export.py [1.5b|3b]

1. Fusion : modèle de base (16 bits, sur CPU) + adaptateur LoRA → safetensors.
2. Ollama importe directement ces safetensors et les quantifie en Q4_K_M
   (équivalent de la conversion GGUF de llama.cpp prévue au cahier des charges).
   Le gabarit de dialogue est celui de Qwen2.5, repris du modèle qwen2.5:3b installé.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(HERE.parent / ".cache" / "huggingface"))

import torch  # noqa: E402
from peft import PeftModel  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

from train import base_model  # noqa: E402

QUANTIZE = {"1.5b": "int8", "3b": "int4"}  # 3B en int8 (≈ 3,3 Go) déborderait de la VRAM


def qwen_template() -> str:
    """Bloc TEMPLATE du Modelfile de qwen2.5:3b (même famille, même format de dialogue)."""
    modelfile = subprocess.run(["ollama", "show", "qwen2.5:3b", "--modelfile"],
                               capture_output=True, text=True, encoding="utf-8").stdout
    start = modelfile.index("TEMPLATE")
    end = modelfile.index('"""', modelfile.index('"""', start) + 3) + 3
    return modelfile[start:end]


def main(size: str, pilot: bool = False) -> None:
    out = HERE / "out" / f"writer-{size}{'-pilote' if pilot else ''}"
    merged = out / "merged"
    tokenizer = AutoTokenizer.from_pretrained(base_model(size))
    model = AutoModelForCausalLM.from_pretrained(base_model(size), dtype=torch.float16,
                                                 device_map={"": "cpu"})
    model = PeftModel.from_pretrained(model, out / "adapter").merge_and_unload()
    model.save_pretrained(merged, safe_serialization=True)
    tokenizer.save_pretrained(merged)

    name = f"smartdeck-writer-{size}{'-pilote' if pilot else ''}"
    (out / "Modelfile").write_text(
        f"FROM {merged.as_posix()}\n{qwen_template()}\n"
        'PARAMETER stop "<|im_end|>"\nPARAMETER stop "<|endoftext|>"\n', encoding="utf-8")
    # Ollama 0.40 : types int4 / int8 (anciennement q4_K_M…). Un 1,5B en int8 ≈ 1,6 Go,
    # entièrement sur le GPU, avec moins de perte de qualité qu'en int4.
    subprocess.run(["ollama", "create", name, "-f", str(out / "Modelfile"),
                    "--quantize", QUANTIZE.get(size, "int4")], check=True)
    print(f"Modèle Ollama créé : {name}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "1.5b", pilot="--pilote" in sys.argv)
