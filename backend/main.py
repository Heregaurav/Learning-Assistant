import base64
import hashlib
import json
import logging
import os, re, secrets, uuid
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError

from models import (
    CompleteIn,
    ClassroomAssessmentIn,
    ClassroomGradeIn,
    ClassroomPostIn,
    ClassroomReplyIn,
    ClassroomSubmissionIn,
    CurriculumConceptIn,
    CurriculumMaterialIn,
    CurriculumModuleIn,
    CurriculumTopicIn,
    GoogleAuthIn,
    LearnIn,
    RefineIn,
    UserRoleUpdateIn,
)
from llm import generate_lesson, generate_retest_quiz, refine_lesson, LLMError
from document_processor.service import DocumentProcessingService
from document_processor.parser import EmptyDocumentError, UnsupportedDocumentError
from mastery import build_classroom_analytics, build_student_progress
from adaptive import build_adaptive_path
from evaluation import evaluate_written_answer

load_dotenv()
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLOCK_SKEW_SECONDS = int(os.getenv("GOOGLE_CLOCK_SKEW_SECONDS", "300"))
FRONTEND_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174",
    ).split(",")
    if origin.strip()
]
db = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=5000)[
    os.getenv("DATABASE_NAME", "learning_assistant")
]

app = FastAPI(title="AI Learning Assistant")
logger = logging.getLogger("uvicorn.error")
SESSION_COOKIE = "curiosity_session"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "1209600"))
SESSION_COOKIE_SECURE = os.getenv("APP_ENV", "development").lower() != "development"


def session_cookie_settings():
    return {
        "httponly": True,
        "secure": SESSION_COOKIE_SECURE,
        "samesite": "lax",
        "path": "/",
    }


def now() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_session(user_id: str, session_id: str | None = None, csrf_token: str | None = None):
    session_id = session_id or secrets.token_urlsafe(32)
    csrf_token = csrf_token or secrets.token_urlsafe(32)
    expires_at = now() + timedelta(seconds=SESSION_TTL_SECONDS)
    record = {
        "_id": session_id,
        "user_id": user_id,
        "created_at": now(),
        "expires_at": expires_at,
        "csrf_token_hash": hash_token(csrf_token),
    }
    db.sessions.update_one({"_id": session_id}, {"$set": record}, upsert=True)
    return {"id": session_id, "csrf_token": csrf_token, "expires_at": expires_at}


def get_session_user_id(session_id: str | None) -> str | None:
    if not session_id:
        return None
    session = db.sessions.find_one({"_id": session_id})
    if not session:
        return None
    expires_at = session.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not isinstance(expires_at, datetime) or expires_at <= now():
        db.sessions.delete_one({"_id": session_id})
        return None
    return session.get("user_id")


