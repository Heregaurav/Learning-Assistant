from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mastery import summarize_evidence


REVISION_SCORE = 60
ADVANCE_SCORE = 80


def build_adaptive_path(
    modules: list[dict[str, Any]], events: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Build a deterministic student path from curriculum and learning evidence."""
    event_list = list(events)
    topic_lookup = {
        str(topic["id"]): topic
        for module in modules
        for topic in module.get("topics", [])
    }
    summaries = {
        topic_id: summarize_evidence(
            [event for event in event_list if str(event.get("topicId")) == topic_id]
        )
        for topic_id in topic_lookup
    }

    items: list[dict[str, Any]] = []
    for module in modules:
        for topic in module.get("topics", []):
            topic_id = str(topic["id"])
            topic_events = [event for event in event_list if str(event.get("topicId")) == topic_id]
            mastery = {**summaries[topic_id], **_assessment_signals(topic_events)}
            prerequisite_ids = [str(item) for item in topic.get("prerequisites", [])]
            blocked_by = [
                topic_lookup[prerequisite_id].get("title", prerequisite_id)
                for prerequisite_id in prerequisite_ids
                if prerequisite_id in topic_lookup
                and (
                    summaries[prerequisite_id]["score"] is None
                    or summaries[prerequisite_id]["score"] < ADVANCE_SCORE
                )
            ]
            if blocked_by:
                status = "locked"
                reason = f"Complete {', '.join(blocked_by)} first."
            elif mastery["score"] is None:
                status = "available"
                reason = "Start this topic to build your first evidence."
            elif mastery["score"] < REVISION_SCORE:
                status = "revision_needed"
                reason = _revision_reason(mastery)
            elif mastery["trend"] == "declining":
                status = "revision_needed"
                reason = _revision_reason(mastery) if mastery.get("weakQuestionIds") else "Recent quiz performance is declining; revisit the weak questions before progressing."
            elif mastery["score"] < ADVANCE_SCORE or mastery["evidenceCount"] < 2:
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


def _revision_reason(mastery: dict[str, Any]) -> str:
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
