import copy
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import load_only

from database import current_session, ping
from orm_models import (
    AdaptiveTask,
    AuthSession,
    Classroom,
    ClassroomAssessment,
    ClassroomLecture,
    ClassroomLectureProgress,
    ClassroomMaterial,
    ClassroomMember,
    ClassroomPost,
    ClassroomReply,
    ClassroomSubmission,
    ConceptPrerequisite,
    CurriculumModule,
    CurriculumTopic,
    LearningEvent,
    LearningPath,
    LearningSession,
    Topic,
    TopicSession,
    TopicPrerequisite,
    User,
)


logger = logging.getLogger(__name__)


COLLECTION_MODELS = {
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
    "classroom_materials": ClassroomMaterial,
    "classroom_lectures": ClassroomLecture,
    "classroom_lecture_progress": ClassroomLectureProgress,
}

JSON_FIELDS = {
    User: {"stats", "keyConcepts", "progress"},
    Topic: {"keyConcepts", "progress"},
    LearningSession: {"input", "learningContent", "evaluation", "answers", "questionResults", "conceptResults", "concepts", "document"},
    Classroom: {"facultyIds"},
    CurriculumTopic: {"learningObjectives", "prerequisiteRefs", "concepts", "materials"},
    ClassroomAssessment: {"conceptIds"},
    ClassroomSubmission: {"aiEvaluation"},
    LearningEvent: {"concepts", "conceptResults", "questionResults"},
    LearningPath: {"path"},
    AdaptiveTask: {"conceptIds", "weakQuestionIds", "weakQuestionTexts", "revisionContent", "attemptHistory"},
}

DATE_FIELDS = {
    "createdAt", "updatedAt", "completedAt", "firstStudied", "lastStudied", "joinedAt",
    "dueAt", "submittedAt", "gradedAt", "aiEvaluatedAt", "occurredAt", "masteredAt",
    "revisionCompletedAt", "generationStartedAt", "retestGenerationStartedAt", "orchestratedAt",
    "deleteUntil", "created_at", "expires_at",
}


def _model_for_session(query: dict[str, Any]):
    if any(key in query for key in ("userId", "classroomId", "topicId", "adaptiveTaskId", "evaluation.completed")):
        return LearningSession
    return AuthSession


def _model_fields(model) -> set[str]:
    return {attribute.key for attribute in inspect(model).column_attrs}


def _field_name(model, key: str) -> str | None:
    if key == "_id":
        return "id"
    if key in _model_fields(model):
        return key
    if model is Topic and key == "sessionIds":
        return key
    if model is Classroom and key in {"members", "memberCount"}:
        return key
    if model is CurriculumTopic and key == "prerequisites":
        return key
    if model is AuthSession and key == "_id":
        return "id"
    return None


def _json_path(column, path: list[str]):
    value = column
    for part in path:
        value = value[part]
    return value


def _expression(model, key: str):
    if model is Topic and key == "sessionIds":
        return None
    if model is Classroom and key in {"members", "memberCount"}:
        return None
    if model is CurriculumTopic and key == "prerequisites":
        return None
    parts = key.split(".")
    attribute = _field_name(model, parts[0])
    if attribute is None:
        return None
    column = getattr(model, attribute)
    if len(parts) == 1:
        return column
    if parts[0] not in JSON_FIELDS.get(model, set()):
        return None
    return _json_path(column, parts[1:])


def _typed_json_value(expression, value):
    if isinstance(value, bool):
        return expression.as_boolean()
    if isinstance(value, int):
        return expression.as_integer()
    if isinstance(value, float):
        return expression.as_float()
    if isinstance(value, str):
        return expression.as_string()
    return expression.as_json()


def _conditions(model, query: dict[str, Any]):
    clauses = []
    for key, expected in (query or {}).items():
        expression = _expression(model, key)
        if expression is None:
            continue
        comparison = expression
        if "." in key and not isinstance(expected, dict):
            comparison = _typed_json_value(expression, expected)
        if isinstance(expected, dict):
            if "$ne" in expected:
                value = expected["$ne"]
                typed_comparison = _typed_json_value(expression, value) if "." in key else expression
                clauses.append(or_(expression.is_(None), typed_comparison != value))
            if "$in" in expected:
                clauses.append(expression.in_(expected["$in"]))
            if "$gt" in expected:
                typed_comparison = _typed_json_value(expression, expected["$gt"]) if "." in key else expression
                clauses.append(typed_comparison > expected["$gt"])
            if "$lt" in expected:
                typed_comparison = _typed_json_value(expression, expected["$lt"]) if "." in key else expression
                clauses.append(typed_comparison < expected["$lt"])
            if "$exists" in expected:
                clauses.append(expression.is_not(None) if expected["$exists"] else expression.is_(None))
        elif "." in key:
            clauses.append(comparison == expected)
        else:
            clauses.append(expression == expected)
    return clauses