def is_valid_csrf_token(session_id: str | None, csrf_token: str | None) -> bool:
    if not session_id or not csrf_token:
        return False
    session = db.sessions.find_one({"_id": session_id}, {"csrf_token_hash": 1})
    return bool(session and session.get("csrf_token_hash") == hash_token(csrf_token))


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return await call_next(request)
    if request.url.path in {"/api/auth/google", "/api/auth/logout"}:
        return await call_next(request)
    session_id = request.cookies.get(SESSION_COOKIE)
    csrf_token = request.headers.get("X-CSRF-Token")
    if is_valid_csrf_token(session_id, csrf_token):
        return await call_next(request)
    return JSONResponse(
        status_code=403,
        content={"detail": {"code": "csrf_invalid", "message": "Invalid or missing CSRF token."}},
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def err(status: int, code: str, message: str):
    return HTTPException(status, detail={"code": code, "message": message})


def user_topic_id(topic_id: str, user_id: str) -> str:
    if db.topics.find_one({"_id": topic_id, "userId": user_id}, {"_id": 1}):
        return topic_id
    suffix = uuid.uuid5(uuid.NAMESPACE_URL, f"{user_id}:{topic_id}").hex[:16]
    return f"{topic_id}_{suffix}"


def out(doc):
    if doc is not None and "_id" in doc:
        doc["id"] = doc.pop("_id")
    return doc


def level(score: int) -> str:
    return "Strong" if score >= 85 else "Good" if score >= 70 else "Needs review"


VALID_ROLES = {"ADMIN", "FACULTY", "STUDENT"}


def normalize_role(value: str | None) -> str:
    role = (value or "STUDENT").upper().strip()
    return role if role in VALID_ROLES else "STUDENT"


def classroom_payload(doc: dict) -> dict:
    payload = dict(doc)
    payload["id"] = str(payload.pop("_id"))
    members = payload.get("members", [])
    payload["memberCount"] = len(members)
    payload["members"] = [
        {
            **member,
            "name": (db.users.find_one({"_id": member.get("userId")}) or {}).get("name", "Class member"),
        }
        for member in members
    ]
    payload["status"] = payload.get("status", "active")
    if payload.get("ownerId"):
        owner = db.users.find_one({"_id": payload["ownerId"]})
        if owner:
            payload["ownerName"] = owner.get("name", "Faculty")
    return payload


def require_role(user: dict | None, *allowed_roles: str):
    if user is None:
        raise err(401, "auth_required", "Sign in with Google to continue.")
    role = normalize_role(user.get("role"))
    if allowed_roles and role not in {normalize_role(item) for item in allowed_roles}:
        raise err(403, "forbidden", "You do not have permission to perform this action.")
    return role


def create_classroom(payload: dict, user: dict):
    role = require_role(user, "ADMIN", "FACULTY", "STUDENT")
    name = str(payload.get("name", "")).strip()
    subject = str(payload.get("subject", "")).strip()
    section = str(payload.get("section", "")).strip()
    semester = str(payload.get("semester", "")).strip()
    description = str(payload.get("description", "")).strip()
    if not name or not subject or not section or not semester:
        raise err(400, "invalid_classroom", "Classroom name, subject, section, and semester are required.")
    join_code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    while db.classrooms.find_one({"joinCode": join_code}):
        join_code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    classroom = {
        "_id": f"classroom_{uuid.uuid4().hex[:12]}",
        "name": name,
        "subject": subject,
        "section": section,
        "semester": semester,
        "description": description,
        "ownerId": user["id"],
        "facultyIds": [user["id"]] if role == "FACULTY" else [],
        "joinCode": join_code,
        "status": "active",
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "curriculum": {"modules": []},
        "members": [{"userId": user["id"], "role": "OWNER", "joinedAt": now_iso()}],
    }
    db.classrooms.insert_one(classroom)
    return classroom_payload(classroom)


def delete_classroom(classroom_id: str, user: dict):
    classroom = db.classrooms.find_one({"_id": classroom_id})
    if not classroom:
        raise err(404, "not_found", "Classroom not found.")
    require_role(user, "ADMIN", "FACULTY", "STUDENT")
    if classroom.get("ownerId") != user["id"]:
        raise err(403, "forbidden", "Only the teacher who created this classroom can delete it.")

    for collection_name in (
        "classroom_modules",
        "classroom_curriculum_topics",
        "classroom_assessments",
        "classroom_submissions",
        "classroom_posts",
        "classroom_replies",
        "learning_events",
        "learning_paths",
    ):
        getattr(db, collection_name).delete_many({"classroomId": classroom_id})
    db.classrooms.delete_one({"_id": classroom_id})
    return {"deleted": True, "id": classroom_id}


def list_classrooms(user: dict):
    role = require_role(user, "ADMIN", "FACULTY", "STUDENT")
    rows = list(db.classrooms.find({}))
    visible = []
    for row in rows:
        if role == "ADMIN":
            visible.append(classroom_payload(row))
            continue
        members = row.get("members", [])
        if row.get("ownerId") == user["id"] or any(member.get("userId") == user["id"] for member in members):
            item = classroom_payload(row)
            if not _classroom_editor(row, user):
                item.pop("joinCode", None)
            visible.append(item)
    return sorted(visible, key=lambda item: item.get("createdAt", ""), reverse=True)


def get_classroom(classroom_id: str, user: dict):
    classroom = db.classrooms.find_one({"_id": classroom_id})
    if not classroom:
        raise err(404, "not_found", "Classroom not found.")
    role = require_role(user, "ADMIN", "FACULTY", "STUDENT")
    is_owner = classroom.get("ownerId") == user["id"]
    is_member = any(member.get("userId") == user["id"] for member in classroom.get("members", []))
    if role != "ADMIN" and not is_owner and not is_member:
        raise err(403, "forbidden", "You do not have access to this classroom.")
    result = classroom_payload(classroom)
    if not _classroom_editor(classroom, user):
        result.pop("joinCode", None)
    return result


def require_classroom_editor(classroom_id: str, user: dict):
    classroom = db.classrooms.find_one({"_id": classroom_id})
    if not classroom:
        raise err(404, "not_found", "Classroom not found.")
    role = require_role(user, "ADMIN", "FACULTY", "STUDENT")
    if role == "ADMIN" or classroom.get("ownerId") == user["id"]:
        return classroom
    if role != "FACULTY" or user["id"] not in classroom.get("facultyIds", []):
        raise err(403, "forbidden", "Only authorized classroom faculty can edit its curriculum.")
    return classroom


def get_classroom_curriculum(classroom_id: str, user: dict):
    classroom = get_classroom(classroom_id, user)
    modules = list(db.classroom_modules.find({"classroomId": classroom_id}))
    modules.sort(key=lambda item: item.get("position", 0))
    curriculum = []
    for module in modules:
        module_id = module["_id"]
        topics = list(
            db.classroom_curriculum_topics.find(
                {"classroomId": classroom_id, "moduleId": module_id}
            )
        )
        topics.sort(key=lambda item: item.get("position", 0))
        curriculum.append(
            {
                "id": module_id,
                "title": module["title"],
                "description": module.get("description", ""),
                "position": module.get("position", 0),
                "topics": [
                    {**{key: value for key, value in topic.items() if key != "_id"}, "id": topic["_id"]}
                    for topic in topics
                ],
            }
        )
    return {"classroom": classroom, "modules": curriculum}


def create_curriculum_module(classroom_id: str, payload: CurriculumModuleIn, user: dict):
    require_classroom_editor(classroom_id, user)
    module = {
        "_id": f"module_{uuid.uuid4().hex[:12]}",
        "classroomId": classroom_id,
        "title": payload.title.strip(),
        "description": payload.description.strip(),
        "position": payload.position,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    db.classroom_modules.insert_one(module)
    return {**{key: value for key, value in module.items() if key != "_id"}, "id": module["_id"], "topics": []}


def create_curriculum_topic(
    classroom_id: str,
    module_id: str,
    payload: CurriculumTopicIn,
    user: dict,
):
    require_classroom_editor(classroom_id, user)
    module = db.classroom_modules.find_one({"_id": module_id, "classroomId": classroom_id})
    if not module:
        raise err(404, "not_found", "Curriculum module not found in this classroom.")
    topic = {
        "_id": f"topic_{uuid.uuid4().hex[:12]}",
        "classroomId": classroom_id,
        "moduleId": module_id,
        "title": payload.title.strip(),
        "description": payload.description.strip(),
        "learningObjectives": [item.strip() for item in payload.learningObjectives if item.strip()],
        "prerequisites": payload.prerequisites,
        "concepts": [item.model_dump() for item in payload.concepts],
        "materials": [item.model_dump() for item in payload.materials],
        "position": db.classroom_curriculum_topics.count_documents(
            {"classroomId": classroom_id, "moduleId": module_id}
        ),
        "published": True,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    db.classroom_curriculum_topics.insert_one(topic)
    return {**{key: value for key, value in topic.items() if key != "_id"}, "id": topic["_id"]}


def classroom_topic_learning_context(classroom_id: str, topic_id: str, user: dict):
    classroom = get_classroom(classroom_id, user)
    topic = db.classroom_curriculum_topics.find_one(
        {"_id": topic_id, "classroomId": classroom_id, "published": True}
    )
    if not topic:
        raise err(404, "not_found", "Published topic not found in this classroom.")
    module = db.classroom_modules.find_one(
        {"_id": topic["moduleId"], "classroomId": classroom_id}
    )
    return classroom, module or {}, topic


def render_classroom_learning_prompt(
    content: str,
    classroom: dict,
    module: dict,
    topic: dict,
    learning_path: dict | None = None,
):
    concepts = "\n".join(
        f"- {concept['name']}: {concept.get('description', '')}"
        for concept in topic.get("concepts", [])
    ) or "None specified"
    objectives = "\n".join(f"- {item}" for item in topic.get("learningObjectives", [])) or "None specified"
    prerequisites = "\n".join(f"- {item}" for item in topic.get("prerequisites", [])) or "None specified"
    materials = "\n".join(
        f"- {material['title']}: {material.get('content') or material.get('url', '')}"
        for material in topic.get("materials", [])
    ) or "None provided"
    recommendation = (learning_path or {}).get("recommendation") or {}
    adaptive_state = (
        f"Current topic status: {recommendation.get('status', 'selected')}\n"
        f"Current topic mastery: {recommendation.get('mastery', {}).get('score', 'not measured')}\n"
        f"Adaptive reason: {recommendation.get('reason', 'Follow the selected curriculum topic.')}\n"
        f"Next action: {recommendation.get('nextAction', 'Build understanding with a lesson and quiz.')}"
        if recommendation.get("topicId") == (topic.get("id") or topic.get("_id"))
        else "The student is exploring this permitted curriculum topic."
    )
    return (
        "You are the classroom adaptive learning agent, not a general-purpose tutor. "
        "Teach only the selected official curriculum topic and its prerequisites. "
        "If the student asks about an unrelated subject, briefly redirect them to this topic. "
        "Treat the teacher-authored curriculum as authoritative; do not modify it.\n\n"
        f"Classroom: {classroom['name']} ({classroom.get('subject', '')})\n"
        f"Module: {module.get('title', '')}\n"
        f"Official topic: {topic['title']}\n"
        f"Topic description: {topic.get('description', '')}\n"
        f"Learning objectives:\n{objectives}\n"
        f"Expected concepts:\n{concepts}\n"
        f"Prerequisites:\n{prerequisites}\n"
        f"Teacher materials:\n{materials}\n\n"
        f"Student adaptive state:\n{adaptive_state}\n\n"
        f"Student request: {content}"
    )


def classroom_progress(classroom_id: str, user: dict):
    curriculum = get_classroom_curriculum(classroom_id, user)
    events = [
        event
        for event in db.learning_events.find({"classroomId": classroom_id})
        if event.get("userId") == user["id"]
    ]
    progress = build_student_progress(curriculum["modules"], events)
    path = build_adaptive_path(curriculum["modules"], events)
    db.learning_paths.update_one(
        {"_id": f"learning_path_{classroom_id}_{user['id']}", "classroomId": classroom_id, "userId": user["id"]},
        {"$set": {"classroomId": classroom_id, "userId": user["id"], "path": path, "updatedAt": now()}},
        upsert=True,
    )
    progress["learningPath"] = path
    return progress


def classroom_analytics(classroom_id: str, user: dict):
    classroom = require_classroom_editor(classroom_id, user)
    curriculum = get_classroom_curriculum(classroom_id, user)
    student_ids = list(
        dict.fromkeys(
            member["userId"]
            for member in classroom.get("members", [])
            if member.get("role") == "STUDENT" and member.get("userId")
        )
    )
    events = list(db.learning_events.find({"classroomId": classroom_id}))
    return build_classroom_analytics(curriculum["modules"], student_ids, events)


def classroom_knowledge_graph(classroom_id: str, user: dict, student_id: str | None = None):
    classroom = get_classroom(classroom_id, user)
    target_student = student_id or user["id"]
    if target_student != user["id"]:
        if not _classroom_editor(classroom, user):
            raise err(403, "forbidden", "Students may only view their own knowledge graph.")
        is_student_member = any(
            member.get("userId") == target_student and member.get("role") == "STUDENT"
            for member in classroom.get("members", [])
        )
        if not is_student_member:
            raise err(404, "not_found", "Student is not enrolled in this classroom.")
    curriculum = get_classroom_curriculum(classroom_id, user)
    events = [
        event
        for event in db.learning_events.find({"classroomId": classroom_id})
        if event.get("userId") == target_student
    ]
    progress = build_student_progress(curriculum["modules"], events)
    topic_progress = {
        topic["id"]: topic
        for module in progress["modules"]
        for topic in module["topics"]
    }
    nodes = []
    edges = []
    concept_node_by_name: dict[str, str] = {}
    for module in curriculum["modules"]:
        for topic in module["topics"]:
            topic_id = f"topic:{topic['id']}"
            topic_state = topic_progress[topic["id"]]
            nodes.append(
                {
                    "id": topic_id,
                    "curriculumId": topic["id"],
                    "label": topic["title"],
                    "kind": "topic",
                    "mastery": topic_state["mastery"],
                    "coverage": topic_state["coverage"],
                }
            )
            for concept in topic.get("concepts", []):
                concept_id = f"concept:{topic['id']}:{concept['name']}"
                concept_node_by_name.setdefault(concept["name"], concept_id)
                concept_state = next(
                    item for item in topic_state["concepts"] if item["name"] == concept["name"]
                )
                nodes.append(
                    {
                        "id": concept_id,
                        "curriculumId": concept["name"],
                        "label": concept["name"],
                        "kind": "concept",
                        "mastery": concept_state["mastery"],
                        "coverage": topic_state["coverage"],
                    }
                )
                edges.append({"source": topic_id, "target": concept_id, "kind": "contains"})
    for module in curriculum["modules"]:
        for topic in module["topics"]:
            for concept in topic.get("concepts", []):
                target = f"concept:{topic['id']}:{concept['name']}"
                for prerequisite in concept.get("prerequisites", []):
                    source = concept_node_by_name.get(prerequisite)
                    if source:
                        edges.append({"source": source, "target": target, "kind": "prerequisite"})
    return {"studentId": target_student, "nodes": nodes, "edges": edges}


def _classroom_editor(classroom: dict, user: dict) -> bool:
    role = normalize_role(user.get("role"))
    return (
        role == "ADMIN"
        or classroom.get("ownerId") == user["id"]
        or (role == "FACULTY" and user["id"] in classroom.get("facultyIds", []))
    )


def create_classroom_assessment(
    classroom_id: str, payload: ClassroomAssessmentIn, user: dict
):
    classroom = require_classroom_editor(classroom_id, user)
    if payload.topicId and not db.classroom_curriculum_topics.find_one(
        {"_id": payload.topicId, "classroomId": classroom_id}
    ):
        raise err(404, "not_found", "Assessment topic not found in this classroom.")
    assessment = {
        "_id": f"assessment_{uuid.uuid4().hex[:12]}",
        "classroomId": classroom_id,
        "title": payload.title.strip(),
        "kind": payload.kind,
        "instructions": payload.instructions.strip(),
        "topicId": payload.topicId,
        "conceptIds": payload.conceptIds,
        "dueAt": payload.dueAt,
        "maxMarks": payload.maxMarks,
        "rubric": payload.rubric.strip(),
        "expectedAnswer": payload.expectedAnswer.strip(),
        "published": payload.published,
        "createdBy": user["id"],
        "createdAt": now(),
        "updatedAt": now(),
    }
    db.classroom_assessments.insert_one(assessment)
    return {**{key: value for key, value in assessment.items() if key != "_id"}, "id": assessment["_id"]}


def list_classroom_assessments(classroom_id: str, user: dict):
    classroom = get_classroom(classroom_id, user)
    rows = list(db.classroom_assessments.find({"classroomId": classroom_id}))
    if not _classroom_editor(classroom, user):
        rows = [row for row in rows if row.get("published")]
    rows.sort(key=lambda row: row.get("createdAt", now()), reverse=True)
    return [
        {**{key: value for key, value in row.items() if key != "_id"}, "id": row["_id"]}
        for row in rows
    ]


def submit_classroom_assessment(
    classroom_id: str,
    assessment_id: str,
    payload: ClassroomSubmissionIn,
    user: dict,
):
    require_role(user, "STUDENT")
    get_classroom(classroom_id, user)
    assessment = db.classroom_assessments.find_one(
        {"_id": assessment_id, "classroomId": classroom_id, "published": True}
    )
    if not assessment:
        raise err(404, "not_found", "Published assessment not found in this classroom.")
    previous = db.classroom_submissions.find_one(
        {"assessmentId": assessment_id, "studentId": user["id"]}
    )
    if previous:
        raise err(409, "submission_exists", "A submission already exists for this assessment.")
    submission = {
        "_id": f"submission_{uuid.uuid4().hex[:12]}",
        "classroomId": classroom_id,
        "assessmentId": assessment_id,
        "studentId": user["id"],
        "answer": payload.answer.strip(),
        "status": "submitted",
        "evaluationStatus": "pending",
        "submittedAt": now(),
    }
    db.classroom_submissions.insert_one(submission)
    return {**{key: value for key, value in submission.items() if key != "_id"}, "id": submission["_id"]}


def list_classroom_submissions(classroom_id: str, assessment_id: str, user: dict):
    classroom = get_classroom(classroom_id, user)
    assessment = db.classroom_assessments.find_one(
        {"_id": assessment_id, "classroomId": classroom_id}
    )
    if not assessment:
        raise err(404, "not_found", "Assessment not found in this classroom.")
    if _classroom_editor(classroom, user):
        rows = list(db.classroom_submissions.find({"assessmentId": assessment_id}))
    else:
        rows = list(
            db.classroom_submissions.find(
                {"assessmentId": assessment_id, "studentId": user["id"]}
            )
        )
    result = []
    for row in rows:
        item = {**{key: value for key, value in row.items() if key != "_id"}, "id": row["_id"]}
        if not _classroom_editor(classroom, user) and not item.get("released"):
            item.pop("score", None)
            item.pop("feedback", None)
            item.pop("aiEvaluation", None)
        result.append(item)
    return result


def grade_classroom_submission(
    classroom_id: str,
    assessment_id: str,
    submission_id: str,
    payload: ClassroomGradeIn,
    user: dict,
):
    require_classroom_editor(classroom_id, user)
    assessment = db.classroom_assessments.find_one(
        {"_id": assessment_id, "classroomId": classroom_id}
    )
    submission = db.classroom_submissions.find_one(
        {
            "_id": submission_id,
            "classroomId": classroom_id,
            "assessmentId": assessment_id,
        }
    )
    if not assessment or not submission:
        raise err(404, "not_found", "Assessment submission not found.")
    if payload.score > assessment["maxMarks"]:
        raise err(400, "invalid_score", "Score cannot exceed the assessment maximum marks.")
    curriculum_topic = (
        db.classroom_curriculum_topics.find_one(
            {"_id": assessment["topicId"], "classroomId": classroom_id},
            {"moduleId": 1},
        )
        if assessment.get("topicId")
        else None
    )
    db.classroom_submissions.update_one(
        {"_id": submission_id, "classroomId": classroom_id},
        {
            "$set": {
                "score": payload.score,
                "feedback": payload.feedback.strip(),
                "released": payload.release,
                "status": "graded",
                "evaluationStatus": "faculty_graded",
                "gradedBy": user["id"],
                "gradedAt": now(),
            }
        },
    )
    if assessment.get("topicId"):
        db.learning_events.update_one(
            {"_id": f"learning_event_submission_{submission_id}"},
            {
                "$set": {
                    "userId": submission["studentId"],
                    "classroomId": classroom_id,
                    "moduleId": (curriculum_topic or {}).get("moduleId"),
                    "topicId": assessment["topicId"],
                    "concepts": assessment.get("conceptIds", []),
                    "activityType": assessment["kind"],
                    "evidenceType": "assessment",
                    "sourceSubmissionId": submission_id,
                    "score": payload.score,
                    "maxScore": assessment["maxMarks"],
                    "masteryScore": round(payload.score / assessment["maxMarks"] * 100),
                    "coverage": True,
                    "attempt": 1,
                    "evaluationStatus": "faculty_graded",
                    "occurredAt": now(),
                },
                "$setOnInsert": {"createdAt": now()},
            },
            upsert=True,
        )
    return {"id": submission_id, "score": payload.score, "released": payload.release}


def evaluate_classroom_submission(
    classroom_id: str,
    assessment_id: str,
    submission_id: str,
    user: dict,
):
    require_classroom_editor(classroom_id, user)
    assessment = db.classroom_assessments.find_one(
        {"_id": assessment_id, "classroomId": classroom_id}
    )
    submission = db.classroom_submissions.find_one(
        {"_id": submission_id, "classroomId": classroom_id, "assessmentId": assessment_id}
    )
    if not assessment or not submission:
        raise err(404, "not_found", "Assessment submission not found.")
    topic = (
        db.classroom_curriculum_topics.find_one(
            {"_id": assessment["topicId"], "classroomId": classroom_id}
        )
        if assessment.get("topicId")
        else None
    ) or {}
    expected_concepts = assessment.get("conceptIds", [])
    if not expected_concepts:
        expected_concepts = [item["name"] for item in topic.get("concepts", [])]
    context = "\n".join(
        [topic.get("description", ""), *topic.get("learningObjectives", [])]
        + [material.get("content", "") for material in topic.get("materials", [])]
    )
    try:
        result = evaluate_written_answer(
            question=f"{assessment['title']}\n{assessment.get('instructions', '')}",
            answer=submission["answer"],
            rubric=assessment.get("rubric", ""),
            expected_answer=assessment.get("expectedAnswer", ""),
            max_marks=assessment["maxMarks"],
            expected_concepts=expected_concepts,
            course_context=context,
            provider=os.getenv("EVALUATION_PROVIDER", "groq"),
            model=os.getenv("EVALUATION_MODEL") or None,
        )
    except LLMError as exc:
        raise err(504 if exc.code == "timeout" else 502, exc.code, exc.message)
    db.classroom_submissions.update_one(
        {"_id": submission_id, "classroomId": classroom_id},
        {"$set": {"aiEvaluation": result, "aiEvaluatedAt": now(), "evaluationStatus": "ai_evaluated"}},
    )
    if assessment.get("topicId"):
        db.learning_events.update_one(
            {"_id": f"learning_event_submission_{submission_id}"},
            {
                "$set": {
                    "userId": submission["studentId"],
                    "classroomId": classroom_id,
                    "moduleId": topic.get("moduleId"),
                    "topicId": assessment["topicId"],
                    "concepts": list(result["conceptScores"]),
                    "activityType": assessment["kind"],
                    "evidenceType": "ai_evaluated_assessment",
                    "sourceSubmissionId": submission_id,
                    "score": result["score"],
                    "maxScore": assessment["maxMarks"],
                    "masteryScore": round(result["score"] / assessment["maxMarks"] * 100),
                    "conceptScores": result["conceptScores"],
                    "coverage": True,
                    "attempt": 1,
                    "evaluationStatus": "complete",
                    "occurredAt": now(),
                },
                "$setOnInsert": {"createdAt": now()},
            },
            upsert=True,
        )
    return result


def list_classroom_posts(classroom_id: str, user: dict):
    get_classroom(classroom_id, user)
    posts = list(db.classroom_posts.find({"classroomId": classroom_id}))
    posts.sort(key=lambda post: post.get("createdAt", now()), reverse=True)
    result = []
    for post in posts:
        replies = list(db.classroom_replies.find({"postId": post["_id"], "classroomId": classroom_id}))
        replies.sort(key=lambda reply: reply.get("createdAt", now()))
        result.append(
            {
                **{key: value for key, value in post.items() if key != "_id"},
                "id": post["_id"],
                "replies": [
                    {**{key: value for key, value in reply.items() if key != "_id"}, "id": reply["_id"]}
                    for reply in replies
                ],
            }
        )
    return result


def create_classroom_post(classroom_id: str, payload: ClassroomPostIn, user: dict):
    classroom = get_classroom(classroom_id, user)
    if payload.kind == "announcement" and not _classroom_editor(classroom, user):
        raise err(403, "forbidden", "Only the classroom owner or authorized faculty can post announcements.")
    post = {
        "_id": f"post_{uuid.uuid4().hex[:12]}",
        "classroomId": classroom_id,
        "kind": payload.kind,
        "title": payload.title.strip(),
        "body": payload.body.strip(),
        "authorId": user["id"],
        "createdAt": now(),
    }
    db.classroom_posts.insert_one(post)
    return {**{key: value for key, value in post.items() if key != "_id"}, "id": post["_id"], "replies": []}


def create_classroom_reply(
    classroom_id: str, post_id: str, payload: ClassroomReplyIn, user: dict
):
    get_classroom(classroom_id, user)
    post = db.classroom_posts.find_one({"_id": post_id, "classroomId": classroom_id})
    if not post:
        raise err(404, "not_found", "Classroom post not found.")
    reply = {
        "_id": f"reply_{uuid.uuid4().hex[:12]}",
        "classroomId": classroom_id,
        "postId": post_id,
        "authorId": user["id"],
        "body": payload.body.strip(),
        "createdAt": now(),
    }
    db.classroom_replies.insert_one(reply)
    return {**{key: value for key, value in reply.items() if key != "_id"}, "id": reply["_id"]}


def join_classroom(payload: dict, user: dict):
    role = require_role(user, "STUDENT", "FACULTY")
    join_code = str(payload.get("joinCode", "")).strip().upper()
    classroom = db.classrooms.find_one({"joinCode": join_code})
    if not classroom:
        raise err(404, "not_found", "Join code not found.")
    members = classroom.get("members", [])
    if any(member.get("userId") == user["id"] for member in members):
        return {**classroom_payload(classroom), "memberCount": len(members)}
    member_role = "FACULTY" if role == "FACULTY" else "STUDENT"
    members.append({"userId": user["id"], "role": member_role, "joinedAt": now_iso()})
    db.classrooms.update_one({"_id": classroom["_id"]}, {"$set": {"members": members, "updatedAt": now_iso()}})
    updated = db.classrooms.find_one({"_id": classroom["_id"]})
    return {**classroom_payload(updated), "memberCount": len(updated.get("members", []))}


def update_user_role(user_id: str, payload: dict, acting_user: dict):
    require_role(acting_user, "ADMIN")
    target_role = str(payload.get("role", "")).upper().strip()
    if target_role not in VALID_ROLES:
        raise err(400, "invalid_role", "Role must be ADMIN, FACULTY, or STUDENT.")
    if acting_user["id"] == user_id and target_role in {"FACULTY", "ADMIN"}:
        raise err(403, "forbidden", "You cannot promote yourself to a higher role.")
    target = db.users.find_one({"_id": user_id})
    if not target:
        raise err(404, "not_found", "User not found.")
    db.users.update_one({"_id": user_id}, {"$set": {"role": target_role, "updatedAt": now_iso()}})
    return {"id": user_id, "name": target.get("name", "User"), "email": target.get("email", ""), "role": target_role}


def list_platform_users(acting_user: dict):
    require_role(acting_user, "ADMIN")
    return [
        {
            "id": user["_id"],
            "name": user.get("name", "Learner"),
            "email": user.get("email", ""),
            "role": normalize_role(user.get("role")),
            "createdAt": user.get("createdAt"),
        }
        for user in db.users.find({}, {"name": 1, "email": 1, "role": 1, "createdAt": 1})
        if not str(user.get("_id", "")).startswith("guest_")
    ]


def current_user(
    request: Request,
    guest_id: str | None = Header(default=None, alias="X-Guest-ID"),
):
    session_id = request.cookies.get(SESSION_COOKIE)
    user_id = get_session_user_id(session_id)
    if user_id:
        user = db.users.find_one({"_id": user_id})
        if user:
            return {
                "id": user["_id"],
                "name": user.get("name", "Learner"),
                "email": user.get("email", ""),
                "picture": user.get("picture", ""),
                "role": normalize_role(user.get("role")),
            }
        db.sessions.delete_one({"_id": session_id})
    if guest_id and re.fullmatch(r"guest_[0-9a-f-]{36}", guest_id):
        db.users.update_one(
            {"_id": guest_id},
            {
                "$set": {"name": "Guest", "email": "", "picture": "", "updatedAt": now_iso()},
                "$setOnInsert": {
                    "createdAt": now_iso(),
                    "stats": {
                        "topicsStudied": 0,
                        "sessionsCompleted": 0,
                        "averageScore": 0,
                        "cardsReviewed": 0,
                        "quizzesCompleted": 0,
                    },
                },
            },
            upsert=True,
        )
        return {"id": guest_id, "name": "Guest", "email": "", "picture": "", "role": "STUDENT", "isGuest": True}
    raise err(401, "auth_required", "Sign in with Google to continue.")


def verify_google_credential(credential: str):
    if not GOOGLE_CLIENT_ID:
        raise err(503, "auth_not_configured", "Set GOOGLE_CLIENT_ID in backend/.env.")
    try:
        claims = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=GOOGLE_CLOCK_SKEW_SECONDS,
        )
    except ValueError as exc:
        reason = str(exc).lower()
        claim_audience = "unknown"
        try:
            encoded_claims = credential.split(".")[1]
            encoded_claims += "=" * (-len(encoded_claims) % 4)
            claim_audience = json.loads(base64.urlsafe_b64decode(encoded_claims)).get("aud", "unknown")
        except (IndexError, ValueError, json.JSONDecodeError):
            pass
        category = "expired" if "expired" in reason else "invalid_or_wrong_client"
        logger.warning(
            "Google token rejected: %s; audience_matches=%s; verifier=%s",
            category,
            claim_audience == GOOGLE_CLIENT_ID,
            str(exc)[:180],
        )
        if "expired" in reason:
            raise err(401, "auth_expired", "Your Google sign-in has expired. Please sign in again.")
        raise err(401, "invalid_auth", "Google rejected this sign-in token. Check the OAuth client ID and authorized origin.")
    except GoogleAuthError:
        logger.warning("Google token rejected: google_auth_error")
        raise err(401, "invalid_auth", "Google rejected this sign-in token. Check the OAuth client ID and authorized origin.")
    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise err(401, "invalid_auth", "Invalid Google identity.")
    return claims


def auth_session_status(session_id: str | None):
    user_id = get_session_user_id(session_id)
    if not user_id:
        return {"authenticated": False, "user": None}
    user = db.users.find_one({"_id": user_id})
    if not user:
        db.sessions.delete_one({"_id": session_id})
        return {"authenticated": False, "user": None}
    return {
        "authenticated": True,
        "user": {
            "id": user["_id"],
            "name": user.get("name", "Learner"),
            "email": user.get("email", ""),
            "picture": user.get("picture", ""),
            "role": normalize_role(user.get("role")),
        },
    }


@app.get("/api/auth/session")
def auth_session(request: Request):
    return auth_session_status(request.cookies.get(SESSION_COOKIE))


@app.post("/api/auth/google")
def google_auth(body: GoogleAuthIn, response: Response):
    claims = verify_google_credential(body.credential)
    user_id = claims["sub"]
    existing_user = db.users.find_one({"_id": user_id}, {"role": 1}) or {}
    bootstrap_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().casefold()
    first_admin = bool(
        bootstrap_email
        and claims.get("email_verified") is True
        and str(claims.get("email", "")).strip().casefold() == bootstrap_email
        and db.users.count_documents({"role": "ADMIN"}) == 0
    )
    assigned_role = (
        "ADMIN"
        if first_admin
        else normalize_role(existing_user["role"])
        if existing_user.get("role")
        else "STUDENT"
    )
    db.users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "name": claims.get("name", "Learner"),
                "email": claims.get("email", ""),
                "picture": claims.get("picture", ""),
                "role": assigned_role,
                "updatedAt": now_iso(),
            },
            "$setOnInsert": {
                "createdAt": now_iso(),
                "stats": {
                    "topicsStudied": 0,
                    "sessionsCompleted": 0,
                    "averageScore": 0,
                    "cardsReviewed": 0,
                    "quizzesCompleted": 0,
                },
            },
        },
        upsert=True,
    )
    session = create_session(user_id)
    response.set_cookie(key=SESSION_COOKIE, value=session["id"], **session_cookie_settings())
    user_doc = db.users.find_one({"_id": user_id}) or {}
    return {
        "user": {
            "id": user_id,
            "name": claims.get("name", "Learner"),
            "email": claims.get("email", ""),
            "picture": claims.get("picture", ""),
            "role": normalize_role(user_doc.get("role")),
        },
        "csrfToken": session["csrf_token"],
    }


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        db.sessions.delete_one({"_id": session_id})
    response.delete_cookie(key=SESSION_COOKIE, path="/", samesite="lax")
    return {"status": "ok"}


