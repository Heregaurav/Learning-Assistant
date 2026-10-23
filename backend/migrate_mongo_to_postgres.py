"""Read-only MongoDB export into PostgreSQL. Re-running is safe and idempotent."""

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from pymongo import MongoClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database import session_scope
from orm_models import (
    AdaptiveTask,
    AuthSession,
    Classroom,
    ClassroomAssessment,
    ClassroomMember,
    ClassroomPost,
    ClassroomReply,
    ClassroomSubmission,
    CurriculumModule,
    CurriculumTopic,
    LearningEvent,
    LearningPath,
    LearningSession,
    Topic,
    TopicSession,
    User,
)
from persistence import COLLECTION_MODELS, _parse_datetime, _prepare_doc, _sync_relations


ORDER = (
    "users",
    "topics",
    "classrooms",
    "classroom_modules",
    "classroom_curriculum_topics",
    "classroom_assessments",
    "classroom_posts",
    "classroom_replies",
    "classroom_submissions",
    "sessions",
    "learning_events",
    "learning_paths",
    "adaptive_tasks",
)


def normalize_bson(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {str(key): normalize_bson(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_bson(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_bson(item) for item in value]
    return value


def session_model(document: dict[str, Any]):
    return AuthSession if "user_id" in document and "userId" not in document else LearningSession


def model_for(collection_name: str, document: dict[str, Any]):
    if collection_name == "sessions":
        return session_model(document)
    return COLLECTION_MODELS[collection_name]


def document_key(document: dict[str, Any]) -> str:
    return str(document.get("_id", document.get("id", "")))


def report_record(report, kind: str, collection: str, identity: str, message: str):
    report[kind].append({"collection": collection, "id": identity, "reason": message})


def import_documents(mongo_db, *, dry_run: bool, batch_size: int, report):
    imported_counts = defaultdict(int)
    source_counts = {}
    if dry_run:
        for name in ORDER:
            source_counts[name] = mongo_db[name].count_documents({})
        report["sourceCounts"] = source_counts
        report["dryRun"] = True
        return imported_counts

    for collection_name in ORDER:
        source = mongo_db[collection_name]
        source_counts[collection_name] = source.count_documents({})
        batch = []
        for document in source.find({}).batch_size(batch_size):
            normalized = normalize_bson(document)
            if not normalized.get("_id"):
                report_record(report, "invalid", collection_name, "<missing>", "Document has no _id.")
                continue
            if collection_name == "sessions":
                model = session_model(normalized)
            else:
                model = COLLECTION_MODELS[collection_name]
            batch.append((normalized, model))
            if len(batch) >= batch_size:
                import_batch(collection_name, batch, imported_counts, report)
                batch.clear()
        if batch:
            import_batch(collection_name, batch, imported_counts, report)

    reconcile_topic_relations(mongo_db, report)
    reconcile_personal_topic_sessions(mongo_db, report)
    report["sourceCounts"] = source_counts
    report["postgresCounts"] = postgres_counts()
    report["importedCounts"] = dict(imported_counts)
    report["relationshipIntegrity"] = relationship_integrity()
    report["countValidation"] = {
        name: {"source": count, "postgres": report["postgresCounts"].get(name, 0), "matches": count == report["postgresCounts"].get(name, 0)}
        for name, count in source_counts.items()
    }
    report["dryRun"] = False
    return imported_counts


def import_batch(collection_name, batch, imported_counts, report):
    from sqlalchemy.dialects.postgresql import insert

    with session_scope() as session:
        for document, model in batch:
            identity = document_key(document)
            known_fields = {"_id", "id", "members", "sessionIds", "prerequisites"}
            known_fields |= {column.key for column in model.__table__.columns}
            unknown = sorted(set(document) - known_fields)
            if unknown:
                report_record(report, "unsupportedFields", collection_name, identity, ", ".join(unknown))
            try:
                with session.begin_nested():
                    if model is AuthSession:
                        values = {
                            "id": identity,
                            "user_id": str(document.get("user_id", "")),
                            "created_at": _parse_datetime(document.get("created_at")),
                            "expires_at": _parse_datetime(document.get("expires_at")),
                            "csrf_token_hash": document.get("csrf_token_hash", ""),
                        }
                        session.execute(insert(AuthSession).values(**values).on_conflict_do_update(
                            index_elements=[AuthSession.id], set_={key: value for key, value in values.items() if key != "id"}
                        ))
                    else:
                        prepared = _prepare_doc(model, document)
                        if model is Topic:
                            prepared.pop("sessionIds", None)
                        statement = insert(model).values(**prepared)
                        update_values = {key: value for key, value in prepared.items() if key != "id"}
                        session.execute(statement.on_conflict_do_update(index_elements=[model.id], set_=update_values))
                        session.flush()
                        if model in {Classroom, CurriculumTopic}:
                            _sync_relations(model, identity, document, session)
                imported_counts[collection_name] += 1
            except IntegrityError as exc:
                report_record(report, "orphaned" if "foreign key" in str(exc).lower() else "duplicate", collection_name, identity, str(exc.orig)[:300])
            except (TypeError, ValueError, SQLAlchemyError) as exc:
                report_record(report, "invalid", collection_name, identity, str(exc)[:300])


def reconcile_topic_relations(mongo_db, report):
    topic_keys = {
        (str(document.get("classroomId", "")), document_key(normalize_bson(document)))
        for document in mongo_db["classroom_curriculum_topics"].find({}, {"_id": 1, "classroomId": 1})
    }
    for document in mongo_db["classroom_curriculum_topics"].find({}, {"_id": 1, "classroomId": 1, "prerequisites": 1}):
        normalized = normalize_bson(document)
        identity = document_key(normalized)
        prerequisites = normalized.get("prerequisites", [])
        if prerequisites:
            for prerequisite_id in prerequisites:
                if (str(normalized.get("classroomId", "")), str(prerequisite_id)) not in topic_keys:
                    report_record(
                        report,
                        "orphaned",
                        "classroom_curriculum_topics",
                        identity,
                        f"prerequisites references missing same-classroom topic {prerequisite_id}; raw value was retained",
                    )
        with session_scope() as session:
            topic = session.get(CurriculumTopic, identity)
            if topic is None:
                continue
            try:
                _sync_relations(CurriculumTopic, identity, normalized, session)
            except IntegrityError as exc:
                report_record(report, "orphaned", "classroom_curriculum_topics", identity, str(exc.orig)[:300])


def reconcile_personal_topic_sessions(mongo_db, report):
    for document in mongo_db["topics"].find({}, {"_id": 1, "sessionIds": 1}):
        normalized = normalize_bson(document)
        topic_id = document_key(normalized)
        with session_scope() as session:
            if session.get(Topic, topic_id) is None:
                continue
            for session_id in normalized.get("sessionIds", []):
                if session.get(LearningSession, str(session_id)) is None:
                    report_record(report, "orphaned", "topics", topic_id, f"sessionIds references missing learning session {session_id}")
                    continue
                session.merge(TopicSession(
                    topicId=topic_id,
                    sessionId=str(session_id),
                    userId=normalized["userId"],
                ))


def postgres_counts() -> dict[str, int]:
    models = {
        "users": User,
        "topics": Topic,
        "classrooms": Classroom,
        "classroom_modules": CurriculumModule,
        "classroom_curriculum_topics": CurriculumTopic,
        "classroom_assessments": ClassroomAssessment,
        "classroom_submissions": ClassroomSubmission,
        "classroom_posts": ClassroomPost,
        "classroom_replies": ClassroomReply,
        "learning_events": LearningEvent,
        "learning_paths": LearningPath,
        "adaptive_tasks": AdaptiveTask,
    }
    from database import current_session

    session = current_session()
    counts = {name: session.scalar(select(func.count()).select_from(model)) or 0 for name, model in models.items()}
    counts["sessions"] = (session.scalar(select(func.count()).select_from(AuthSession)) or 0) + (session.scalar(select(func.count()).select_from(LearningSession)) or 0)
    return counts


def relationship_integrity() -> dict[str, int]:
    from sqlalchemy import and_, exists
    from database import current_session

    session = current_session()
    checks = {
        "sessions_without_users": select(func.count()).select_from(LearningSession).where(~exists(select(User.id).where(User.id == LearningSession.userId))),
        "members_without_users": select(func.count()).select_from(ClassroomMember).where(~exists(select(User.id).where(User.id == ClassroomMember.userId))),
        "topics_without_modules": select(func.count()).select_from(CurriculumTopic).where(~exists(select(CurriculumModule.id).where(and_(CurriculumModule.id == CurriculumTopic.moduleId, CurriculumModule.classroomId == CurriculumTopic.classroomId)))),
        "submissions_without_assessments": select(func.count()).select_from(ClassroomSubmission).where(~exists(select(ClassroomAssessment.id).where(and_(ClassroomAssessment.id == ClassroomSubmission.assessmentId, ClassroomAssessment.classroomId == ClassroomSubmission.classroomId)))),
    }
    return {name: session.scalar(statement) or 0 for name, statement in checks.items()}


def main():
    parser = argparse.ArgumentParser(description="Read MongoDB documents into PostgreSQL without modifying MongoDB.")
    parser.add_argument("--dry-run", action="store_true", help="Report MongoDB source counts without writing to PostgreSQL.")
    parser.add_argument("--batch-size", type=int, default=500, help="Documents per transaction batch; must be 1..5000.")
    parser.add_argument("--report", default="migration-report.json", help="Path for the JSON validation report.")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 5000:
        parser.error("--batch-size must be between 1 and 5000")
    mongo_url = os.getenv("MONGODB_URI")
    database_name = os.getenv("MONGODB_DATABASE", "learningAssistant")
    if not mongo_url:
        parser.error("Set MONGODB_URI to the source MongoDB connection string.")
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    mongo_db = client[database_name]
    report = {"invalid": [], "duplicate": [], "orphaned": [], "unsupportedFields": [], "startedAt": datetime.now().astimezone().isoformat()}
    try:
        import_documents(mongo_db, dry_run=args.dry_run, batch_size=args.batch_size, report=report)
    finally:
        client.close()
    report["finishedAt"] = datetime.now().astimezone().isoformat()
    Path(args.report).write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    failures = bool(report["invalid"] or report["duplicate"] or report["orphaned"] or report["unsupportedFields"])
    failures = failures or any(report.get("relationshipIntegrity", {}).values())
    count_mismatch = any(not item["matches"] for item in report.get("countValidation", {}).values())
    raise SystemExit(2 if failures or count_mismatch else 0)


if __name__ == "__main__":
    main()