def _parse_datetime(value):
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except ValueError:
            return value
    return value


def _json_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(child) for child in value]
    return value


def _prepare_doc(model, doc: dict[str, Any]):
    prepared = {}
    for key, value in doc.items():
        if key in {"_id", "id", "members", "memberCount", "sessionIds"}:
            continue
        if model is CurriculumTopic and key == "prerequisites":
            prepared["prerequisiteRefs"] = _json_value(value)
            continue
        attribute = _field_name(model, key)
        if attribute is None:
            logger.warning("Ignoring unmapped persisted field %s.%s", model.__tablename__, key)
            continue
        if key in DATE_FIELDS and value is not None:
            value = _parse_datetime(value)
        if key in JSON_FIELDS.get(model, set()):
            value = _json_value(value)
        prepared[attribute] = value
    identity = doc.get("_id", doc.get("id"))
    if identity is not None:
        prepared["id"] = str(identity)
    return prepared


def _row_doc(model, row, projection=None) -> dict[str, Any]:
    if model is AuthSession:
        values = {
            "_id": row.id,
            "user_id": row.user_id,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "csrf_token_hash": row.csrf_token_hash,
        }
        if isinstance(projection, dict):
            included = [key for key, enabled in projection.items() if enabled]
            if included:
                selected = {"_id": values["_id"]} if projection.get("_id", 1) else {}
                selected.update({key: values[key] for key in included if key in values and key != "_id"})
                return selected
            for key, enabled in projection.items():
                if not enabled:
                    values.pop(key, None)
        return values
    doc = {"_id": row.id}
    if isinstance(projection, dict):
        included = {key.split(".", 1)[0] for key, enabled in projection.items() if enabled}
        excluded = {key.split(".", 1)[0] for key, enabled in projection.items() if not enabled}
        attributes = (included - {"_id"}) if included else (_model_fields(model) - {"id"} - excluded)
    else:
        attributes = _model_fields(model) - {"id"}
    for attribute in attributes:
        if attribute not in _model_fields(model):
            continue
        value = getattr(row, attribute)
        if value is not None:
            doc[attribute] = copy.deepcopy(value)
    session = current_session()
    include_relations = not isinstance(projection, dict) or any(
        key in projection for key in {"members", "sessionIds", "prerequisites"}
    )
    if model is Classroom and include_relations:
        members = session.scalars(select(ClassroomMember).where(ClassroomMember.classroomId == row.id)).all()
        doc["members"] = [
            {"userId": member.userId, "role": member.role, "joinedAt": member.joinedAt}
            for member in members
        ]
    elif model is Topic and include_relations:
        doc["sessionIds"] = list(session.scalars(select(TopicSession.sessionId).where(TopicSession.topicId == row.id)).all())
    elif model is CurriculumTopic and include_relations:
        doc["prerequisites"] = copy.deepcopy(row.prerequisiteRefs or [])
    return doc


def _project(doc: dict[str, Any], projection):
    if not projection:
        return doc
    if isinstance(projection, dict):
        included = [key for key, enabled in projection.items() if enabled]
        excluded = [key for key, enabled in projection.items() if not enabled]
    else:
        included, excluded = [], []
    if included:
        result = {}
        if projection.get("_id", 1) and "_id" in doc:
            result["_id"] = doc["_id"]
        for key in included:
            if key == "_id":
                if "_id" in doc:
                    result[key] = doc[key]
                continue
            value = doc
            for part in key.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            if value is not None:
                target = result
                parts = key.split(".")
                for part in parts[:-1]:
                    target = target.setdefault(part, {})
                target[parts[-1]] = value
        return result
    result = copy.deepcopy(doc)
    for key in excluded:
        target = result
        parts = key.split(".")
        for part in parts[:-1]:
            target = target.get(part, {}) if isinstance(target, dict) else {}
        if isinstance(target, dict):
            target.pop(parts[-1], None)
    return result