@app.exception_handler(PyMongoError)
async def db_error(_: Request, __: PyMongoError):
    if isinstance(__, OperationFailure) and __.code == 8000:
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "database_auth_failed",
                    "message": "MongoDB rejected the username or password. Check the Atlas database user and URL encoding.",
                }
            },
        )
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "code": "database_unavailable",
                "message": "Database unavailable.",
            }
        },
    )


@app.get("/api/health")
def health():
    try:
        db.client.admin.command("ping")
        return {"status": "ok", "database": "connected"}
    except OperationFailure as exc:
        if exc.code == 8000:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "code": "database_auth_failed",
                    "message": "MongoDB rejected the username or password.",
                },
            )
        return JSONResponse(
            status_code=503, content={"status": "error", "code": "database_unavailable"}
        )
    except PyMongoError:
        return JSONResponse(
            status_code=503, content={"status": "error", "code": "database_unavailable"}
        )


@app.post("/api/learn")
def learn(body: LearnIn, user: dict = Depends(current_user)):
    try:
        lesson = generate_lesson(
            body.content, body.difficulty, body.provider, body.model
        )
    except LLMError as e:
        raise err(504 if e.code == "timeout" else 502, e.code, e.message)
    sid = f"session_{uuid.uuid4().hex[:12]}"
    user_id = user["id"]
    topic_key = "topic_" + re.sub(
        r"[^a-z0-9]+", "_", lesson.topic.lower()
    ).strip("_")
    tid = user_topic_id(topic_key, user_id)
    data = lesson.model_dump()
    db.sessions.insert_one(
        {
            "_id": sid,
            "userId": user_id,
            "topicId": tid,
            "topic": lesson.topic,
            "source": "topic",
            "difficulty": body.difficulty,
            "provider": body.provider,
            "model": body.model,
            "input": {"content": body.content},
            "learningContent": data,
            "evaluation": {"completed": False},
            "createdAt": now(),
        }
    )
    db.topics.update_one(
        {"_id": tid, "userId": user_id},
        {
            "$setOnInsert": {
                "name": lesson.topic,
                "firstStudied": now(),
                "summary": lesson.explanation.overview[:240],
                "keyConcepts": [s.title for s in lesson.explanation.sections],
                "progress": {"score": 0, "level": "New", "sessionsCompleted": 0},
            },
            "$addToSet": {"sessionIds": sid},
            "$set": {"lastStudied": now()},
        },
        upsert=True,
    )
    return {"sessionId": sid, "topic": lesson.topic, "learningContent": data}


