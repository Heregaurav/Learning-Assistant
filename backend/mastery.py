from collections import defaultdict
from typing import Any

MASTERY_THRESHOLDS = {"strong": 80, "developing": 60}
MINIMUM_EVIDENCE = 2
ASSESSMENT_WEIGHTS = {
    "curiosity_quiz": 1.0,
    "assignment": 1.0,
    "quiz": 1.15,
    "test": 1.25,
    "practice": 0.6,
}


def summarize_evidence(events: list[dict[str, Any]]) -> dict[str, Any]:
    unique: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("evaluationStatus") not in {"complete", "faculty_graded"}:
            continue
        score = event.get("masteryScore")
        if not isinstance(score, (int, float)) or not 0 <= score <= 100:
            continue
        evidence_id = str(event.get("_id") or event.get("id") or event.get("sourceSessionId"))
        unique[evidence_id] = event

    weighted_score = 0.0
    total_weight = 0.0
    for event in unique.values():
        weight = ASSESSMENT_WEIGHTS.get(event.get("activityType", ""), 1.0)
        weighted_score += float(event["masteryScore"]) * weight
        total_weight += weight

    if not unique or total_weight == 0:
        return {
            "score": None,
            "state": "unknown",
            "confidence": "insufficient",
            "evidenceCount": 0,
            "evidenceIds": [],
        }

    score = round(weighted_score / total_weight)
    if len(unique) < MINIMUM_EVIDENCE:
        state = "provisional"
        confidence = "low"
    elif score >= MASTERY_THRESHOLDS["strong"]:
        state = "strong"
        confidence = "high"
    elif score >= MASTERY_THRESHOLDS["developing"]:
        state = "developing"
        confidence = "high"
    else:
        state = "needs_improvement"
        confidence = "high"

    return {
        "score": score,
        "state": state,
        "confidence": confidence,
        "evidenceCount": len(unique),
        "evidenceIds": list(unique),
    }


def build_student_progress(
    modules: list[dict[str, Any]], events: list[dict[str, Any]]
) -> dict[str, Any]:
    events_by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("topicId"):
            events_by_topic[str(event["topicId"])].append(event)

    result_modules = []
    topic_summaries = []
    total_topics = 0
    covered_topics = 0
    for module in modules:
        topics = []
        for topic in module.get("topics", []):
            total_topics += 1
            topic_events = events_by_topic.get(str(topic["id"]), [])
            covered = any(event.get("coverage") is True for event in topic_events)
            covered_topics += int(covered)
            mastery = summarize_evidence(topic_events)
            concepts = []
            for concept in topic.get("concepts", []):
                concept_events = [
                    event for event in topic_events
                    if concept.get("name") in event.get("concepts", [])
                ]
                concepts.append({**concept, "mastery": summarize_evidence(concept_events)})
            topic_result = {
                "id": topic["id"],
                "title": topic["title"],
                "coverage": "covered" if covered else "not_started",
                "mastery": mastery,
                "concepts": concepts,
                "evidence": [
                    {
                        "id": event.get("_id") or event.get("id"),
                        "activityType": event.get("activityType"),
                        "evidenceType": event.get("evidenceType"),
                        "masteryScore": event.get("masteryScore"),
                        "occurredAt": event.get("occurredAt"),
                        "evaluationStatus": event.get("evaluationStatus"),
                    }
                    for event in topic_events
                ],
            }
            topics.append(topic_result)
            topic_summaries.append(topic_result)
        result_modules.append(
            {
                "id": module["id"],
                "title": module["title"],
                "topics": topics,
                "mastery": _summary_of_children(topics),
                "coverage": {
                    "covered": sum(topic["coverage"] == "covered" for topic in topics),
                    "total": len(topics),
                },
            }
        )

    known_topics = [topic["mastery"]["score"] for topic in topic_summaries if topic["mastery"]["score"] is not None]
    course_mastery = round(sum(known_topics) / len(known_topics)) if known_topics else None
    recommendations = []
    for topic in topic_summaries:
        if topic["coverage"] != "covered":
            recommendations.append({"kind": "learn", "topicId": topic["id"], "title": f"Learn {topic['title']} with Curiosity"})
        elif topic["mastery"]["state"] == "needs_improvement":
            recommendations.append({"kind": "review", "topicId": topic["id"], "title": f"Review {topic['title']}"})

    return {
        "mastery": {"score": course_mastery, "state": _mastery_state(course_mastery)},
        "coverage": {
            "coveredTopics": covered_topics,
            "totalTopics": total_topics,
            "percent": round(covered_topics / total_topics * 100) if total_topics else 0,
        },
        "modules": result_modules,
        "recommendations": recommendations,
    }


def build_classroom_analytics(
    modules: list[dict[str, Any]],
    student_ids: list[str],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    students = []
    for student_id in student_ids:
        student_events = [event for event in events if event.get("userId") == student_id]
        progress = build_student_progress(modules, student_events)
        students.append({"studentId": student_id, **progress})
    mastery_scores = [
        student["mastery"]["score"] for student in students
        if student["mastery"]["score"] is not None
    ]
    topic_totals: dict[str, list[int]] = defaultdict(list)
    for student in students:
        for module in student["modules"]:
            for topic in module["topics"]:
                score = topic["mastery"]["score"]
                if score is not None:
                    topic_totals[topic["id"]].append(score)
    curriculum_titles = {
        topic["id"]: topic["title"]
        for module in modules
        for topic in module.get("topics", [])
    }
    return {
        "enrolledStudents": len(student_ids),
        "studentsWithEvidence": len(mastery_scores),
        "averageMastery": round(sum(mastery_scores) / len(mastery_scores)) if mastery_scores else None,
        "students": students,
        "topics": [
            {"topicId": topic_id, "title": curriculum_titles.get(topic_id, topic_id), "averageMastery": round(sum(scores) / len(scores)), "evidenceCount": len(scores)}
            for topic_id, scores in topic_totals.items()
        ],
    }


def _summary_of_children(children: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [item["mastery"]["score"] for item in children if item["mastery"]["score"] is not None]
    score = round(sum(scores) / len(scores)) if scores else None
    return {"score": score, "state": _mastery_state(score), "evidenceCount": len(scores)}


def _mastery_state(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= MASTERY_THRESHOLDS["strong"]:
        return "strong"
    if score >= MASTERY_THRESHOLDS["developing"]:
        return "developing"
    return "needs_improvement"
