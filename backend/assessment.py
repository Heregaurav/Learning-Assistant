from __future__ import annotations

from typing import Any


class AssessmentValidationError(ValueError):
    pass


def grade_quiz(
    quiz: list[dict[str, Any]],
    answers: dict[str, str],
    allowed_concepts: set[str] | None = None,
) -> dict[str, Any]:
    """Grade a stored quiz answer key and retain only trusted concept mappings."""
    if not isinstance(quiz, list) or not quiz:
        raise AssessmentValidationError("This session has no gradeable quiz.")
    question_ids: set[str] = set()
    results = []
    concept_totals: dict[str, dict[str, int]] = {}
    correct = 0
    for question in quiz:
        if not isinstance(question, dict):
            raise AssessmentValidationError("The saved quiz contains an invalid question.")
        question_id = question.get("id")
        options = question.get("options")
        answer_key = question.get("correctAnswer")
        if (
            not isinstance(question_id, str)
            or not question_id
            or question_id in question_ids
            or not isinstance(options, list)
            or len(options) < 2
            or not isinstance(answer_key, str)
            or answer_key not in options
        ):
            raise AssessmentValidationError("The saved quiz answer key is invalid.")
        question_ids.add(question_id)
        submitted = answers.get(question_id)
        if submitted is not None and submitted not in options:
            raise AssessmentValidationError("An answer is not one of the saved question options.")
        is_correct = submitted is not None and submitted == answer_key
        correct += int(is_correct)
        raw_concepts = question.get("conceptIds", [])
        mapped_concepts = sorted({
            str(concept)
            for concept in raw_concepts
            if isinstance(concept, str)
            and concept
            and (allowed_concepts is None or concept in allowed_concepts)
        }) if isinstance(raw_concepts, list) else []
        for concept in mapped_concepts:
            totals = concept_totals.setdefault(concept, {"correct": 0, "incorrect": 0, "unanswered": 0})
            totals["correct" if is_correct else "unanswered" if submitted is None else "incorrect"] += 1
        results.append({
            "questionId": question_id,
            "correct": is_correct if submitted is not None else None,
            "unanswered": submitted is None,
            "concepts": mapped_concepts,
        })
    unknown_questions = set(answers) - question_ids
    if unknown_questions:
        raise AssessmentValidationError("Answers contain unknown question IDs.")
    total = len(quiz)
    return {
        "correct": correct,
        "incorrect": total - correct,
        "unanswered": sum(result["unanswered"] for result in results),
        "total": total,
        "score": round(correct / total * 100),
        "questionResults": results,
        "conceptResults": {
            concept: {
                **counts,
                "total": sum(counts.values()),
                "score": round(counts["correct"] / sum(counts.values()) * 100),
            }
            for concept, counts in concept_totals.items()
        },
    }