@app.post("/api/learn/document")
async def learn_document(
    file: UploadFile = File(...),
    difficulty: str = Form("beginner"),
    provider: str = Form("groq"),
    model: str = Form("qwen/qwen3.8-27b"),
    instructions: str = Form(""),
    user: dict = Depends(current_user),
):
    if not file.filename:
        raise err(400, "unsupported_file", "No document file was provided.")
    raw = await file.read()
    if not raw or not raw.strip():
        raise err(400, "empty_document", "The uploaded document is empty.")
    try:
        document = DocumentProcessingService.process_uploaded_document(
            filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
            file_bytes=raw,
            source_name=file.filename,
        )
    except UnsupportedDocumentError as exc:
        raise err(400, "unsupported_file", str(exc))
    except EmptyDocumentError as exc:
        raise err(400, "empty_document", str(exc))
    except ValueError as exc:
        raise err(400, "unreadable_document", str(exc))

    source_text = DocumentProcessingService.build_context_for_llm(document)
    if not source_text.strip():
        raise err(400, "unreadable_document", "No readable text could be extracted from this document, even after OCR.")

    prompt = (
        "You are CURIOSITY, an AI learning assistant. "
        "The uploaded document is the primary source of truth. "
        "Do not invent facts that are not supported by the document. "
        "Preserve important terminology, concepts, formulas, examples, and structure from the source. "
        "Adapt the explanation to the selected difficulty while prioritizing understanding over copying.\n\n"
        f"Document title: {document.title}\n"
        f"Difficulty: {difficulty}\n"
        f"Instructions: {instructions.strip() if instructions else 'None'}\n\n"
        f"Document source content:\n{source_text}"
    )
    try:
        lesson = generate_lesson(prompt, difficulty, provider, model)
    except LLMError as e:
        raise err(504 if e.code == "timeout" else 502, e.code, e.message)

    sid = f"session_{uuid.uuid4().hex[:12]}"
    title = lesson.topic or document.title
    topic_key = "doc_" + re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    tid = user_topic_id(topic_key, user["id"])
    metadata = DocumentProcessingService.document_metadata(document)
    data = lesson.model_dump()
    db.sessions.insert_one(
        {
            "_id": sid,
            "userId": user["id"],
            "topicId": tid,
            "topic": title,
            "source": "document",
            "difficulty": difficulty,
            "provider": provider,
            "model": model,
            "document": metadata,
            "input": {
                "content": source_text,
                "instructions": instructions,
                "document": True,
                "filename": metadata["filename"],
                "title": metadata["title"],
            },
            "learningContent": data,
            "evaluation": {"completed": False},
            "createdAt": now(),
        }
    )
    db.topics.update_one(
        {"_id": tid, "userId": user["id"]},
        {
            "$setOnInsert": {
                "name": title,
                "firstStudied": now(),
                "summary": lesson.explanation.overview[:240],
                "keyConcepts": [s.title for s in lesson.explanation.sections],
                "progress": {"score": 0, "level": "New", "sessionsCompleted": 0},
            },
            "$addToSet": {"sessionIds": sid},
            "$set": {"lastStudied": now()},
        },
        upsert=True,
    )
    return {
        "sessionId": sid,
        "topic": title,
        "learningContent": data,
        "document": metadata,
    }


