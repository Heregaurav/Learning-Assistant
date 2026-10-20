import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assessment import AssessmentValidationError, grade_quiz


def sample_quiz():
    return [
        {"id": "q1", "options": ["A", "B"], "correctAnswer": "A", "conceptIds": ["3NF"]},
        {"id": "q2", "options": ["A", "B"], "correctAnswer": "B", "conceptIds": ["3NF"]},
        {"id": "q3", "options": ["A", "B"], "correctAnswer": "A", "conceptIds": ["BCNF"]},
    ]


def test_grade_quiz_counts_correct_incorrect_and_unanswered_from_key():
    result = grade_quiz(sample_quiz(), {"q1": "A", "q2": "A"}, {"3NF", "BCNF"})

    assert result["score"] == 33
    assert (result["correct"], result["incorrect"], result["unanswered"], result["total"]) == (1, 2, 1, 3)
    assert result["conceptResults"]["3NF"] == {
        "correct": 1, "incorrect": 1, "unanswered": 0, "total": 2, "score": 50,
    }


def test_unknown_concept_tags_are_not_trusted():
    result = grade_quiz(sample_quiz(), {"q1": "A"}, {"BCNF"})

    assert result["questionResults"][0]["concepts"] == []
    assert "3NF" not in result["conceptResults"]
    assert result["questionResults"][2]["concepts"] == ["BCNF"]


def test_unknown_question_ids_and_invalid_options_are_rejected():
    with pytest.raises(AssessmentValidationError, match="unknown question IDs"):
        grade_quiz(sample_quiz(), {"not-a-question": "A"})
    with pytest.raises(AssessmentValidationError, match="not one of"):
        grade_quiz(sample_quiz(), {"q1": "not-an-option"})


def test_malformed_or_empty_saved_quiz_is_not_gradeable():
    with pytest.raises(AssessmentValidationError, match="no gradeable quiz"):
        grade_quiz([], {})
    with pytest.raises(AssessmentValidationError, match="answer key is invalid"):
        grade_quiz([{"id": "q1", "options": ["A", "B"], "correctAnswer": "C"}], {})
