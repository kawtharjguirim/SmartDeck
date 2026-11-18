"""Fine-tuning, étape 3 : QLoRA du modèle de rédaction (FT-01, FT-02).

À lancer avec le venv d'entraînement :  .venv-ft\\Scripts\\python finetune\\train.py [1.5b|3b]

Réglages du cahier des charges (section 14) : LoRA rang 16, alpha 32, learning rate
2e-4, 3 époques, quantification 4 bits (bitsandbytes). La perte n'est calculée que sur
la réponse du modèle (format prompt / completion), jamais sur le prompt.
La courbe de validation est enregistrée pour détecter le surapprentissage.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(HERE.parent / ".cache" / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import torch  # noqa: E402
from datasets import Dataset  # noqa: E402
from huggingface_hub import snapshot_download  # noqa: E402
from peft import LoraConfig  # noqa: E402
from transformers import AutoTokenizer, BitsAndBytesConfig  # noqa: E402
from trl import SFTConfig, SFTTrainer  # noqa: E402

MODELS = {"1.5b": "Qwen/Qwen2.5-1.5B-Instruct", "3b": "Qwen/Qwen2.5-3B-Instruct"}
MAX_LENGTH = 2048  # les prompts du rédacteur font ~1 300 tokens (extraits compris)


def base_model(size: str) -> Path:
    repo = MODELS[size]
    local = HERE / "models" / repo.split("/")[1]
    if not (local / "config.json").exists():
        snapshot_download(repo, local_dir=local,
                          allow_patterns=["*.json", "*.safetensors", "*.txt", "merges.txt"])
    return local


def load_split(name: str) -> Dataset:
    rows = [json.loads(line) for line in (HERE / "data" / f"{name}.jsonl").open(encoding="utf-8")]
    return Dataset.from_list([{"prompt": r["messages"][:2], "completion": r["messages"][2:]}
                              for r in rows])


def main(size: str) -> None:
    model_dir = base_model(size)
    out = HERE / "out" / f"writer-{size}"
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    train, valid = load_split("train"), load_split("valid")

    lengths = [len(tokenizer.apply_chat_template(r["prompt"] + r["completion"], tokenize=True))
               for r in train]
    print(f"{len(train)} exemples d'entraînement, {len(valid)} de validation ; "
          f"longueur max {max(lengths)} tokens (limite {MAX_LENGTH})", flush=True)

    config = SFTConfig(
        output_dir=str(out),
        num_train_epochs=3,
        learning_rate=2e-4,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        per_device_eval_batch_size=1,
        gradient_checkpointing=True,
        bf16=torch.cuda.is_bf16_supported(),
        fp16=not torch.cuda.is_bf16_supported(),
        max_length=MAX_LENGTH,
        completion_only_loss=True,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        logging_steps=5,
        eval_strategy="steps",
        eval_steps=20,
        save_strategy="steps",
        save_steps=20,
        save_total_limit=2,
        load_best_model_at_end=True,  # garde le meilleur point sur la validation
        metric_for_best_model="eval_loss",
        report_to="none",
        seed=42,
        model_init_kwargs={
            "quantization_config": BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported()
                else torch.float16),
            "torch_dtype": "auto",
            "device_map": {"": 0},
        },
    )
    lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                      "gate_proj", "up_proj", "down_proj"])
    trainer = SFTTrainer(model=str(model_dir), args=config, train_dataset=train,
                         eval_dataset=valid, processing_class=tokenizer, peft_config=lora)
    trainer.train()
    trainer.save_model(str(out / "adapter"))
    (out / "courbes.json").write_text(json.dumps(trainer.state.log_history, indent=2),
                                      encoding="utf-8")
    print(f"Adaptateur : {out / 'adapter'} ; pic mémoire GPU "
          f"{torch.cuda.max_memory_allocated() / 2**30:.2f} Go", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "1.5b")