@app.post("/api/learn/stream")
def learn_stream(body: LearnIn, user: dict = Depends(current_user)):
    generation_content = body.content
    classroom_context = None
    if body.classroomId and body.curriculumTopicId:
        classroom, module, topic = classroom_topic_learning_context(
            body.classroomId, body.curriculumTopicId, user
        )
        classroom_context = (classroom, module, topic)
        learning_path = classroom_progress(body.classroomId, user)["learningPath"]
        generation_content = render_classroom_learning_prompt(
            body.content, classroom, module, topic, learning_path
        )

    def events():
        yield 'data: {"stage":"understanding"}\n\n'
        try:
            lesson = generate_lesson(generation_content, body.difficulty, body.provider, body.model)
            yield 'data: {"stage":"building"}\n\n'
            sid = f"session_{uuid.uuid4().hex[:12]}"
            topic_key = "topic_" + re.sub(
                r"[^a-z0-9]+", "_", lesson.topic.lower()
            ).strip("_")
            tid = user_topic_id(topic_key, user["id"])
            data = lesson.model_dump()
            db.sessions.insert_one(
                {
                    "_id": sid,
                    "userId": user["id"],
                    "topicId": tid,
                    "topic": lesson.topic,
                    "difficulty": body.difficulty,
                    "provider": body.provider,
                    "model": body.model,
                    "input": {"content": body.content},
                    **(
                        {
                            "classroomId": classroom["id"],
                            "curriculumTopicId": topic["_id"],
                            "curriculumModuleId": module.get("_id"),
                            "concepts": [item["name"] for item in topic.get("concepts", [])],
                        }
                        if classroom_context
                        else {}
                    ),
                    "learningContent": data,
                    "evaluation": {"completed": False},
                    "createdAt": now(),
                }
            )
            db.topics.update_one(
                {"_id": tid, "userId": user["id"]},
                {
                    "$setOnInsert": {
                        "name": lesson.topic,
                        "firstStudied": now(),
                        "summary": lesson.explanation.overview[:240],
                        "keyConcepts": [s.title for s in lesson.explanation.sections],
                        "progress": {"score": 0, "level": "New", "sessionsCompleted": 0},
                    },
                    "$addToSet": {"sessionIds": sid},
                    "$set": {"lastStudied": now()},
                },
                upsert=True,
            )
            yield 'data: {"stage":"ready"}\n\n'
            yield f"data: {json.dumps({'sessionId': sid, 'topic': lesson.topic, 'learningContent': data})}\n\n"
        except LLMError as error:
            yield f"data: {json.dumps({'error': error.code, 'message': error.message})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