def _sync_relations(model, row_id: str, doc: dict[str, Any], session) -> None:
    if model is Classroom and "members" in doc:
        existing = session.scalars(select(ClassroomMember).where(ClassroomMember.classroomId == row_id)).all()
        old_by_user = {member.userId: member for member in existing}
        desired = {str(item["userId"]): item for item in doc["members"] if item.get("userId")}
        for user_id, item in desired.items():
            values = {
                "classroomId": row_id,
                "userId": user_id,
                "role": item.get("role", "STUDENT"),
                "joinedAt": _parse_datetime(item.get("joinedAt")),
            }
            statement = insert(ClassroomMember).values(**values).on_conflict_do_update(
                constraint="uq_classroom_member",
                set_={"role": values["role"], "joinedAt": values["joinedAt"]},
            )
            session.execute(statement)
        for user_id, member in old_by_user.items():
            if user_id not in desired:
                session.delete(member)
    elif model is Topic and "sessionIds" in doc:
        for session_id in doc["sessionIds"]:
            session.execute(
                insert(TopicSession).values(
                    topicId=row_id,
                    sessionId=str(session_id),
                    userId=doc["userId"],
                ).on_conflict_do_nothing()
            )
    elif model is CurriculumTopic and "prerequisites" in doc:
        classroom_id = doc.get("classroomId")
        row = session.get(CurriculumTopic, row_id)
        if row is not None:
            row.prerequisiteRefs = [str(value) for value in doc["prerequisites"]]
        current = set(session.scalars(select(TopicPrerequisite.prerequisiteId).where(TopicPrerequisite.topicId == row_id)).all())
        requested = {str(value) for value in doc["prerequisites"]}
        known = set(session.scalars(select(CurriculumTopic.id).where(
            CurriculumTopic.classroomId == classroom_id,
            CurriculumTopic.id.in_(requested or [""]),
        )).all())
        for prerequisite_id in current - requested:
            session.execute(delete(TopicPrerequisite).where(
                TopicPrerequisite.topicId == row_id,
                TopicPrerequisite.prerequisiteId == prerequisite_id,
            ))
        for prerequisite_id in requested & known:
            session.execute(insert(TopicPrerequisite).values(
                topicId=row_id,
                prerequisiteId=prerequisite_id,
                classroomId=classroom_id,
            ).on_conflict_do_nothing())
    if model is CurriculumTopic and "concepts" in doc:
        classroom_id = doc.get("classroomId")
        desired_concept_edges = {
            (str(concept.get("name", "")), str(prerequisite))
            for concept in doc["concepts"]
            for prerequisite in concept.get("prerequisites", [])
            if concept.get("name") and prerequisite
        }
        existing_edges = session.scalars(select(ConceptPrerequisite).where(
            ConceptPrerequisite.topicId == row_id,
            ConceptPrerequisite.classroomId == classroom_id,
        )).all()
        existing_keys = {(edge.conceptName, edge.prerequisiteName): edge for edge in existing_edges}
        for edge_key, edge in existing_keys.items():
            if edge_key not in desired_concept_edges:
                session.delete(edge)
        for concept_name, prerequisite_name in desired_concept_edges - set(existing_keys):
            session.add(ConceptPrerequisite(
                topicId=row_id,
                classroomId=classroom_id,
                conceptName=concept_name,
                prerequisiteName=prerequisite_name,
            ))


class Cursor:
    def __init__(self, rows=None, loader=None):
        self.rows = rows or []
        self.loader = loader
        self.sort_spec = None
        self.limit_count = None

    def sort(self, key, direction=1):
        if isinstance(key, list):
            self.sort_spec = key
        else:
            self.sort_spec = [(key, direction)]
        if self.loader is None:
            for field, order in reversed(self.sort_spec):
                self._sort_one(field, order)
        return self

    def _sort_one(self, key, direction):
        def value(row):
            current = row
            for part in key.split("."):
                current = current.get(part) if isinstance(current, dict) else None
            return current or datetime.min
        self.rows.sort(key=value, reverse=direction < 0)

    def limit(self, count):
        self.limit_count = count
        if self.loader is None:
            self.rows = self.rows[:count]
        return self

    def __iter__(self):
        if self.loader is not None:
            return iter(self.loader(self.sort_spec, self.limit_count))
        return iter(self.rows)


