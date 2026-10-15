import hashlib
from collections import defaultdict


def _stable_pick(text: str, index: int) -> str:
    sentences = [s.strip() for s in text.replace("?", ".").split(".") if len(s.strip()) > 20]
    if not sentences:
        return text[:160] if text else "Summarize this concept."
    return sentences[index % len(sentences)]


def generate_demo_questions(chunks: list[dict], chapter_title: str, counts: dict) -> list[dict]:
    seen = set()
    out: list[dict] = []
    requested = {"mcq": counts.get("mcq", 10), "short": counts.get("short", 5), "long": counts.get("long", 3)}
    grouped = defaultdict(list)
    for c in chunks:
        grouped[c["page_number"]].append(c["text"])
    texts = [(p, " ".join(t)) for p, t in grouped.items()]
    if not texts:
        return out

    def add_question(q: dict) -> None:
        dedupe_key = hashlib.md5(q["question_text"].encode()).hexdigest()  # noqa: S324
        if dedupe_key not in seen:
            seen.add(dedupe_key)
            out.append(q)

    cursor = 0
    for _ in range(requested["mcq"]):
        page, txt = texts[cursor % len(texts)]
        stem = _stable_pick(txt, cursor)
        add_question(
            {
                "type": "mcq",
                "question_text": f"Which statement best reflects: {stem[:100]}?",
                "options": {
                    "A": stem[:80],
                    "B": "An unrelated interpretation",
                    "C": "A contradictory claim",
                    "D": "Insufficient context statement",
                },
                "correct_answer": "A",
                "explanation": "Option A is grounded in the source chunk.",
                "model_answer": None,
                "keywords": [w for w in stem.split()[:5]],
                "rubric": {"criteria": "Concept alignment", "marks": 1},
                "difficulty": ["Easy", "Medium", "Hard"][cursor % 3],
                "marks": 1,
                "source_page": page,
                "source_chapter": chapter_title,
            }
        )
        cursor += 1

    for q_type, marks in (("short", 3), ("long", 5)):
        for _ in range(requested[q_type]):
            page, txt = texts[cursor % len(texts)]
            stem = _stable_pick(txt, cursor)
            add_question(
                {
                    "type": q_type,
                    "question_text": f"Explain the significance of: {stem[:110]}",
                    "options": None,
                    "correct_answer": None,
                    "explanation": None,
                    "model_answer": f"A strong answer should explain: {stem[:180]}",
                    "keywords": [w.strip('.,') for w in stem.split()[:8]],
                    "rubric": {"accuracy": marks * 0.5, "coverage": marks * 0.3, "clarity": marks * 0.2},
                    "difficulty": ["Easy", "Medium", "Hard"][cursor % 3],
                    "marks": marks,
                    "source_page": page,
                    "source_chapter": chapter_title,
                }
            )
            cursor += 1

    return out