def recompute_stats(user_id):
    done = list(db.sessions.find({"userId": user_id, "evaluation.completed": True}))
    stats = {
        "topicsStudied": db.topics.count_documents({"userId": user_id}),
        "sessionsCompleted": len(done),
        "quizzesCompleted": len(done),
        "averageScore": (
            round(sum(d["evaluation"]["score"] for d in done) / len(done))
            if done
            else 0
        ),
        "cardsReviewed": sum(d.get("cardsReviewed", 0) for d in done),
    }
    db.users.update_one({"_id": user_id}, {"$set": {"stats": stats}})
    return stats


@app.post("/api/sessions/{sid}/complete")
def complete(sid: str, body: CompleteIn, user: dict = Depends(current_user)):
    user_id = user["id"]
    s = db.sessions.find_one({"_id": sid, "userId": user_id})
    if not s:
        raise err(404, "not_found", "Session not found.")
    score = round(body.correct / body.total * 100)
    ev = {
        "score": score,
        "correct": body.correct,
        "incorrect": body.incorrect,
        "total": body.total,
        "completed": True,
    }
    db.sessions.update_one(
        {"_id": sid},
        {
            "$set": {
                "evaluation": ev,
                "answers": body.answers,
                "cardsReviewed": body.cardsReviewed,
                "completedAt": now(),
            }
        },
    )
    if s.get("classroomId") and s.get("curriculumTopicId"):
        db.learning_events.update_one(
            {"_id": f"learning_event_{sid}"},
            {
                "$set": {
                    "userId": user_id,
                    "classroomId": s["classroomId"],
                    "moduleId": s.get("curriculumModuleId"),
                    "topicId": s["curriculumTopicId"],
                    "concepts": s.get("concepts", []),
                    "activityType": "curiosity_quiz",
                    "evidenceType": "assessment",
                    "sourceSessionId": sid,
                    "score": score,
                    "maxScore": 100,
                    "masteryScore": score,
                    "coverage": True,
                    "attempt": 1,
                    "evaluationStatus": "complete",
                    "occurredAt": s.get("completedAt", now()),
                },
                "$setOnInsert": {"createdAt": now()},
            },
            upsert=True,
        )
        classroom_progress(s["classroomId"], user)
    done = list(
        db.sessions.find(
            {"userId": user_id, "topicId": s["topicId"], "evaluation.completed": True},
            {"evaluation.score": 1},
        )
    )
    avg = round(sum(d["evaluation"]["score"] for d in done) / len(done))
    db.topics.update_one(
        {"_id": s["topicId"]},
        {
            "$set": {
                "progress": {
                    "score": avg,
                    "level": level(avg),
                    "sessionsCompleted": len(done),
                },
                "lastStudied": now(),
            }
        },
    )
    return {"evaluation": ev, "topicProgress": avg, "stats": recompute_stats(user_id)}


