import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive import build_adaptive_path


MODULES = [
    {
        "id": "module-1",
        "title": "Foundations",
        "topics": [
            {"id": "topic-1", "title": "Processes", "prerequisites": []},
            {"id": "topic-2", "title": "Scheduling", "prerequisites": ["topic-1"]},
        ],
    }
]


def event(event_id: str, student_id: str, topic_id: str, score: int) -> dict:
    return {
        "_id": event_id,
        "userId": student_id,
        "topicId": topic_id,
        "masteryScore": score,
        "evaluationStatus": "complete",
        "activityType": "quiz",
    }


def test_low_evidence_recommends_revision_and_keeps_prerequisite_locked():
    path = build_adaptive_path(MODULES, [event("attempt-1", "student-a", "topic-1", 40)])

    assert path["recommendation"]["topicId"] == "topic-1"
    assert path["items"][0]["status"] == "revision_needed"
    assert path["items"][1]["status"] == "locked"


def test_repeated_strong_evidence_unlocks_next_topic():
    path = build_adaptive_path(
        MODULES,
        [
            event("attempt-1", "student-a", "topic-1", 90),
            event("attempt-2", "student-a", "topic-1", 90),
        ],
    )

    assert path["items"][0]["status"] == "completed"
    assert path["items"][1]["status"] == "available"
    assert path["recommendation"]["topicId"] == "topic-2"


def test_student_paths_are_independent():
    first_student = build_adaptive_path(
        MODULES,
        [event("attempt-a", "student-a", "topic-1", 90), event("attempt-b", "student-a", "topic-1", 90)],
    )
    second_student = build_adaptive_path(
        MODULES,
        [event("attempt-c", "student-b", "topic-1", 40)],
    )

    assert first_student["items"][0]["status"] == "completed"
    assert second_student["items"][0]["status"] == "revision_needed"
    assert first_student["recommendation"]["topicId"] != second_student["recommendation"]["topicId"]
