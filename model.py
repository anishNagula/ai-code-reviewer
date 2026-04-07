"""
model.py — Model loader for the AI Code Reviewer pipeline.

Architecture decision
─────────────────────
The summariser uses PURE AST analysis (in agents.py / summariser_agent).
Reason: every code-to-text seq2seq model small enough to run on CPU
(codet5p-220m, codet5-base, flan-t5-base) either echoes the prompt,
hallucinates, or produces incoherent output for anything beyond trivial
single-function snippets. AST metadata + heuristic templates are 100%
reliable and produce better output than any of these models.

The IMPROVER uses Salesforce/codet5p-220m in code-infilling mode.
220M is the sweet spot: fast on CPU, trained on code, seq2seq so it
generates a complete output rather than appending.
"""

from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch

device = torch.device("cpu")

IMPROVER_MODEL = "Salesforce/codet5p-220m"
_imp_tokenizer = None
_imp_model = None


def _load_improver():
    global _imp_tokenizer, _imp_model
    if _imp_model is None:
        print("[model] Loading improver: codet5p-220m ...")
        _imp_tokenizer = AutoTokenizer.from_pretrained(IMPROVER_MODEL)
        _imp_model = (
            AutoModelForSeq2SeqLM.from_pretrained(IMPROVER_MODEL)
            .to(device)
        )
        _imp_model.eval()
        print("[model] Improver ready.")
    return _imp_tokenizer, _imp_model


def generate_improvement(code: str, issue_summary: str) -> str:
    """
    Ask the model to rewrite `code` fixing `issue_summary`.
    Returns raw decoded text; caller validates before use.
    """
    tokenizer, model = _load_improver()

    prompt = (
        "Fix the following Python code.\n"
        f"Issues: {issue_summary}\n"
        "Return only the fixed Python code with no explanation.\n"
        f"Code:\n{code}"
    )

    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=512,
    ).to(device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=300,
            num_beams=4,
            early_stopping=True,
            no_repeat_ngram_size=3,
        )

    return tokenizer.decode(outputs[0], skip_special_tokens=True).strip()