@app.post("/api/topics/{tid}/retest")
def retest(tid: str, user: dict = Depends(current_user)):
    user_id = user["id"]
    topic = db.topics.find_one({"_id": tid, "userId": user_id})
    if not topic:
        raise err(404, "not_found", "Topic not found.")
    retests_used = db.sessions.count_documents(
        {"userId": user_id, "topicId": tid, "input.retest": True}
    )
    if retests_used >= 3:
        raise err(409, "retest_limit", "You have used all 3 retests for this topic.")

    source = db.sessions.find_one(
        {"userId": user_id, "topicId": tid},
        sort=[("createdAt", -1)],
    )
    if not source:
        raise err(404, "not_found", "No lesson found for this topic.")

    content = source.get("input", {}).get("content") or source.get("topic", tid)
    provider = source.get("provider", "groq")
    model = source.get("model", "qwen/qwen3.8-27b")
    existing_questions = [
        question.get("question", "")
        for session in db.sessions.find(
            {"userId": user_id, "topicId": tid}, {"learningContent.quiz": 1}
        )
        for question in session.get("learningContent", {}).get("quiz", [])
        if isinstance(question, dict)
    ]
    existing_questions = list(dict.fromkeys(existing_questions))[-30:]
    try:
        quiz = generate_retest_quiz(content, existing_questions, provider, model)
    except LLMError as e:
        raise err(504 if e.code == "timeout" else 502, e.code, e.message)

    learning_content = dict(source["learningContent"])
    previous_quiz = []
    seen_questions = set()
    for session in db.sessions.find(
        {"userId": user_id, "topicId": tid}, {"learningContent.quiz": 1}
    ):
        for question in session.get("learningContent", {}).get("quiz", []):
            if not isinstance(question, dict):
                continue
            question_text = question.get("question", "")
            if question_text and question_text not in seen_questions:
                seen_questions.add(question_text)
                previous_quiz.append(question)
    new_quiz = [
        question.model_copy(
            update={"id": f"retest-{uuid.uuid4().hex[:10]}-{index}"}
        ).model_dump()
        for index, question in enumerate(quiz, start=1)
    ]
    learning_content["quiz"] = previous_quiz + new_quiz
    sid = f"session_{uuid.uuid4().hex[:12]}"
    db.sessions.insert_one(
        {
            "_id": sid,
            "userId": user_id,
            "topicId": tid,
            "topic": topic["name"],
            "difficulty": source.get("difficulty", "beginner"),
            "provider": provider,
            "model": model,
            "input": {"content": content, "retest": True},
            "learningContent": learning_content,
            "evaluation": {"completed": False},
            "createdAt": now(),
        }
    )
    db.topics.update_one(
        {"_id": tid, "userId": user_id},
        {
            "$addToSet": {"sessionIds": sid},
            "$set": {"lastStudied": now(), "retestsUsed": retests_used + 1},
        },
    )
    return {"sessionId": sid, "topic": topic["name"], "learningContent": learning_content}


@app.get("/api/sessions")
def sessions(user: dict = Depends(current_user)):
    rows = db.sessions.find(
        {"userId": user["id"]}, {"learningContent": 0, "input": 0, "answers": 0}
    ).sort("createdAt", -1)
    topic_retests = {
        topic["_id"]: db.sessions.count_documents(
            {"userId": user["id"], "topicId": topic["_id"], "input.retest": True}
        )
        for topic in db.topics.find({"userId": user["id"]}, {"_id": 1})
    }
    result = []
    for row in rows:
        item = out(row)
        item["retestsUsed"] = topic_retests.get(item.get("topicId"), 0)
        result.append(item)
    return result


@app.get("/api/sessions/{sid}")
def session(sid: str, user: dict = Depends(current_user)):
    s = db.sessions.find_one({"_id": sid, "userId": user["id"]})
    if not s:
        raise err(404, "not_found", "Session not found.")
    return out(s)


@app.post("/api/sessions/{sid}/refine")
def refine(sid: str, body: RefineIn, user: dict = Depends(current_user)):
    saved = db.sessions.find_one({"_id": sid, "userId": user["id"]})
    if not saved:
        raise err(404, "not_found", "Session not found.")
    try:
        lesson = refine_lesson(
            saved["learningContent"],
            body.prompt,
            saved.get("provider", "groq"),
            saved.get("model", "qwen/qwen3.8-27b"),
        )
    except LLMError as e:
        raise err(504 if e.code == "timeout" else 502, e.code, e.message)
    data = lesson.model_dump()
    db.sessions.update_one(
        {"_id": sid, "userId": user["id"]},
        {"$set": {"learningContent": data, "updatedAt": now()}},
    )
    if saved.get("source") == "document":
        doc = saved.get("document") or {}
        prompt_text = (
            f"Use the uploaded document as the primary source of truth. "
            f"Document title: {doc.get('title', 'Uploaded document')}. "
            f"Question: {body.prompt}\n\n"
            f"Document source excerpt:\n{saved.get('input', {}).get('content', '')}"
        )
        try:
            lesson = refine_lesson(saved["learningContent"], prompt_text, saved.get("provider", "groq"), saved.get("model", "qwen/qwen3.8-27b"))
            data = lesson.model_dump()
            db.sessions.update_one(
                {"_id": sid, "userId": user["id"]},
                {"$set": {"learningContent": data, "updatedAt": now()}},
            )
            return {"sessionId": sid, "learningContent": data}
        except LLMError as e:
            raise err(504 if e.code == "timeout" else 502, e.code, e.message)
    return {"sessionId": sid, "learningContent": data}


