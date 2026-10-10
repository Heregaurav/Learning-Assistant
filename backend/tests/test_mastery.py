import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mastery import build_classroom_analytics, build_student_progress, summarize_evidence


def test_no_evidence_returns_unknown_without_invented_score():
    summary = summarize_evidence([])
    assert summary["score"] is None
    assert summary["state"] == "unknown"
    assert summary["confidence"] == "insufficient"


def test_repeated_same_evidence_is_not_counted_twice_and_coverage_is_separate():
    module = {
        "id": "module-1",
        "title": "Relational Design",
        "topics": [
            {
                "id": "topic-1",
                "title": "Normalization",
                "concepts": [{"name": "3NF"}],
            },
            {"id": "topic-2", "title": "Transactions", "concepts": []},
        ],
    }
    events = [
        {
            "_id": "event-1",
            "topicId": "topic-1",
            "concepts": ["3NF"],
            "activityType": "quiz",
            "evaluationStatus": "complete",
            "masteryScore": 50,
            "coverage": True,
        },
        {
            "_id": "event-1",
            "topicId": "topic-1",
            "concepts": ["3NF"],
            "activityType": "quiz",
            "evaluationStatus": "complete",
            "masteryScore": 50,
            "coverage": True,
        },
    ]

    progress = build_student_progress([module], events)
    normalization, transactions = progress["modules"][0]["topics"]

    assert normalization["mastery"]["evidenceCount"] == 1
    assert normalization["mastery"]["state"] == "provisional"
    assert normalization["coverage"] == "covered"
    assert transactions["coverage"] == "not_started"
    assert transactions["mastery"]["score"] is None
    assert progress["coverage"] == {"coveredTopics": 1, "totalTopics": 2, "percent": 50}


def test_two_distinct_assessments_enable_high_confidence_mastery():
    events = [
        {"_id": "a", "masteryScore": 80, "evaluationStatus": "complete", "activityType": "quiz"},
        {"_id": "b", "masteryScore": 100, "evaluationStatus": "faculty_graded", "activityType": "assignment"},
    ]
    summary = summarize_evidence(events)
    assert summary["evidenceCount"] == 2
    assert summary["confidence"] == "high"
    assert summary["state"] == "strong"


def test_faculty_analytics_uses_persisted_student_events():
    modules = [{"id": "m", "title": "M", "topics": [{"id": "t", "title": "T", "concepts": []}]}]
    events = [
        {"userId": "s1", "topicId": "t", "_id": "e1", "masteryScore": 90, "evaluationStatus": "complete", "activityType": "quiz", "coverage": True},
        {"userId": "s1", "topicId": "t", "_id": "e2", "masteryScore": 90, "evaluationStatus": "complete", "activityType": "quiz", "coverage": True},
    ]
    result = build_classroom_analytics(modules, ["s1", "s2"], events)
    assert result["enrolledStudents"] == 2
    assert result["studentsWithEvidence"] == 1
    assert result["averageMastery"] == 90
    assert len(result["topics"]) == 1