class Collection:
    def __init__(self, name: str, model=None):
        self.name = name
        self.model = model

    def _select_model(self, query):
        if self.name == "sessions":
            return _model_for_session(query or {})
        return self.model

    def _query_rows(self, model, query=None, sort=None, limit=None, for_update=False, projection=None):
        session = current_session()
        statement = select(model).where(*_conditions(model, query or {}))
        if isinstance(projection, dict):
            included = {key.split(".", 1)[0] for key, enabled in projection.items() if enabled}
            excluded = {key.split(".", 1)[0] for key, enabled in projection.items() if not enabled}
            if included:
                selected = included - {"_id"}
                selected |= {key for key, _ in (sort if isinstance(sort, list) else [sort] if sort else [])}
            else:
                selected = _model_fields(model) - {"id"} - excluded
            attributes = [getattr(model, name) for name in selected if name in _model_fields(model)]
            attributes.append(model.id)
            statement = statement.options(load_only(*attributes))
        if sort:
            sort_items = sort if isinstance(sort, list) else [sort]
            for key, direction in sort_items:
                expression = _expression(model, key)
                if expression is not None:
                    statement = statement.order_by(expression.desc() if direction < 0 else expression.asc())
        if limit is not None:
            statement = statement.limit(limit)
        if for_update:
            statement = statement.with_for_update()
        return session.scalars(statement).all()

    def find_one(self, query=None, projection=None, sort=None):
        model = self._select_model(query or {})
        row = next(iter(self._query_rows(model, query, sort, 1, projection=projection)), None)
        return _project(_row_doc(model, row, projection), projection) if row is not None else None

    def find(self, query=None, projection=None, sort=None):
        model = self._select_model(query or {})
        def load(sort_spec, limit_count):
            rows = self._query_rows(model, query, sort_spec, limit_count, projection=projection)
            return [_project(_row_doc(model, row, projection), projection) for row in rows]
        if sort is not None:
            sort_spec = sort if isinstance(sort, list) else [(sort, 1)]
            return Cursor(loader=lambda _sort, limit: load(sort_spec, limit))
        return Cursor(loader=load)

    def insert_one(self, doc):
        model = self._select_model(doc)
        session = current_session()
        prepared = _prepare_doc(model, doc)
        row = model(**prepared)
        session.add(row)
        session.flush()
        _sync_relations(model, row.id, doc, session)
        return type("InsertResult", (), {"inserted_id": row.id})()

    def update_one(self, query, update_doc, upsert=False):
        model = self._select_model(query or {})
        session = current_session()
        row = next(iter(self._query_rows(model, query, limit=1, for_update=True)), None)
        is_insert = row is None
        if is_insert and not upsert:
            return type("UpdateResult", (), {"matched_count": 0, "modified_count": 0})()
        if is_insert:
            initial = {key: value for key, value in (query or {}).items() if not isinstance(value, dict)}
            initial.update(update_doc.get("$setOnInsert", {}))
            initial.update(update_doc.get("$set", {}))
            row = model(**_prepare_doc(model, initial))
            session.add(row)
            session.flush()
        else:
            initial = _row_doc(model, row)
        set_values = update_doc.get("$set", {})
        for key, value in set_values.items():
            if "." in key:
                root, *path = key.split(".")
                attribute = _field_name(model, root)
                if attribute and root in JSON_FIELDS.get(model, set()):
                    data = copy.deepcopy(getattr(row, attribute) or {})
                    target = data
                    for part in path[:-1]:
                        target = target.setdefault(part, {})
                    target[path[-1]] = _json_value(value)
                    setattr(row, attribute, data)
                continue
            attribute = _field_name(model, key)
            if attribute and attribute not in {"members", "sessionIds", "prerequisites", "memberCount"}:
                if key in DATE_FIELDS and value is not None:
                    value = _parse_datetime(value)
                if key in JSON_FIELDS.get(model, set()):
                    value = _json_value(value)
                setattr(row, attribute, value)
        for key, values in update_doc.get("$addToSet", {}).items():
            if model is Topic and key == "sessionIds":
                values = values.get("$each", [values]) if isinstance(values, dict) else [values]
                _sync_relations(model, row.id, {"sessionIds": values, "userId": row.userId}, session)
            elif model is CurriculumTopic and key == "prerequisites":
                values = values.get("$each", [values]) if isinstance(values, dict) else [values]
                _sync_relations(model, row.id, {"classroomId": row.classroomId, "prerequisites": values}, session)
        for key, value in set_values.items():
            if key in {"members", "sessionIds", "prerequisites"}:
                _sync_relations(model, row.id, {**initial, key: value}, session)
        session.flush()
        return type("UpdateResult", (), {"matched_count": 0 if is_insert else 1, "modified_count": 1})()

    def update_many(self, query, update_doc):
        rows = self._query_rows(self._select_model(query or {}), query)
        for row in rows:
            self.update_one({"_id": row.id}, update_doc)
        return type("UpdateResult", (), {"matched_count": len(rows), "modified_count": len(rows)})()

    def delete_one(self, query):
        model = self._select_model(query or {})
        row = next(iter(self._query_rows(model, query, limit=1)), None)
        if row is None:
            return type("DeleteResult", (), {"deleted_count": 0})()
        current_session().delete(row)
        return type("DeleteResult", (), {"deleted_count": 1})()

    def delete_many(self, query):
        model = self._select_model(query or {})
        rows = self._query_rows(model, query)
        for row in rows:
            current_session().delete(row)
        return type("DeleteResult", (), {"deleted_count": len(rows)})()

    def count_documents(self, query=None):
        model = self._select_model(query or {})
        statement = select(func.count()).select_from(model).where(*_conditions(model, query or {}))
        return current_session().scalar(statement) or 0


