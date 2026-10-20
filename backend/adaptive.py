from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mastery import summarize_evidence


REVISION_SCORE = 85
ADVANCE_SCORE = 85


def build_adaptive_path(
    modules: list[dict[str, Any]],
    events: Iterable[dict[str, Any]],
    revision_tasks: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Build a path using strict >85% mastery and active revision tasks."""
    event_list = list(events)
    active_tasks = [
        task for task in revision_tasks
        if task.get("status") in {"pending", "ready", "failed", "revision_complete", "generating_retest", "retest_available"}
    ]
    topic_lookup = {
        str(topic["id"]): topic
        for module in modules
        for topic in module.get("topics", [])
    }
    summaries = {
        topic_id: summarize_evidence(
            [
                event for event in event_list
                if str(event.get("topicId")) == topic_id
                and event.get("coverage") is True
                and not (
                    event.get("activityType") == "curiosity_quiz"
                    and int(event.get("total", 0)) < 2
                )
            ]
        )
        for topic_id in topic_lookup
    }

    items: list[dict[str, Any]] = []
    for module in modules:
        for topic in module.get("topics", []):
            topic_id = str(topic["id"])
            topic_events = [event for event in event_list if str(event.get("topicId")) == topic_id]
            mastery = {**summaries[topic_id], **_assessment_signals(topic_events)}
            topic_tasks = [task for task in active_tasks if str(task.get("topicId")) == topic_id]
            has_undercovered_quiz = any(
                event.get("evaluationStatus") in {"complete", "faculty_graded"}
                and (
                    event.get("coverage") is not True
                    or (event.get("activityType") == "curiosity_quiz" and int(event.get("total", 0)) < 2)
                )
                for event in topic_events
            )
            prerequisite_ids = [str(item) for item in topic.get("prerequisites", [])]
            blocked_by = [
                topic_lookup[prerequisite_id].get("title", prerequisite_id)
                for prerequisite_id in prerequisite_ids
                if prerequisite_id in topic_lookup
                and (
                    summaries[prerequisite_id]["score"] is None
                    or summaries[prerequisite_id]["score"] <= ADVANCE_SCORE
                )
            ]
            if blocked_by:
                status = "locked"
                reason = f"Complete {', '.join(blocked_by)} first."
            elif topic_tasks:
                status = "revision_needed"
                reason = _revision_reason(mastery, topic_tasks)
            elif mastery["score"] is None and has_undercovered_quiz:
                status = "practice"
                reason = "Complete an assessment with sufficient coverage before mastery can be measured."
            elif mastery["score"] is None:
                status = "available"
                reason = "Start this topic to build your first evidence."
            elif mastery["score"] <= REVISION_SCORE:
                status = "revision_needed"
                reason = _revision_reason(mastery, topic_tasks)
            elif mastery["trend"] == "declining":
                status = "revision_needed"
                reason = _revision_reason(mastery) if mastery.get("weakQuestionIds") else "Recent quiz performance is declining; revisit the weak questions before progressing."
            elif mastery["score"] <= ADVANCE_SCORE:
                status = "practice"
                reason = "Complete another practice check to confirm understanding."
            else:
                status = "completed"
                reason = "Multiple strong checks show this topic is ready to revisit or extend."
            items.append(
                {
                    "topicId": topic_id,
                    "moduleId": str(module["id"]),
                    "title": topic.get("title", "Untitled topic"),
                    "status": status,
                    "mastery": mastery,
                    "reason": reason,
                    "nextAction": _next_action(status),
                }
            )

    recommendation = next(
        (item for item in items if item["status"] == "revision_needed"),
        None,
    ) or next((item for item in items if item["status"] == "practice"), None)
    if recommendation is None:
        recommendation = next((item for item in items if item["status"] == "available"), None)
    if recommendation is None:
        recommendation = next((item for item in items if item["status"] == "completed"), None)

    completed = sum(item["status"] == "completed" for item in items)
    return {
        "items": items,
        "recommendation": recommendation,
        "progress": {
            "completed": completed,
            "total": len(items),
            "percent": round(completed / len(items) * 100) if items else 0,
        },
        "revisionTasks": active_tasks,
        "curriculumComplete": bool(items) and all(item["status"] == "completed" for item in items),
    }


def _assessment_signals(events: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [
        float(event["masteryScore"])
        for event in events
        if event.get("evaluationStatus") == "complete"
        and isinstance(event.get("masteryScore"), (int, float))
    ]
    recent = scores[-3:]
    trend = "stable"
    if len(recent) >= 2 and recent[-1] > recent[0] + 5:
        trend = "improving"
    elif len(recent) >= 2 and recent[-1] < recent[0] - 5:
        trend = "declining"
    weak_questions = sorted({
        str(result.get("questionId"))
        for event in events
        for result in event.get("questionResults", [])
        if result.get("correct") is False and result.get("questionId")
    })
    return {"trend": trend, "weakQuestionIds": weak_questions}


def revision_task_specs(
    question_results: list[dict[str, Any]], topic: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return task scopes for missed items, using topic-level fallback if unmapped."""
    topic_id = str(topic.get("id") or topic.get("_id"))
    weak_concepts: dict[str, list[str]] = {}
    for result in question_results:
        if result.get("correct") is not False and not result.get("unanswered"):
            continue
        for concept in result.get("concepts", []):
            weak_concepts.setdefault(str(concept), []).append(str(result["questionId"]))
    if weak_concepts:
        return [
            {
                "topicId": topic_id,
                "conceptIds": [concept],
                "weakQuestionIds": sorted(set(question_ids)),
                "mappingStatus": "mapped",
            }
            for concept, question_ids in sorted(weak_concepts.items())
        ]
    if any(result.get("correct") is False or result.get("unanswered") for result in question_results):
        return [{
            "topicId": topic_id,
            "conceptIds": [],
            "weakQuestionIds": [
                str(result["questionId"])
                for result in question_results
                if result.get("correct") is False or result.get("unanswered")
            ],
            "mappingStatus": "insufficient",
        }]
    return []


def _revision_reason(mastery: dict[str, Any], tasks: list[dict[str, Any]] = ()) -> str:
    if tasks:
        return "Targeted revision is active for missed assessment evidence."
    weak_questions = mastery.get("weakQuestionIds", [])
    if weak_questions:
        return f"Review this topic because {len(weak_questions)} quiz question(s) were missed repeatedly."
    return "Recent evidence shows this topic needs targeted revision."


def _next_action(status: str) -> str:
    return {
        "locked": "Review prerequisites",
        "available": "Start lesson",
        "revision_needed": "Review with targeted practice",
        "practice": "Take another practice check",
        "completed": "Extend or revisit",
    }[status]
