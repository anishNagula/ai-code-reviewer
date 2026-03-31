from transformers import RobertaTokenizer, AutoModelForSeq2SeqLM
import torch

tokenizer = RobertaTokenizer.from_pretrained("Salesforce/codet5-small")
model = AutoModelForSeq2SeqLM.from_pretrained("Salesforce/codet5-small")

device = torch.device("cpu")
model = model.to(device)


def generate(prompt):
    print("\n=== PROMPT ===\n", prompt[:200])

    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=512
    ).to(device)

    outputs = model.generate(
        **inputs,
        max_length=200,
        num_beams=5,
        no_repeat_ngram_size=2
    )

    result = tokenizer.decode(outputs[0], skip_special_tokens=True)

    print("\n=== OUTPUT ===\n", result)

    return result
