from collections import Counter
from math import sqrt


def _vec(text: str) -> Counter:
    return Counter(w.lower().strip('.,!?') for w in text.split() if len(w) > 2)


def _cos(a: Counter, b: Counter) -> float:
    common = set(a) & set(b)
    num = sum(a[k] * b[k] for k in common)
    da = sqrt(sum(v * v for v in a.values())) or 1
    db = sqrt(sum(v * v for v in b.values())) or 1
    return num / (da * db)


def answer_from_chunks(question: str, chunks: list[dict]) -> tuple[str, list[dict]]:
    qv = _vec(question)
    ranked = sorted(chunks, key=lambda c: _cos(qv, _vec(c["text"])), reverse=True)[:3]
    evidence = [c for c in ranked if c["text"].strip()]
    if not evidence:
        return (
            "I could not find this answer in the selected book content. "
            "Please upload a clearer PDF or ask about another section.",
            [],
        )
    summary = " ".join(c["text"][:220] for c in evidence)
    reply = (
        "From source material: "
        + summary
        + "\nAdditional explanation: Focus on the key definitions and examples above."
    )
    return reply, [{"page": e["page_number"], "chapter": e.get("chapter", "General Content")} for e in evidence]