@app.get("/api/admin/users")
def admin_list_users(user: dict = Depends(current_user)):
    return list_platform_users(user)


@app.post("/api/admin/users/{user_id}/role")
def admin_update_user_role(user_id: str, body: UserRoleUpdateIn, user: dict = Depends(current_user)):
    return update_user_role(user_id, body.model_dump(), user)


@app.get("/api/classrooms")
def list_classrooms_route(user: dict = Depends(current_user)):
    return list_classrooms(user)


@app.post("/api/classrooms")
def create_classroom_route(body: dict, user: dict = Depends(current_user)):
    return create_classroom(body, user)


@app.delete("/api/classrooms/{classroom_id}")
def delete_classroom_route(classroom_id: str, user: dict = Depends(current_user)):
    return delete_classroom(classroom_id, user)


@app.post("/api/classrooms/join")
def join_classroom_route(body: dict, user: dict = Depends(current_user)):
    return join_classroom(body, user)


@app.get("/api/classrooms/{classroom_id}")
def get_classroom_route(classroom_id: str, user: dict = Depends(current_user)):
    return get_classroom(classroom_id, user)


@app.get("/api/classrooms/{classroom_id}/curriculum")
def get_classroom_curriculum_route(classroom_id: str, user: dict = Depends(current_user)):
    return get_classroom_curriculum(classroom_id, user)


@app.get("/api/classrooms/{classroom_id}/progress")
def classroom_progress_route(classroom_id: str, user: dict = Depends(current_user)):
    return classroom_progress(classroom_id, user)


@app.get("/api/classrooms/{classroom_id}/analytics")
def classroom_analytics_route(classroom_id: str, user: dict = Depends(current_user)):
    return classroom_analytics(classroom_id, user)


@app.get("/api/classrooms/{classroom_id}/graph")
def classroom_graph_route(
    classroom_id: str,
    student_id: str | None = None,
    user: dict = Depends(current_user),
):
    return classroom_knowledge_graph(classroom_id, user, student_id)


@app.get("/api/classrooms/{classroom_id}/stream")
def classroom_stream_route(classroom_id: str, user: dict = Depends(current_user)):
    return list_classroom_posts(classroom_id, user)


@app.post("/api/classrooms/{classroom_id}/stream")
def create_classroom_post_route(
    classroom_id: str,
    body: ClassroomPostIn,
    user: dict = Depends(current_user),
):
    return create_classroom_post(classroom_id, body, user)


@app.post("/api/classrooms/{classroom_id}/stream/{post_id}/replies")
def create_classroom_reply_route(
    classroom_id: str,
    post_id: str,
    body: ClassroomReplyIn,
    user: dict = Depends(current_user),
):
    return create_classroom_reply(classroom_id, post_id, body, user)


@app.post("/api/classrooms/{classroom_id}/modules")
def create_curriculum_module_route(
    classroom_id: str,
    body: CurriculumModuleIn,
    user: dict = Depends(current_user),
):
    return create_curriculum_module(classroom_id, body, user)


@app.post("/api/classrooms/{classroom_id}/modules/{module_id}/topics")
def create_curriculum_topic_route(
    classroom_id: str,
    module_id: str,
    body: CurriculumTopicIn,
    user: dict = Depends(current_user),
):
    return create_curriculum_topic(classroom_id, module_id, body, user)


@app.get("/api/classrooms/{classroom_id}/classwork")
def list_classroom_assessments_route(classroom_id: str, user: dict = Depends(current_user)):
    return list_classroom_assessments(classroom_id, user)


@app.post("/api/classrooms/{classroom_id}/classwork")
def create_classroom_assessment_route(
    classroom_id: str,
    body: ClassroomAssessmentIn,
    user: dict = Depends(current_user),
):
    return create_classroom_assessment(classroom_id, body, user)


@app.post("/api/classrooms/{classroom_id}/classwork/{assessment_id}/submissions")
def submit_classroom_assessment_route(
    classroom_id: str,
    assessment_id: str,
    body: ClassroomSubmissionIn,
    user: dict = Depends(current_user),
):
    return submit_classroom_assessment(classroom_id, assessment_id, body, user)


@app.get("/api/classrooms/{classroom_id}/classwork/{assessment_id}/submissions")
def list_classroom_submissions_route(
    classroom_id: str,
    assessment_id: str,
    user: dict = Depends(current_user),
):
    return list_classroom_submissions(classroom_id, assessment_id, user)


@app.patch("/api/classrooms/{classroom_id}/classwork/{assessment_id}/submissions/{submission_id}")
def grade_classroom_submission_route(
    classroom_id: str,
    assessment_id: str,
    submission_id: str,
    body: ClassroomGradeIn,
    user: dict = Depends(current_user),
):
    return grade_classroom_submission(classroom_id, assessment_id, submission_id, body, user)


@app.post("/api/classrooms/{classroom_id}/classwork/{assessment_id}/submissions/{submission_id}/evaluate")
def evaluate_classroom_submission_route(
    classroom_id: str,
    assessment_id: str,
    submission_id: str,
    user: dict = Depends(current_user),
):
    return evaluate_classroom_submission(classroom_id, assessment_id, submission_id, user)


@app.get("/api/profile")
def profile(user: dict = Depends(current_user)):
    user_id = user["id"]
    u = out(db.users.find_one({"_id": user_id}))
    u["role"] = normalize_role(u.get("role"))
    topics = []
    for topic in db.topics.find(
        {"userId": user_id, "progress.sessionsCompleted": {"$gt": 0}}
    ):
        item = out(topic)
        item["retestsUsed"] = db.sessions.count_documents(
            {"userId": user_id, "topicId": item["id"], "input.retest": True}
        )
        topics.append(item)
    return {
        **u,
        "role": normalize_role(u.get("role")),
        "strong": [t for t in topics if t["progress"]["score"] >= 80],
        "needsReview": [t for t in topics if t["progress"]["score"] < 70],
        "recent": [
            out(r)
            for r in db.sessions.find(
                {"userId": user_id}, {"learningContent": 0, "input": 0, "answers": 0}
            )
            .sort("createdAt", -1)
            .limit(5)
        ],
    }


@app.get("/api/topics")
def topics(user: dict = Depends(current_user)):
    return [
        out(t) for t in db.topics.find({"userId": user["id"]}).sort("lastStudied", -1)
    ]


@app.get("/api/topics/{tid}")
def topic(tid: str, user: dict = Depends(current_user)):
    t = db.topics.find_one({"_id": tid, "userId": user["id"]})
    if not t:
        raise err(404, "not_found", "Topic not found.")
    t = out(t)
    t["history"] = [
        out(s)
        for s in db.sessions.find(
            {"_id": {"$in": t.get("sessionIds", [])}, "evaluation.completed": True},
            {"evaluation": 1, "createdAt": 1},
        ).sort("createdAt", -1)
    ]
    return t


@app.get("/api/graph")
def graph(user: dict = Depends(current_user)):
    ts = list(db.topics.find({"userId": user["id"]}))
    return {
        "nodes": [
            {
                "id": t["_id"],
                "label": t["name"],
                "progress": (
                    t["progress"]["score"]
                    if t["progress"]["sessionsCompleted"]
                    else None
                ),
                "sessions": len(t.get("sessionIds", [])),
            }
            for t in ts
        ],
        "edges": [],
    }


# Keep CORS outside FastAPI's error handling so even server errors carry CORS headers.
app = CORSMiddleware(
    app=app,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