class _Admin:
    @staticmethod
    def command(command, *args, **kwargs):
        if command != "ping":
            raise ValueError("Only the database ping command is supported.")
        ping()
        return {"ok": 1}


class _Client:
    admin = _Admin()


class Database:
    client = _Client()

    def join_member(self, classroom_id: str, user_id: str, role: str, joined_at):
        session = current_session()
        statement = insert(ClassroomMember).values(
            classroomId=classroom_id,
            userId=user_id,
            role=role,
            joinedAt=_parse_datetime(joined_at),
        ).on_conflict_do_nothing(constraint="uq_classroom_member")
        result = session.execute(statement)
        session.execute(
            update(Classroom)
            .where(Classroom.id == classroom_id)
            .values(updatedAt=_parse_datetime(joined_at))
        )
        return result.rowcount == 1

    def add_member(self, classroom_id: str, user_id: str, role: str, joined_at=None):
        session = current_session()
        dt = _parse_datetime(joined_at) if joined_at else datetime.now(timezone.utc)
        statement = insert(ClassroomMember).values(
            classroomId=classroom_id,
            userId=user_id,
            role=role,
            joinedAt=dt,
        ).on_conflict_do_update(
            constraint="uq_classroom_member",
            set_={"role": role},
        )
        result = session.execute(statement)
        session.execute(
            update(Classroom)
            .where(Classroom.id == classroom_id)
            .values(updatedAt=dt)
        )
        return result.rowcount >= 1

    def update_member_role(self, classroom_id: str, user_id: str, role: str):
        session = current_session()
        dt = datetime.now(timezone.utc)
        statement = (
            update(ClassroomMember)
            .where(and_(ClassroomMember.classroomId == classroom_id, ClassroomMember.userId == user_id))
            .values(role=role)
        )
        result = session.execute(statement)
        session.execute(
            update(Classroom)
            .where(Classroom.id == classroom_id)
            .values(updatedAt=dt)
        )
        return result.rowcount >= 1

    def remove_member(self, classroom_id: str, user_id: str):
        session = current_session()
        dt = datetime.now(timezone.utc)
        statement = (
            delete(ClassroomMember)
            .where(and_(ClassroomMember.classroomId == classroom_id, ClassroomMember.userId == user_id))
        )
        result = session.execute(statement)
        session.execute(
            update(Classroom)
            .where(Classroom.id == classroom_id)
            .values(updatedAt=dt)
        )
        return result.rowcount >= 1

    def __getattr__(self, name):
        if name == "sessions":
            return Collection(name)
        if name not in COLLECTION_MODELS:
            raise AttributeError(name)
        return Collection(name, COLLECTION_MODELS[name])


db = Database()