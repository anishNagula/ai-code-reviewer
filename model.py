from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch

MODEL_NAME = "google/flan-t5-base"

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)

device = torch.device("cpu")
model = model.to(device)


def generate(prompt):
    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=512
    ).to(device)

    outputs = model.generate(
        **inputs,
        max_length=256,
        temperature=0.3,   # 🔥 lower = more stable
        do_sample=True
    )

    result = tokenizer.decode(outputs[0], skip_special_tokens=True)
    return result.strip()
