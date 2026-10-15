from dataclasses import dataclass
from app.core.config import get_settings


@dataclass
class AIResult:
    content: str
    provider: str
    demo_mode: bool


class AIProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    def mode(self) -> str:
        return self.settings.ai_provider if self.settings.ai_provider in {"demo", "openai", "ollama"} else "demo"

    def demo_enabled(self) -> bool:
        provider = self.mode()
        if provider == "openai" and self.settings.openai_api_key:
            return False
        return provider != "openai"

    def evaluate_answer(self, question: str, model_answer: str, student_answer: str, max_marks: float) -> AIResult:
        # deterministic fallback/local mode
        expected_words = {w.lower().strip('.,') for w in model_answer.split() if len(w) > 4}
        student_words = {w.lower().strip('.,') for w in student_answer.split()}
        hit = len(expected_words.intersection(student_words))
        coverage = hit / max(len(expected_words), 1)
        mark = round(max_marks * min(1.0, coverage + 0.15), 2)
        feedback = (
            f"Estimated-AI-Mark: {mark}/{max_marks}. "
            f"Matched {hit} key concepts. Improve by covering: "
            f"{', '.join(sorted(list(expected_words - student_words)[:6])) or 'more detailed explanations'}."
        )
        return AIResult(content=feedback, provider=self.mode(), demo_mode=self.demo_enabled())


ai_provider = AIProvider()
