import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evaluation
from llm import LLMError


def test_evaluation_schema_rejects_scores_above_max_and_unknown_concepts():
    valid = {
        "score": 8,
        "conceptScores": {"3NF": 75},
        "strengths": ["Explained dependency"],
        "misconceptions": [],
        "feedback": "Mostly correct.",
        "recommendedTopics": ["Normalization"],
    }
    assert evaluation.validate_answer_evaluation(valid, 10, ["3NF"])["score"] == 8

    with pytest.raises(LLMError):
        evaluation.validate_answer_evaluation({**valid, "score": 11}, 10, ["3NF"])
    with pytest.raises(LLMError):
        evaluation.validate_answer_evaluation({**valid, "conceptScores": {"SQL injection": 99}}, 10, ["3NF"])


def test_written_evaluator_uses_existing_provider_and_validates_json(monkeypatch):
    class Completion:
        choices = [type("Choice", (), {"message": type("Message", (), {"content": '{"score": 7, "conceptScores": {"3NF": 70}, "strengths": [], "misconceptions": [], "feedback": "Good start.", "recommendedTopics": []}'})()})()]

    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return Completion()

    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    monkeypatch.setattr(evaluation, "client", lambda provider: fake_client)

    result = evaluation.evaluate_written_answer(
        question="Explain 3NF",
        answer="A relation is in 3NF when...",
        rubric="Explain transitive dependencies",
        expected_answer="No non-key attribute depends transitively on a key",
        max_marks=10,
        expected_concepts=["3NF"],
        course_context="Teacher notes on normalization",
    )

    assert result["score"] == 7
    assert captured["model"] == "qwen/qwen3.8-27b"
    assert "studentAnswer" in captured["messages"][1]["content"]
