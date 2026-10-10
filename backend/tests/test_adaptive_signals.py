import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive import build_adaptive_path


def test_repeated_question_misses_and_declining_scores_trigger_revision_reason():
    modules = [{"id": "m", "title": "Processes", "topics": [{"id": "t", "title": "States"}]}]
    events = [
        {"_id": "a", "topicId": "t", "masteryScore": 90, "evaluationStatus": "complete", "questionResults": [{"questionId": "q1", "correct": False}]},
        {"_id": "b", "topicId": "t", "masteryScore": 70, "evaluationStatus": "complete", "questionResults": [{"questionId": "q1", "correct": False}]},
    ]
    path = build_adaptive_path(modules, events)
    item = path["items"][0]
    assert item["status"] == "revision_needed"
    assert item["mastery"]["trend"] == "declining"
    assert "missed repeatedly" in item["reason"]
