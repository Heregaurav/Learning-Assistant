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
        "coverage": True,
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


def test_strict_threshold_requires_greater_than_85_percent():
    at_threshold = build_adaptive_path(MODULES, [event("85", "s", "topic-1", 85)])
    above_threshold = build_adaptive_path(MODULES, [event("86", "s", "topic-1", 86)])

    assert at_threshold["items"][0]["status"] == "revision_needed"
    assert above_threshold["items"][0]["status"] == "completed"


def test_high_score_does_not_master_an_unrelated_topic():
    modules = [{"id": "m", "title": "Course", "topics": [
        {"id": "a", "title": "A", "prerequisites": []},
        {"id": "b", "title": "B", "prerequisites": []},
    ]}]
    path = build_adaptive_path(modules, [event("a-1", "s", "a", 100)])

    assert path["items"][0]["status"] == "completed"
    assert path["items"][1]["status"] == "available"


def test_revision_recommendation_is_selected_across_full_curriculum():
    modules = [{"id": "m", "title": "Course", "topics": [
        {"id": "a", "title": "First", "prerequisites": []},
        {"id": "b", "title": "Second", "prerequisites": []},
    ]}]
    tasks = [{"id": "task-b", "topicId": "b", "conceptIds": ["3NF"], "status": "ready"}]
    path = build_adaptive_path(modules, [], tasks)

    assert path["recommendation"]["topicId"] == "b"
    assert path["items"][0]["status"] == "available"
    assert path["items"][1]["status"] == "revision_needed"


def test_one_question_quiz_cannot_award_topic_mastery():
    insufficient = {
        "_id": "short-quiz",
        "topicId": "topic-1",
        "masteryScore": 100,
        "evaluationStatus": "complete",
        "activityType": "curiosity_quiz",
        "coverage": True,
        "total": 1,
    }
    path = build_adaptive_path(MODULES, [insufficient])

    assert path["items"][0]["status"] == "practice"
    assert "sufficient coverage" in path["items"][0]["reason"]


def test_exactly_85_percent_does_not_unlock_dependent_topic():
    modules = [{"id": "m", "title": "Course", "topics": [
        {"id": "a", "title": "First", "prerequisites": []},
        {"id": "b", "title": "Second", "prerequisites": ["a"]},
    ]}]
    path = build_adaptive_path(modules, [event("a-85", "s", "a", 85)])

    assert path["items"][0]["status"] == "revision_needed"
    assert path["items"][1]["status"] == "locked"
