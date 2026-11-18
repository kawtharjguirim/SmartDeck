"""Vérifie que le modèle de base se charge en 4 bits sur le GPU et répond (avant l'entraînement).

Usage : .venv-ft\\Scripts\\python finetune\\check_gpu.py [1.5b|3b]
"""
import sys
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from train import base_model

size = sys.argv[1] if len(sys.argv) > 1 else "1.5b"
path = base_model(size)  # télécharge le modèle s'il est absent
tokenizer = AutoTokenizer.from_pretrained(path)
model = AutoModelForCausalLM.from_pretrained(
    path, device_map={"": 0},
    quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                           bnb_4bit_compute_dtype=torch.bfloat16))
messages = [{"role": "user", "content": "Donne en une phrase l'intérêt d'une présentation."}]
inputs = tokenizer.apply_chat_template(messages, add_generation_prompt=True,
                                       return_tensors="pt", return_dict=True).to(0)
t = time.perf_counter()
output = model.generate(**inputs, max_new_tokens=40, do_sample=False)
print(tokenizer.decode(output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True))
print(f"{size} en 4 bits : {torch.cuda.max_memory_allocated() / 2**30:.2f} Go de VRAM, "
      f"{time.perf_counter() - t:.1f} s pour 40 tokens")
