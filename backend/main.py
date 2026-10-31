import base64
import hashlib
import json
import logging
import os, re, secrets, uuid
from threading import Timer
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database import current_session, reset_request_session, session_factory, session_scope, set_request_session
from persistence import db
from orm_models import TopicSession

from models import (
    ClassroomAssessmentIn,
    ClassroomCreateIn,
    ClassroomGradeIn,
    ClassroomLectureIn,
    ClassroomLectureProgressIn,
    ClassroomLectureUpdateIn,
    ClassroomMaterialUpdateIn,
    ClassroomMemberAddIn,
    ClassroomMemberRoleUpdateIn,
    ClassroomPostIn,
    ClassroomReplyIn,
    ClassroomSubmissionIn,
    CompleteIn,
    CurriculumConceptIn,
    CurriculumDraftApplyIn,
    CurriculumDraftModuleIn,
    CurriculumGenerateIn,
    CurriculumMaterialIn,
    CurriculumModuleIn,
    CurriculumTopicIn,
    GoogleAuthIn,
    LearnIn,
    RefineIn,
    UserRoleUpdateIn,
)
from video_helper import parse_video_url
from llm import generate_curriculum, generate_lesson, generate_retest_quiz, refine_lesson, LLMError
from document_processor.service import DocumentProcessingService
from document_processor.parser import EmptyDocumentError, UnsupportedDocumentError
from mastery import build_classroom_analytics, build_student_progress
from adaptive import build_adaptive_path, revision_task_specs
from evaluation import evaluate_written_answer
from assessment import AssessmentValidationError, grade_quiz

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
FRONTEND_ORIGIN_REGEX = os.getenv("FRONTEND_ORIGIN_REGEX", "").strip() or None
if FRONTEND_ORIGIN_REGEX:
    re.compile(FRONTEND_ORIGIN_REGEX)
app = FastAPI(title="AI Learning Assistant")
logger = logging.getLogger("uvicorn.error")
SESSION_COOKIE = "curiosity_session"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "1209600"))
SESSION_COOKIE_DOMAIN = os.getenv("SESSION_COOKIE_DOMAIN", "").strip() or None
_cookie_secure = os.getenv("SESSION_COOKIE_SECURE")
SESSION_COOKIE_SECURE = (
    _cookie_secure.lower() in {"1", "true", "yes"}
    if _cookie_secure is not None
    else os.getenv("APP_ENV", "development").lower() != "development"
    or any(origin.startswith("https://") for origin in FRONTEND_ORIGINS)
)
SESSION_COOKIE_SAMESITE = os.getenv(
    "SESSION_COOKIE_SAMESITE", "none" if SESSION_COOKIE_SECURE else "lax"
).strip().lower()
if SESSION_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    raise ValueError("SESSION_COOKIE_SAMESITE must be Lax, Strict, or None.")
if SESSION_COOKIE_SAMESITE == "none" and not SESSION_COOKIE_SECURE:
    raise ValueError("SameSite=None cookies require SESSION_COOKIE_SECURE=true.")
CLASSROOM_UNDO_SECONDS = 5
_classroom_delete_timers: dict[str, Timer] = {}


def session_cookie_settings():
    settings = {
        "httponly": True,
        "secure": SESSION_COOKIE_SECURE,
        "samesite": SESSION_COOKIE_SAMESITE,
        "path": "/",
        "max_age": SESSION_TTL_SECONDS,
    }
    if SESSION_COOKIE_DOMAIN:
        settings["domain"] = SESSION_COOKIE_DOMAIN
    return settings


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


app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_origin_regex=FRONTEND_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _origin_allowed(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        normalized = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    except ValueError:
        return False
    return normalized in FRONTEND_ORIGINS or bool(
        FRONTEND_ORIGIN_REGEX and re.fullmatch(FRONTEND_ORIGIN_REGEX, normalized)
    )


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    with session_scope() as session:
        token = set_request_session(session)
        try:
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                origin = request.headers.get("origin")
                referer = request.headers.get("referer")
                source = origin or (f"{urlsplit(referer).scheme}://{urlsplit(referer).netloc}" if referer else None)
                if source and not _origin_allowed(source):
                    session.rollback()
                    return JSONResponse(
                        status_code=403,
                        content={"detail": {"code": "origin_forbidden", "message": "This request origin is not allowed."}},
                    )

            if (
                request.method in {"POST", "PUT", "PATCH", "DELETE"}
                and request.url.path not in {"/api/auth/google", "/api/auth/guest", "/api/auth/logout"}
                and request.cookies.get(SESSION_COOKIE)
            ):
                session_id = request.cookies.get(SESSION_COOKIE)
                csrf_token = request.headers.get("X-CSRF-Token")
                if not await run_in_threadpool(is_valid_csrf_token, session_id, csrf_token):
                    session.rollback()
                    return JSONResponse(
                        status_code=403,
                        content={"detail": {"code": "csrf_invalid", "message": "Invalid or missing CSRF token."}},
                    )
            response = await call_next(request)
            if response.status_code >= 400:
                session.rollback()
            if response.status_code == 401 and request.cookies.get(SESSION_COOKIE):
                response.delete_cookie(
                    key=SESSION_COOKIE,
                    path="/",
                    secure=SESSION_COOKIE_SECURE,
                    samesite=SESSION_COOKIE_SAMESITE,
                    domain=SESSION_COOKIE_DOMAIN,
                )
            return response
        finally:
            reset_request_session(token)


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


def require_role(user: dict | None, *allowed_roles: str):
    if user is None:
        raise err(401, "auth_required", "Sign in with Google to continue.")
    role = normalize_role(user.get("role"))
    if allowed_roles and role not in set(allowed_roles):
        raise err(403, "forbidden", "You do not have permission to perform this action.")
    return role


def _classroom_editor(classroom: dict, user: dict) -> bool:
    role = normalize_role(user.get("role"))
    return role == "ADMIN" or classroom.get("ownerId") == user["id"] or (
        role == "FACULTY" and user["id"] in classroom.get("facultyIds", [])
    )


def classroom_payload(doc: dict, include_email: bool = True) -> dict:
    payload = {key: value for key, value in doc.items() if key != "_id"}
    payload["id"] = str(doc["_id"])
    members = doc.get("members", [])
    payload["memberCount"] = len(members)
    user_ids = [m.get("userId") for m in members if m.get("userId")]
    user_docs = {
        u["_id"]: u
        for u in db.users.find({"_id": {"$in": user_ids}})
    } if user_ids else {}
    enriched_members = []
    for member in members:
        uid = member.get("userId")
        user_doc = user_docs.get(uid) or {}
        role = member.get("role", "STUDENT")
        if uid == doc.get("ownerId") and role != "OWNER":
            role = "OWNER"
        m_data = {
            "userId": uid,
            "role": role,
            "joinedAt": member.get("joinedAt"),
            "name": user_doc.get("name") or "Class member",
            "picture": user_doc.get("picture") or "",
            "userRole": normalize_role(user_doc.get("role")),
            "createdAt": user_doc.get("createdAt"),
            "status": "Active",
        }
        if include_email:
            m_data["email"] = user_doc.get("email") or ""
        enriched_members.append(m_data)
    payload["members"] = enriched_members
    payload["status"] = doc.get("status", "active")
    owner = db.users.find_one({"_id": doc.get("ownerId")}) if doc.get("ownerId") else None
    if owner:
        payload["ownerName"] = owner.get("name", "Teacher")
    return payload


def create_classroom(payload: dict, user: dict):
    require_role(user, "ADMIN", "FACULTY", "STUDENT")
    fields = {key: str(payload.get(key, "")).strip() for key in ("name", "subject", "section", "semester", "description")}
    if not all(fields[key] for key in ("name", "subject", "section", "semester")):
        raise err(400, "invalid_classroom", "Classroom name, subject, section, and semester are required.")
    join_code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    while db.classrooms.find_one({"joinCode": join_code}):
        join_code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    created_at = now_iso()
    classroom = {
        "_id": f"classroom_{uuid.uuid4().hex[:12]}", **fields,
        "ownerId": user["id"], "facultyIds": [], "joinCode": join_code,
        "status": "active", "curriculumStatus": "draft", "curriculumVersion": 0,
        "createdAt": created_at, "updatedAt": created_at,
        "members": [{"userId": user["id"], "role": "OWNER", "joinedAt": created_at}],
    }
    db.classrooms.insert_one(classroom)
    return classroom_payload(classroom, include_email=False)


def _purge_classroom_data(classroom_id: str):
    for name in ("classroom_modules", "classroom_curriculum_topics", "classroom_assessments", "classroom_submissions", "classroom_posts", "classroom_replies", "learning_events", "learning_paths", "adaptive_tasks"):
        getattr(db, name).delete_many({"classroomId": classroom_id})
    db.classrooms.delete_one({"_id": classroom_id, "deletionState": "purging"})
    _classroom_delete_timers.pop(classroom_id, None)


def finalize_classroom_delete(classroom_id: str, token: str):
    with session_scope():
        claim = db.classrooms.update_one(
            {"_id": classroom_id, "deletionToken": token, "deletionState": "pending"},
            {"$set": {"deletionState": "purging"}},
        )
        if claim.matched_count:
            _purge_classroom_data(classroom_id)


def _schedule_classroom_delete(classroom_id: str, token: str, delay: float = CLASSROOM_UNDO_SECONDS):
    previous = _classroom_delete_timers.pop(classroom_id, None)
    if previous:
        previous.cancel()
    timer = Timer(max(delay, 0.01), finalize_classroom_delete, args=(classroom_id, token))
    timer.daemon = True
    _classroom_delete_timers[classroom_id] = timer
    timer.start()


def _recover_classroom_deletions():
    current_time = now()
    for classroom in db.classrooms.find({"deletionState": "pending"}):
        deadline = classroom.get("deleteUntil")
        if not isinstance(deadline, datetime):
            continue
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        token = classroom.get("deletionToken")
        if not token:
            continue
        if deadline <= current_time:
            finalize_classroom_delete(classroom["_id"], token)
        elif classroom["_id"] not in _classroom_delete_timers:
            _schedule_classroom_delete(classroom["_id"], token, (deadline - current_time).total_seconds())


def delete_classroom(classroom_id: str, user: dict):
    classroom = db.classrooms.find_one({"_id": classroom_id})
    if not classroom:
        raise err(404, "not_found", "Classroom not found.")
    require_role(user, "ADMIN", "FACULTY", "STUDENT")
    if classroom.get("ownerId") != user["id"]:
        raise err(403, "forbidden", "Only the classroom owner can delete it.")
    if classroom.get("deletionState") == "pending":
        raise err(409, "deletion_pending", "This classroom is already waiting for deletion.")
    token = uuid.uuid4().hex
    delete_until = now() + timedelta(seconds=CLASSROOM_UNDO_SECONDS)
    db.classrooms.update_one(
        {"_id": classroom_id},
        {"$set": {"deletionState": "pending", "deletionToken": token, "deleteUntil": delete_until}},
    )
    _schedule_classroom_delete(classroom_id, token)
    return {"deleted": True, "id": classroom_id, "undoToken": token, "undoSeconds": CLASSROOM_UNDO_SECONDS}


def undo_delete_classroom(classroom_id: str, token: str, user: dict):
    classroom = db.classrooms.find_one({"_id": classroom_id, "deletionToken": token, "deletionState": "pending"})
    if not classroom:
        raise err(404, "undo_expired", "The undo period has ended or this classroom is no longer available.")
    if classroom.get("ownerId") != user["id"]:
        raise err(403, "forbidden", "Only the classroom owner can restore it.")
    deadline = classroom.get("deleteUntil")
    if isinstance(deadline, datetime) and deadline <= now():
        finalize_classroom_delete(classroom_id, token)
        raise err(410, "undo_expired", "The undo period has ended.")
    restored = db.classrooms.update_one(
        {"_id": classroom_id, "deletionToken": token, "deletionState": "pending"},
        {"$set": {"deletionState": "active", "deletionToken": None, "deleteUntil": None, "updatedAt": now_iso()}},
    )
    if restored.matched_count == 0:
        raise err(410, "undo_expired", "The undo period has ended.")
    timer = _classroom_delete_timers.pop(classroom_id, None)
    if timer:
        timer.cancel()
    return classroom_payload(db.classrooms.find_one({"_id": classroom_id}))


def update_classroom(classroom_id: str, payload: dict, user: dict):
    classroom = require_classroom_editor(classroom_id, user)
    fields = {key: str(payload.get(key, "")).strip() for key in ("name", "subject", "section", "semester", "description")}
    if not all(fields[key] for key in ("name", "subject", "section", "semester")):
        raise err(400, "invalid_classroom", "Classroom name, subject, section, and semester are required.")
    db.classrooms.update_one({"_id": classroom_id}, {"$set": {**fields, "updatedAt": now_iso()}})
    return classroom_payload(db.classrooms.find_one({"_id": classroom_id}) or classroom)


def list_classrooms(user: dict):
    role = require_role(user, "ADMIN", "FACULTY", "STUDENT")
    _recover_classroom_deletions()
    result = []
    for row in db.classrooms.find({}):
        if row.get("deletionState") == "pending":
            continue
        if role == "ADMIN" or row.get("ownerId") == user["id"] or any(m.get("userId") == user["id"] for m in row.get("members", [])):
            item = classroom_payload(row)
            if not _classroom_editor(row, user):
                item.pop("joinCode", None)
            result.append(item)
    return sorted(result, key=lambda item: item.get("createdAt", ""), reverse=True)


def get_classroom(classroom_id: str, user: dict):
    classroom = db.classrooms.find_one({"_id": classroom_id})
    if not classroom or classroom.get("deletionState") == "pending":
        raise err(404, "not_found", "Classroom not found.")
    role = require_role(user, "ADMIN", "FACULTY", "STUDENT")
    member = any(m.get("userId") == user["id"] for m in classroom.get("members", []))
    if role != "ADMIN" and classroom.get("ownerId") != user["id"] and not member:
        raise err(403, "forbidden", "You do not have access to this classroom.")
    result = classroom_payload(classroom)
    if not _classroom_editor(classroom, user):
        result.pop("joinCode", None)
    return result


def require_classroom_editor(classroom_id: str, user: dict):
    classroom = db.classrooms.find_one({"_id": classroom_id})
    if not classroom or classroom.get("deletionState") == "pending":
        raise err(404, "not_found", "Classroom not found.")
    require_role(user, "ADMIN", "FACULTY", "STUDENT")
    if not _classroom_editor(classroom, user):
        raise err(403, "forbidden", "Only the classroom owner or authorized faculty can edit it.")
    return classroom


def require_classroom_owner(classroom_id: str, user: dict):
    classroom = db.classrooms.find_one({"_id": classroom_id})
    if not classroom or classroom.get("deletionState") == "pending":
        raise err(404, "not_found", "Classroom not found.")
    role = require_role(user, "ADMIN", "FACULTY", "STUDENT")
    if role != "ADMIN" and classroom.get("ownerId") != user["id"]:
        raise err(403, "forbidden", "Only the classroom owner can perform this administrative action.")
    return classroom


def get_classroom_members(classroom_id: str, user: dict):
    classroom = get_classroom(classroom_id, user)
    return {
        "classroomId": classroom_id,
        "members": classroom.get("members", []),
        "ownerId": classroom.get("ownerId"),
        "joinCode": classroom.get("joinCode"),
        "memberCount": len(classroom.get("members", [])),
    }


def add_classroom_member(classroom_id: str, payload: dict, user: dict):
    classroom = require_classroom_owner(classroom_id, user)
    email = str(payload.get("email") or "").strip().lower()
    user_id = str(payload.get("userId") or "").strip()
    role = str(payload.get("role") or "STUDENT").strip().upper()
    if role not in {"STUDENT", "ASSISTANT"}:
        role = "STUDENT"

    target_user = None
    if email:
        target_user = db.users.find_one({"email": email})
    elif user_id:
        target_user = db.users.find_one({"_id": user_id})

    if not target_user:
        raise err(
            404,
            "user_not_found",
            f"No registered user found with email '{email}'. The user must sign in to Curiosity first, or you can share the classroom join code ({classroom.get('joinCode', '')}).",
        )

    target_id = target_user["_id"]
    current_members = list(classroom.get("members", []))
    if any(m.get("userId") == target_id for m in current_members):
        raise err(409, "already_member", f"{target_user.get('name', 'This user')} is already a member of this classroom.")

    created_at = now_iso()
    if hasattr(db, "add_member"):
        db.add_member(classroom_id, target_id, role, created_at)
    else:
        current_members.append({"userId": target_id, "role": role, "joinedAt": created_at})
        db.classrooms.update_one({"_id": classroom_id}, {"$set": {"members": current_members, "updatedAt": created_at}})

    faculty_ids = list(classroom.get("facultyIds") or [])
    if role == "ASSISTANT":
        if target_id not in faculty_ids:
            faculty_ids.append(target_id)
            db.classrooms.update_one({"_id": classroom_id}, {"$set": {"facultyIds": faculty_ids}})

    updated_classroom = db.classrooms.find_one({"_id": classroom_id})
    return classroom_payload(updated_classroom)


def update_classroom_member_role(classroom_id: str, target_user_id: str, payload: dict, user: dict):
    classroom = require_classroom_owner(classroom_id, user)
    new_role = str(payload.get("role") or "").strip().upper()
    if new_role not in {"STUDENT", "ASSISTANT", "OWNER"}:
        raise err(400, "invalid_role", "Classroom role must be STUDENT, ASSISTANT, or OWNER.")

    current_members = list(classroom.get("members", []))
    target_member = next((m for m in current_members if m.get("userId") == target_user_id), None)
    if not target_member:
        raise err(404, "not_found", "User is not a member of this classroom.")

    if target_user_id == classroom.get("ownerId") and new_role != "OWNER":
        other_owners = [
            m for m in current_members
            if m.get("userId") != target_user_id and m.get("role") == "OWNER"
        ]
        if not other_owners:
            raise err(400, "sole_owner", "There must always be at least one classroom owner. Promote another member to Owner before changing your role.")

    if hasattr(db, "update_member_role"):
        db.update_member_role(classroom_id, target_user_id, new_role)
    else:
        for m in current_members:
            if m.get("userId") == target_user_id:
                m["role"] = new_role
        db.classrooms.update_one({"_id": classroom_id}, {"$set": {"members": current_members, "updatedAt": now_iso()}})

    faculty_ids = list(classroom.get("facultyIds") or [])
    if new_role == "ASSISTANT" and target_user_id not in faculty_ids:
        faculty_ids.append(target_user_id)
        db.classrooms.update_one({"_id": classroom_id}, {"$set": {"facultyIds": faculty_ids}})
    elif new_role == "STUDENT" and target_user_id in faculty_ids:
        faculty_ids = [fid for fid in faculty_ids if fid != target_user_id]
        db.classrooms.update_one({"_id": classroom_id}, {"$set": {"facultyIds": faculty_ids}})
    elif new_role == "OWNER" and target_user_id not in faculty_ids:
        faculty_ids.append(target_user_id)
        db.classrooms.update_one({"_id": classroom_id}, {"$set": {"facultyIds": faculty_ids}})

    updated_classroom = db.classrooms.find_one({"_id": classroom_id})
    return classroom_payload(updated_classroom)


def remove_classroom_member(classroom_id: str, target_user_id: str, user: dict):
    classroom = require_classroom_owner(classroom_id, user)
    if target_user_id == classroom.get("ownerId"):
        raise err(400, "cannot_remove_owner", "The classroom owner cannot be removed from their own classroom. Delete the classroom or transfer ownership first.")

    current_members = list(classroom.get("members", []))
    target_member = next((m for m in current_members if m.get("userId") == target_user_id), None)
    if not target_member:
        raise err(404, "not_found", "User is not a member of this classroom.")

    if hasattr(db, "remove_member"):
        db.remove_member(classroom_id, target_user_id)
    else:
        remaining = [m for m in current_members if m.get("userId") != target_user_id]
        db.classrooms.update_one({"_id": classroom_id}, {"$set": {"members": remaining, "updatedAt": now_iso()}})

    faculty_ids = [fid for fid in (classroom.get("facultyIds") or []) if fid != target_user_id]
    db.classrooms.update_one({"_id": classroom_id}, {"$set": {"facultyIds": faculty_ids}})

    return {"removed": True, "userId": target_user_id, "classroomId": classroom_id}



def get_classroom_curriculum(classroom_id: str, user: dict):
    classroom = get_classroom(classroom_id, user)
    curriculum_status = classroom.get("curriculumStatus")
    if curriculum_status is None:
        curriculum_status = "published" if db.classroom_curriculum_topics.find_one({"classroomId": classroom_id, "published": True}) else "draft"
    editor = _classroom_editor(classroom, user)
    visible = curriculum_status == "published" or editor
    if not visible:
        return {"classroom": classroom, "modules": [], "status": curriculum_status, "version": classroom.get("curriculumVersion", 0)}

    modules = list(db.classroom_modules.find({"classroomId": classroom_id}))
    modules.sort(key=lambda row: row.get("position", 0))
    module_ids = [module["_id"] for module in modules]
    topics = list(db.classroom_curriculum_topics.find(
        {"classroomId": classroom_id, "moduleId": {"$in": module_ids}},
    )) if module_ids else []
    topics_by_module: dict[str, list[dict]] = {module_id: [] for module_id in module_ids}
    for topic in topics:
        topics_by_module[topic["moduleId"]].append(topic)
    for module_topics in topics_by_module.values():
        module_topics.sort(key=lambda row: row.get("position", 0))

    result = []
    for module in modules:
        module_topics = topics_by_module[module["_id"]]
        result.append({
            "id": module["_id"], "title": module["title"], "description": module.get("description", ""),
            "position": module.get("position", 0),
            "topics": [{**{k: v for k, v in topic.items() if k != "_id"}, "id": topic["_id"]} for topic in module_topics if editor or topic.get("published", False)],
        })
    return {"classroom": classroom, "modules": result, "status": curriculum_status, "version": classroom.get("curriculumVersion", 0)}


def create_curriculum_module(classroom_id: str, payload: CurriculumModuleIn, user: dict):
    require_classroom_editor(classroom_id, user)
    module = {"_id": f"module_{uuid.uuid4().hex[:12]}", "classroomId": classroom_id, "title": payload.title.strip(), "description": payload.description.strip(), "position": payload.position, "createdAt": now_iso(), "updatedAt": now_iso()}
    db.classroom_modules.insert_one(module)
    return {**{k: v for k, v in module.items() if k != "_id"}, "id": module["_id"], "topics": []}


def create_curriculum_topic(classroom_id: str, module_id: str, payload: CurriculumTopicIn, user: dict):
    require_classroom_editor(classroom_id, user)
    module = db.classroom_modules.find_one({"_id": module_id, "classroomId": classroom_id})
    if not module:
        raise err(404, "not_found", "Curriculum module not found in this classroom.")
    topic = {
        "_id": f"topic_{uuid.uuid4().hex[:12]}", "classroomId": classroom_id, "moduleId": module_id,
        "title": payload.title.strip(), "description": payload.description.strip(),
        "learningObjectives": [v.strip() for v in payload.learningObjectives if v.strip()],
        "prerequisites": payload.prerequisites, "concepts": [v.model_dump() for v in payload.concepts],
        "materials": [v.model_dump() for v in payload.materials],
        "position": db.classroom_curriculum_topics.count_documents({"classroomId": classroom_id, "moduleId": module_id}),
        "published": False, "createdAt": now_iso(), "updatedAt": now_iso(),
    }
    db.classroom_curriculum_topics.insert_one(topic)
    return {**{k: v for k, v in topic.items() if k != "_id"}, "id": topic["_id"]}


def _refresh_published_student_paths(classroom_id: str, classroom: dict):
    modules = list(db.classroom_modules.find({"classroomId": classroom_id}))
    modules.sort(key=lambda row: row.get("position", 0))
    published_modules = []
    for module in modules:
        topics = list(db.classroom_curriculum_topics.find({"classroomId": classroom_id, "moduleId": module["_id"], "published": True}))
        topics.sort(key=lambda row: row.get("position", 0))
        if topics:
            published_modules.append({
                "id": module["_id"],
                "title": module["title"],
                "position": module.get("position", 0),
                "topics": [{**{k: v for k, v in topic.items() if k != "_id"}, "id": topic["_id"]} for topic in topics],
            })
    for member in classroom.get("members", []):
        if member.get("role") == "STUDENT":
            path = build_adaptive_path(published_modules, [])
            db.learning_paths.update_one(
                {"_id": f"learning_path_{classroom_id}_{member['userId']}", "classroomId": classroom_id, "userId": member["userId"]},
                {"$set": {"classroomId": classroom_id, "userId": member["userId"], "path": path, "updatedAt": now()}},
                upsert=True,
            )


def delete_curriculum_module(classroom_id: str, module_id: str, user: dict):
    classroom = require_classroom_editor(classroom_id, user)
    module = db.classroom_modules.find_one({"_id": module_id, "classroomId": classroom_id})
    if not module:
        raise err(404, "not_found", "Curriculum module not found in this classroom.")
    db.classroom_curriculum_topics.delete_many({"classroomId": classroom_id, "moduleId": module_id})
    db.classroom_modules.delete_one({"_id": module_id, "classroomId": classroom_id})
    if not db.classroom_curriculum_topics.find_one({"classroomId": classroom_id}):
        db.classrooms.update_one({"_id": classroom_id}, {"$set": {"curriculumStatus": "draft", "updatedAt": now_iso()}})
    elif classroom.get("curriculumStatus") == "published":
        _refresh_published_student_paths(classroom_id, classroom)
    return {"deleted": True, "id": module_id}


def delete_curriculum_topic(classroom_id: str, topic_id: str, user: dict):
    classroom = require_classroom_editor(classroom_id, user)
    topic = db.classroom_curriculum_topics.find_one({"_id": topic_id, "classroomId": classroom_id})
    if not topic:
        raise err(404, "not_found", "Curriculum topic not found in this classroom.")
    db.classroom_curriculum_topics.delete_one({"_id": topic_id, "classroomId": classroom_id})
    if not db.classroom_curriculum_topics.find_one({"classroomId": classroom_id}):
        db.classrooms.update_one({"_id": classroom_id}, {"$set": {"curriculumStatus": "draft", "updatedAt": now_iso()}})
    elif classroom.get("curriculumStatus") == "published":
        _refresh_published_student_paths(classroom_id, classroom)
    return {"deleted": True, "id": topic_id}


def publish_classroom_curriculum(classroom_id: str, user: dict):
    classroom = require_classroom_editor(classroom_id, user)
    modules = list(db.classroom_modules.find({"classroomId": classroom_id}))
    if not modules or not db.classroom_curriculum_topics.find_one({"classroomId": classroom_id}):
        raise err(400, "empty_curriculum", "Add at least one topic before publishing the curriculum.")
    db.classroom_curriculum_topics.update_many({"classroomId": classroom_id}, {"$set": {"published": True}})
    version = classroom.get("curriculumVersion", 0) + 1
    db.classrooms.update_one({"_id": classroom_id}, {"$set": {"curriculumStatus": "published", "curriculumVersion": version, "updatedAt": now_iso()}})
    published_modules = []
    for module in modules:
        topics = list(db.classroom_curriculum_topics.find({"classroomId": classroom_id, "moduleId": module["_id"]}))
        published_modules.append({"id": module["_id"], "title": module["title"], "position": module.get("position", 0), "topics": [{**topic, "id": topic["_id"]} for topic in topics]})
    for member in classroom.get("members", []):
        if member.get("role") == "STUDENT":
            path = build_adaptive_path(published_modules, [])
            db.learning_paths.update_one({"_id": f"learning_path_{classroom_id}_{member['userId']}", "classroomId": classroom_id, "userId": member["userId"]}, {"$set": {"classroomId": classroom_id, "userId": member["userId"], "path": path, "updatedAt": now()}}, upsert=True)
    return {"status": "published", "version": version}


def classroom_topic_learning_context(classroom_id: str, topic_id: str, user: dict):
    classroom = get_classroom(classroom_id, user)
    curriculum_status = classroom.get("curriculumStatus")
    if curriculum_status is None:
        curriculum_status = "published" if db.classroom_curriculum_topics.find_one({"classroomId": classroom_id, "published": True}) else "draft"
    if curriculum_status != "published":
        raise err(404, "not_found", "Published topic not found in this classroom.")
    topic = db.classroom_curriculum_topics.find_one({"_id": topic_id, "classroomId": classroom_id, "published": True})
    if not topic:
        raise err(404, "not_found", "Published topic not found in this classroom.")
    module = db.classroom_modules.find_one({"_id": topic["moduleId"], "classroomId": classroom_id}) or {}
    return classroom, module, topic


def render_classroom_learning_prompt(content: str, classroom: dict, module: dict, topic: dict, learning_path: dict | None = None):
    concepts = "\n".join(f"- {item['name']}: {item.get('description', '')}" for item in topic.get("concepts", [])) or "None specified"
    objectives = "\n".join(f"- {item}" for item in topic.get("learningObjectives", [])) or "None specified"
    prerequisites = "\n".join(f"- {item}" for item in topic.get("prerequisites", [])) or "None specified"
    materials = "\n".join(f"- {item['title']}: {item.get('content') or item.get('url', '')}" for item in topic.get("materials", [])) or "None provided"
    path = (learning_path or {}).get("recommendation") or {}
    state = (f"Current topic status: {path.get('status', 'selected')}\nCurrent topic mastery: {path.get('mastery', {}).get('score', 'not measured')}\nAdaptive reason: {path.get('reason', 'Follow the selected curriculum topic.')}\nNext action: {path.get('nextAction', 'Build understanding with a lesson and quiz.')}") if path.get("topicId") == topic.get("id", topic.get("_id")) else "The student is exploring this permitted curriculum topic."
    return ("You are the classroom adaptive learning agent, not a general-purpose tutor. Teach only the selected official curriculum topic and its prerequisites. If the student asks about an unrelated subject, briefly redirect them to this topic. Treat the teacher-authored curriculum as authoritative; do not modify it.\n\n"
        f"Classroom: {classroom['name']} ({classroom.get('subject', '')})\nModule: {module.get('title', '')}\nOfficial topic: {topic['title']}\nTopic description: {topic.get('description', '')}\nLearning objectives:\n{objectives}\nExpected concepts:\n{concepts}\nPrerequisites:\n{prerequisites}\nTeacher materials:\n{materials}\n\nStudent adaptive state:\n{state}\n\nStudent request: {content}\nStart lesson")


def _revision_task_id(classroom_id: str, user_id: str, topic_id: str, concept_ids: list[str]) -> str:
    scope = ":".join([classroom_id, user_id, topic_id, *sorted(concept_ids)])
    return "adaptive_task_" + hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


def _classroom_revision_tasks(classroom_id: str, user_id: str) -> list[dict]:
    tasks = []
    for row in db.adaptive_tasks.find({"classroomId": classroom_id, "userId": user_id}):
        task = dict(row)
        task["id"] = str(task.get("id") or task.get("_id", ""))
        task.pop("generationToken", None)
        tasks.append(task)
    return tasks


def _revision_prompt(task: dict, classroom: dict, topic: dict) -> str:
    concepts = [item for item in topic.get("concepts", []) if item.get("name") in task.get("conceptIds", [])]
    materials = [str(item.get("content") or item.get("url") or "") for item in topic.get("materials", [])]
    return (
        "Create a focused revision lesson, not an official curriculum edit. Use only the supplied published materials. "
        "Address recorded missed questions without revealing test answers as hints.\n"
        f"Classroom: {classroom.get('name', '')}\nTopic: {topic.get('title', '')}\n"
        f"Objectives: {topic.get('learningObjectives', [])}\nTarget concepts: {concepts or 'Not reliably mapped; revise this topic generally.'}\n"
        f"Approved materials: {materials}\nMissed questions: {task.get('weakQuestionTexts', [])}\n"
        f"Official concept identifiers: {task.get('conceptIds', [])}"
    )


def _generate_revision_content(task: dict, classroom: dict, topic: dict) -> dict:
    lesson = generate_lesson(
        _revision_prompt(task, classroom, topic),
        task.get("difficulty", "beginner"),
        task.get("provider", "groq"),
        task.get("model", "qwen/qwen3.8-27b"),
    )
    data = lesson.model_dump()
    return {
        "topic": data["topic"],
        "explanation": data["explanation"],
        "flashcards": data["flashcards"],
        "blocks": data.get("blocks", []),
    }


def _prepare_revision_task(task_id: str, task: dict, classroom: dict, topic: dict) -> dict:
    claim_token = uuid.uuid4().hex
    claim = db.adaptive_tasks.update_one(
        {"_id": task_id, "generationStatus": {"$ne": "generating"}},
        {"$set": {
            "status": "pending",
            "generationStatus": "generating",
            "generationToken": claim_token,
            "generationStartedAt": now(),
            "updatedAt": now(),
        }},
    )
    if claim.matched_count == 0:
        existing = db.adaptive_tasks.find_one({"_id": task_id}) or task
        existing.pop("generationToken", None)
        return existing
    try:
        content = _generate_revision_content(task, classroom, topic)
        db.adaptive_tasks.update_one(
            {"_id": task_id, "generationToken": claim_token},
            {"$set": {"status": "ready", "generationStatus": "ready", "revisionContent": content, "generationToken": None, "updatedAt": now()}},
        )
    except LLMError as exc:
        db.adaptive_tasks.update_one(
            {"_id": task_id, "generationToken": claim_token},
            {"$set": {"status": "failed", "generationStatus": "failed", "generationError": exc.code, "generationToken": None, "updatedAt": now()}},
        )
    except Exception:
        db.adaptive_tasks.update_one(
            {"_id": task_id, "generationToken": claim_token},
            {"$set": {"status": "failed", "generationStatus": "failed", "generationError": "generation_failed", "generationToken": None, "updatedAt": now()}},
        )
    result = db.adaptive_tasks.find_one({"_id": task_id}) or task
    result.pop("generationToken", None)
    return result


def _orchestrate_classroom_assessment(session: dict, event: dict, user: dict) -> list[dict]:
    classroom_id = session["classroomId"]
    topic_id = session["curriculumTopicId"]
    classroom, _, topic = classroom_topic_learning_context(classroom_id, topic_id, user)
    prepared: list[dict] = []
    adaptive_task_id = session.get("adaptiveTaskId")
    active_for_topic = db.adaptive_tasks.find({
        "classroomId": classroom_id,
        "userId": user["id"],
        "topicId": topic_id,
        "status": {"$in": ["pending", "ready", "failed", "revision_complete", "generating_retest", "retest_available"]},
    })
    for active_task in active_for_topic:
        if active_task.get("_id") == adaptive_task_id:
            continue
        concept_results = event.get("conceptResults", {})
        covered = all(
            concept in concept_results
            and concept_results[concept]["total"] >= 2
            and concept_results[concept]["score"] > 85
            for concept in active_task.get("conceptIds", [])
        ) if active_task.get("conceptIds") else event["total"] >= 2 and event["masteryScore"] > 85
        if covered:
            history = list(active_task.get("attemptHistory", []))
            if not any(item.get("eventId") == event["_id"] for item in history):
                history.append({"eventId": event["_id"], "score": event["masteryScore"], "occurredAt": event["occurredAt"]})
            db.adaptive_tasks.update_one(
                {"_id": active_task["_id"], "userId": user["id"]},
                {"$set": {"status": "mastered", "generationStatus": "complete", "masteredAt": now(), "updatedAt": now(), "lastRetestScore": event["masteryScore"], "attemptHistory": history}},
            )
    if adaptive_task_id:
        task = db.adaptive_tasks.find_one({"_id": adaptive_task_id, "classroomId": classroom_id, "userId": user["id"]})
        if task:
            attempt_history = list(task.get("attemptHistory", []))
            if not any(item.get("eventId") == event["_id"] for item in attempt_history):
                attempt_history.append({"eventId": event["_id"], "score": event["masteryScore"], "occurredAt": event["occurredAt"]})
            concept_results = event.get("conceptResults", {})
            passed = all(
                concept in concept_results
                and concept_results[concept]["total"] >= 2
                and concept_results[concept]["score"] > 85
                for concept in task.get("conceptIds", [])
            ) if task.get("conceptIds") else event["total"] >= 2 and event["masteryScore"] > 85
            if passed:
                db.adaptive_tasks.update_one(
                    {"_id": adaptive_task_id},
                    {"$set": {"status": "mastered", "generationStatus": "complete", "masteredAt": now(), "updatedAt": now(), "lastRetestScore": event["masteryScore"], "attemptHistory": attempt_history}},
                )
            else:
                db.adaptive_tasks.update_one(
                    {"_id": adaptive_task_id},
                    {"$set": {"status": "pending", "generationStatus": "pending", "lastRetestScore": event["masteryScore"], "updatedAt": now(), "attemptHistory": attempt_history}},
                )
                task = db.adaptive_tasks.find_one({"_id": adaptive_task_id}) or task
                prepared.append(_prepare_revision_task(adaptive_task_id, task, classroom, topic))

    if not adaptive_task_id or (event["incorrect"] > 0 and not prepared):
        for spec in revision_task_specs(event["questionResults"], topic):
            task_id = _revision_task_id(classroom_id, user["id"], topic_id, spec["conceptIds"])
            weak_texts = [
                question.get("question", "")
                for question in session.get("learningContent", {}).get("quiz", [])
                if question.get("id") in spec["weakQuestionIds"]
            ]
            existing_task = db.adaptive_tasks.find_one({"_id": task_id}) or {}
            attempt_history = list(existing_task.get("attemptHistory", []))
            if not any(item.get("eventId") == event["_id"] for item in attempt_history):
                attempt_history.append({"eventId": event["_id"], "score": event["masteryScore"], "occurredAt": event["occurredAt"]})
            weak_question_texts = list(existing_task.get("weakQuestionTexts", []))
            weak_question_texts.extend(value for value in weak_texts if value and value not in weak_question_texts)
            if existing_task.get("generationStatus") == "generating":
                db.adaptive_tasks.update_one(
                    {"_id": task_id},
                    {"$set": {"attemptHistory": attempt_history, "weakQuestionTexts": weak_question_texts, "updatedAt": now()}},
                )
                result = db.adaptive_tasks.find_one({"_id": task_id}) or existing_task
                result.pop("generationToken", None)
                prepared.append(result)
                continue
            task = {
                **existing_task,
                **spec,
                "_id": task_id,
                "id": task_id,
                "classroomId": classroom_id,
                "userId": user["id"],
                "moduleId": session.get("curriculumModuleId"),
                "sourceSessionId": session["_id"],
                "sourceEventId": event["_id"],
                "weakQuestionTexts": weak_question_texts,
                "status": "ready" if existing_task.get("revisionContent") else "pending",
                "generationStatus": "ready" if existing_task.get("revisionContent") else "pending",
                "difficulty": session.get("difficulty", "beginner"),
                "provider": session.get("provider", "groq"),
                "model": session.get("model", "qwen/qwen3.8-27b"),
                "updatedAt": now(),
            }
            task.setdefault("createdAt", now())
            task["attemptHistory"] = attempt_history
            db.adaptive_tasks.update_one({"_id": task_id}, {"$set": task}, upsert=True)
            if existing_task.get("revisionContent"):
                task.pop("generationToken", None)
                prepared.append(task)
            else:
                prepared.append(_prepare_revision_task(task_id, task, classroom, topic))
    return prepared


def classroom_progress(classroom_id: str, user: dict):
    curriculum = get_classroom_curriculum(classroom_id, user)
    events = [e for e in db.learning_events.find({"classroomId": classroom_id}) if e.get("userId") == user["id"]]
    revision_tasks = _classroom_revision_tasks(classroom_id, user["id"])
    progress = build_student_progress(curriculum["modules"], events)
    path = build_adaptive_path(curriculum["modules"], events, revision_tasks)
    db.learning_paths.update_one({"_id": f"learning_path_{classroom_id}_{user['id']}", "classroomId": classroom_id, "userId": user["id"]}, {"$set": {"classroomId": classroom_id, "userId": user["id"], "path": path, "updatedAt": now()}}, upsert=True)
    progress["learningPath"] = path
    progress["revisionTasks"] = path["revisionTasks"]
    progress["revisionHistory"] = revision_tasks
    return progress


def classroom_topic_sessions(classroom_id: str, topic_id: str, user: dict):
    classroom_topic_learning_context(classroom_id, topic_id, user)
    rows = list(db.sessions.find(
        {
            "userId": user["id"],
            "classroomId": classroom_id,
            "curriculumTopicId": topic_id,
        },
        {"learningContent": 0, "input": 0, "answers": 0},
    ))
    rows.sort(key=lambda row: row.get("createdAt") or "", reverse=True)
    return [
        {
            "id": row["_id"],
            "topic": row.get("topic", ""),
            "difficulty": row.get("difficulty", "beginner"),
            "createdAt": row.get("createdAt"),
            "evaluation": row.get("evaluation", {"completed": False}),
            "search": row.get("classroomSearch", row.get("topic", "")),
        }
        for row in rows
    ]


def generate_adaptive_revision(classroom_id: str, task_id: str, user: dict):
    require_role(user, "STUDENT")
    get_classroom(classroom_id, user)
    task = db.adaptive_tasks.find_one({"_id": task_id, "classroomId": classroom_id, "userId": user["id"]})
    if not task:
        raise err(404, "not_found", "Revision task not found.")
    if task.get("status") == "mastered":
        raise err(409, "revision_complete", "This revision task is already mastered.")
    if task.get("revisionContent") and task.get("generationStatus") == "ready":
        return task
    started_at = task.get("generationStartedAt")
    if task.get("generationStatus") == "generating" and isinstance(started_at, datetime):
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        if started_at < now() - timedelta(minutes=2):
            db.adaptive_tasks.update_one(
                {"_id": task_id, "generationToken": task.get("generationToken")},
                {"$set": {"generationStatus": "failed", "status": "failed", "generationError": "generation_interrupted", "generationToken": None, "updatedAt": now()}},
            )
            task = db.adaptive_tasks.find_one({"_id": task_id}) or task
        else:
            task.pop("generationToken", None)
            return task
    _, _, topic = classroom_topic_learning_context(classroom_id, task["topicId"], user)
    classroom = db.classrooms.find_one({"_id": classroom_id})
    db.adaptive_tasks.update_one({"_id": task_id}, {"$set": {"status": "pending", "generationStatus": "pending", "updatedAt": now()}})
    return _prepare_revision_task(task_id, task, classroom, topic)


def complete_adaptive_revision(classroom_id: str, task_id: str, user: dict):
    require_role(user, "STUDENT")
    get_classroom(classroom_id, user)
    task = db.adaptive_tasks.find_one({"_id": task_id, "classroomId": classroom_id, "userId": user["id"]})
    if not task or task.get("status") == "mastered":
        raise err(404, "not_found", "Active revision task not found.")
    if task.get("generationStatus") != "ready" or not task.get("revisionContent"):
        raise err(409, "revision_not_ready", "Revision content must be available before it can be completed.")
    db.adaptive_tasks.update_one(
        {"_id": task_id, "classroomId": classroom_id, "userId": user["id"]},
        {"$set": {"status": "revision_complete", "revisionCompletedAt": now(), "updatedAt": now()}},
    )
    return db.adaptive_tasks.find_one({"_id": task_id}) or task


def create_adaptive_retest(classroom_id: str, task_id: str, user: dict):
    require_role(user, "STUDENT")
    get_classroom(classroom_id, user)
    task = db.adaptive_tasks.find_one({"_id": task_id, "classroomId": classroom_id, "userId": user["id"]})
    if not task or task.get("status") == "mastered":
        raise err(404, "not_found", "Active revision task not found.")
    if task.get("status") == "retest_available" and task.get("currentSessionId"):
        active_session = db.sessions.find_one({
            "_id": task["currentSessionId"],
            "userId": user["id"],
            "adaptiveTaskId": task_id,
            "evaluation.completed": {"$ne": True},
        })
        if active_session:
            return {
                "sessionId": active_session["_id"],
                "learningContent": active_session["learningContent"],
                "taskId": task_id,
                "idempotent": True,
            }
    if task.get("status") == "generating_retest":
        started_at = task.get("retestGenerationStartedAt")
        if isinstance(started_at, datetime):
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            if started_at >= now() - timedelta(minutes=2):
                raise err(409, "retest_preparing", "A fresh retest is already being prepared.")
            db.adaptive_tasks.update_one(
                {"_id": task_id, "status": "generating_retest", "retestGenerationStartedAt": task.get("retestGenerationStartedAt")},
                {"$set": {"status": "revision_complete", "retestGenerationError": "generation_interrupted", "updatedAt": now()}},
            )
            task = db.adaptive_tasks.find_one({"_id": task_id}) or task
    if task.get("status") != "revision_complete":
        raise err(409, "revision_incomplete", "Complete the targeted revision before starting its retest.")
    if task.get("generationStatus") != "ready" or not task.get("revisionContent"):
        raise err(409, "revision_not_ready", "Revision content must be available before the retest.")
    attempt_number = int(task.get("retestAttempt", 0)) + 1
    session_id = "session_adaptive_" + hashlib.sha256(
        f"{task_id}:{attempt_number}".encode("utf-8")
    ).hexdigest()[:16]
    prior_attempt = db.sessions.find_one({"_id": session_id, "userId": user["id"]})
    if prior_attempt:
        db.adaptive_tasks.update_one(
            {"_id": task_id},
            {"$set": {"status": "retest_available", "currentSessionId": session_id, "retestAttempt": attempt_number, "updatedAt": now()}},
        )
        return {"sessionId": session_id, "learningContent": prior_attempt["learningContent"], "taskId": task_id, "idempotent": True}
    claim = db.adaptive_tasks.update_one(
        {"_id": task_id, "classroomId": classroom_id, "userId": user["id"], "status": "revision_complete"},
        {"$set": {"status": "generating_retest", "retestGenerationStartedAt": now(), "retestGenerationAttempt": attempt_number, "updatedAt": now()}},
    )
    if claim.matched_count == 0:
        current = db.adaptive_tasks.find_one({"_id": task_id}) or task
        if current.get("status") == "retest_available" and current.get("currentSessionId"):
            active = db.sessions.find_one({"_id": current["currentSessionId"], "userId": user["id"], "adaptiveTaskId": task_id})
            if active:
                return {"sessionId": active["_id"], "learningContent": active["learningContent"], "taskId": task_id, "idempotent": True}
        raise err(409, "retest_preparing", "A fresh retest is already being prepared.")
    existing = list(db.sessions.find({"userId": user["id"], "adaptiveTaskId": task_id}))
    existing_questions = [
        question.get("question", "")
        for session_record in existing
        for question in session_record.get("learningContent", {}).get("quiz", [])
    ]
    _, _, topic = classroom_topic_learning_context(classroom_id, task["topicId"], user)
    classroom = db.classrooms.find_one({"_id": classroom_id})
    prompt = _revision_prompt(task, classroom, topic)
    try:
        quiz = generate_retest_quiz(
            prompt,
            existing_questions,
            task.get("provider", "groq"),
            task.get("model", "qwen/qwen3.8-27b"),
        )
    except LLMError as exc:
        db.adaptive_tasks.update_one(
            {"_id": task_id, "status": "generating_retest", "retestGenerationAttempt": attempt_number},
            {"$set": {"status": "revision_complete", "retestGenerationError": exc.code, "updatedAt": now()}},
        )
        raise err(504 if exc.code == "timeout" else 502, exc.code, exc.message)
    except Exception as exc:
        db.adaptive_tasks.update_one(
            {"_id": task_id, "status": "generating_retest", "retestGenerationAttempt": attempt_number},
            {"$set": {"status": "revision_complete", "retestGenerationError": "generation_failed", "updatedAt": now()}},
        )
        logger.exception("Adaptive retest generation failed for task %s", task_id)
        raise err(502, "llm_failed", "The retest could not be generated. Retry when the provider is available.") from exc
    duplicate_text = {question.lower().strip() for question in existing_questions}
    if any(question.question.lower().strip() in duplicate_text for question in quiz):
        db.adaptive_tasks.update_one(
            {"_id": task_id, "status": "generating_retest", "retestGenerationAttempt": attempt_number},
            {"$set": {"status": "revision_complete", "retestGenerationError": "duplicate_questions", "updatedAt": now()}},
        )
        raise err(502, "bad_schema", "The generated retest repeated an earlier question. Retry to generate a fresh set.")
    concept_ids = task.get("conceptIds", [])
    lesson = {
        **task["revisionContent"],
        "quiz": [
            {
                **question.model_dump(),
                "id": f"adaptive-{uuid.uuid4().hex[:10]}-{index}",
                "conceptIds": [concept for concept in question.conceptIds if concept in concept_ids],
            }
            for index, question in enumerate(quiz, start=1)
        ],
    }
    db.sessions.insert_one({
        "_id": session_id,
        "userId": user["id"],
        "topicId": user_topic_id("classroom_" + task["topicId"], user["id"]),
        "topic": topic["title"],
        "source": "adaptive_retest",
        "difficulty": task.get("difficulty", "beginner"),
        "provider": task.get("provider", "groq"),
        "model": task.get("model", "qwen/qwen3.8-27b"),
        "classroomId": classroom_id,
        "curriculumTopicId": task["topicId"],
        "curriculumModuleId": task.get("moduleId"),
        "concepts": concept_ids,
        "adaptiveTaskId": task_id,
        "adaptiveAttempt": attempt_number,
        "learningContent": lesson,
        "evaluation": {"completed": False},
        "createdAt": now(),
    })
    db.adaptive_tasks.update_one(
        {"_id": task_id, "status": "generating_retest", "retestGenerationAttempt": attempt_number},
        {"$set": {"status": "retest_available", "currentSessionId": session_id, "retestAttempt": attempt_number, "updatedAt": now()}},
    )
    return {"sessionId": session_id, "learningContent": lesson, "taskId": task_id}


def classroom_analytics(classroom_id: str, user: dict):
    classroom = require_classroom_editor(classroom_id, user)
    curriculum = get_classroom_curriculum(classroom_id, user)
    students = list(dict.fromkeys(m["userId"] for m in classroom.get("members", []) if m.get("role") == "STUDENT" and m.get("userId")))
    analytics = build_classroom_analytics(curriculum["modules"], students, list(db.learning_events.find({"classroomId": classroom_id})))
    for student in analytics["students"]:
        record = db.users.find_one({"_id": student["studentId"]}) or {}
        student["name"] = record.get("name") or "Student"
    return analytics


def classroom_knowledge_graph(classroom_id: str, user: dict, student_id: str | None = None):
    classroom = get_classroom(classroom_id, user)
    target = student_id or user["id"]
    if target != user["id"]:
        if not _classroom_editor(classroom, user):
            raise err(403, "forbidden", "Students may only view their own knowledge graph.")
        if not any(m.get("userId") == target and m.get("role") == "STUDENT" for m in classroom.get("members", [])):
            raise err(404, "not_found", "Student is not enrolled in this classroom.")
    modules = get_classroom_curriculum(classroom_id, user)["modules"]
    events = [e for e in db.learning_events.find({"classroomId": classroom_id}) if e.get("userId") == target]
    progress = build_student_progress(modules, events)
    states = {t["id"]: t for m in progress["modules"] for t in m["topics"]}
    topic_ids = {topic["id"] for module in modules for topic in module["topics"]}
    started_topic_ids = {
        session.get("curriculumTopicId")
        for session in db.sessions.find({"userId": target, "classroomId": classroom_id})
        if session.get("curriculumTopicId") in topic_ids
    }
    submissions = list(db.classroom_submissions.find({"studentId": target, "classroomId": classroom_id}))
    assessment_ids = {submission.get("assessmentId") for submission in submissions if submission.get("assessmentId")}
    if assessment_ids:
        started_topic_ids.update(
            assessment.get("topicId")
            for assessment in db.classroom_assessments.find({"_id": {"$in": list(assessment_ids)}, "classroomId": classroom_id})
            if assessment.get("topicId") in topic_ids
        )
    eligible_modules = []
    for module in modules:
        eligible_topics = []
        for topic in module["topics"]:
            state = states.get(topic["id"])
            mastery = state["mastery"] if state else None
            has_evidence = bool(mastery and mastery["evidenceCount"])
            started = topic["id"] in started_topic_ids or has_evidence
            completed = bool(state and state["coverage"] == "covered")
            if not started and not completed:
                continue
            eligible_topics.append(topic)
        if eligible_topics:
            eligible_modules.append({**module, "topics": eligible_topics})
    nodes, edges, concepts_by_name, visible_topic_ids = [], [], {}, {}
    for module in eligible_modules:
        for topic in module["topics"]:
            topic_node = f"topic:{topic['id']}"
            state = states[topic["id"]]
            visible_topic_ids[topic["id"]] = topic_node
            has_evidence = bool(state["mastery"]["evidenceCount"])
            nodes.append({"id": topic_node, "curriculumId": topic["id"], "label": topic["title"], "kind": "topic", "moduleId": module["id"], "moduleName": module["title"], "started": topic["id"] in started_topic_ids or has_evidence, "completed": state["coverage"] == "covered", "mastered": state["mastery"]["state"] == "strong", "mastery": state["mastery"], "coverage": state["coverage"]})
            for concept in topic.get("concepts", []):
                cid = f"concept:{topic['id']}:{concept['name']}"
                cstate = next((c for c in state["concepts"] if c["name"] == concept["name"]), None)
                if not cstate or not cstate["mastery"]["evidenceCount"]:
                    continue
                concepts_by_name.setdefault(concept["name"], []).append(cid)
                nodes.append({"id": cid, "curriculumId": concept["name"], "label": concept["name"], "kind": "concept", "moduleId": module["id"], "moduleName": module["title"], "started": True, "completed": state["coverage"] == "covered", "mastered": cstate["mastery"]["state"] == "strong", "mastery": cstate["mastery"], "coverage": state["coverage"]})
                edges.append({"source": topic_node, "target": cid, "kind": "contains"})
    for module in eligible_modules:
        for topic in module["topics"]:
            topic_node = visible_topic_ids[topic["id"]]
            for prerequisite_id in topic.get("prerequisites", []):
                prerequisite_node = visible_topic_ids.get(prerequisite_id)
                if prerequisite_node:
                    edges.append({"source": prerequisite_node, "target": topic_node, "kind": "prerequisite"})
            target_id = lambda name: f"concept:{topic['id']}:{name}"
            for concept in topic.get("concepts", []):
                target_node = target_id(concept["name"])
                if not any(node["id"] == target_node for node in nodes):
                    continue
                for prerequisite in concept.get("prerequisites", []):
                    source_nodes = [node_id for node_id in concepts_by_name.get(prerequisite, []) if node_id != target_node]
                    if source_nodes:
                        edges.append({"source": source_nodes[0], "target": target_node, "kind": "prerequisite"})
    visible_node_ids = {node["id"] for node in nodes}
    unique_edges = {}
    for edge in edges:
        if edge["source"] in visible_node_ids and edge["target"] in visible_node_ids:
            unique_edges[(edge["source"], edge["target"], edge["kind"])] = edge
    return {"studentId": target, "nodes": nodes, "edges": list(unique_edges.values())}


def join_classroom(payload: dict, user: dict):
    role = require_role(user, "STUDENT", "FACULTY")
    classroom = db.classrooms.find_one({"joinCode": str(payload.get("joinCode", "")).strip().upper()})
    if not classroom:
        raise err(404, "not_found", "Join code not found.")
    if hasattr(db, "join_member"):
        db.join_member(classroom["_id"], user["id"], role, now())
        classroom = db.classrooms.find_one({"_id": classroom["_id"]})
        return classroom_payload(classroom)
    members = classroom.get("members", [])
    if not any(m.get("userId") == user["id"] for m in members):
        members.append({"userId": user["id"], "role": role, "joinedAt": now_iso()})
        db.classrooms.update_one({"_id": classroom["_id"]}, {"$set": {"members": members, "updatedAt": now_iso()}})
        classroom = db.classrooms.find_one({"_id": classroom["_id"]})
    return classroom_payload(classroom)


def update_user_role(user_id: str, payload: dict, acting_user: dict):
    require_role(acting_user, "ADMIN")
    role = str(payload.get("role", "")).upper().strip()
    if role not in VALID_ROLES:
        raise err(400, "invalid_role", "Role must be ADMIN, FACULTY, or STUDENT.")
    if acting_user["id"] == user_id and role != "STUDENT":
        raise err(403, "forbidden", "You cannot promote yourself to a higher role.")
    target = db.users.find_one({"_id": user_id})
    if not target:
        raise err(404, "not_found", "User not found.")
    db.users.update_one({"_id": user_id}, {"$set": {"role": role, "updatedAt": now_iso()}})
    return {"id": user_id, "name": target.get("name", "User"), "email": target.get("email", ""), "role": role}


def list_platform_users(acting_user: dict):
    require_role(acting_user, "ADMIN")
    return [{"id": row["_id"], "name": row.get("name", "Learner"), "email": row.get("email", ""), "role": normalize_role(row.get("role")), "createdAt": row.get("createdAt")} for row in db.users.find({}) if not str(row.get("_id", "")).startswith("guest_")]


def auth_session_status(session_id: str | None):
    user_id = get_session_user_id(session_id)
    if not user_id:
        return {"authenticated": False, "user": None}
    user = db.users.find_one({"_id": user_id})
    if not user:
        db.sessions.delete_one({"_id": session_id})
        return {"authenticated": False, "user": None}
    csrf = secrets.token_urlsafe(32)
    db.sessions.update_one({"_id": session_id}, {"$set": {"csrf_token_hash": hash_token(csrf)}})
    is_guest = user_id.startswith("guest_")
    return {
        "authenticated": True,
        "csrfToken": csrf,
        "user": {
            "id": user_id,
            "name": user.get("name", "Guest" if is_guest else "Learner"),
            "email": user.get("email", ""),
            "picture": user.get("picture", ""),
            "role": "STUDENT" if is_guest else normalize_role(user.get("role")),
            "isGuest": is_guest,
        },
    }


def create_classroom_assessment(classroom_id: str, payload: ClassroomAssessmentIn, user: dict):
    require_classroom_editor(classroom_id, user)
    if payload.topicId and not db.classroom_curriculum_topics.find_one({"_id": payload.topicId, "classroomId": classroom_id}):
        raise err(404, "not_found", "Assessment topic not found in this classroom.")
    assessment = {"_id": f"assessment_{uuid.uuid4().hex[:12]}", "classroomId": classroom_id, **payload.model_dump(), "createdBy": user["id"], "createdAt": now(), "updatedAt": now()}
    db.classroom_assessments.insert_one(assessment)
    return {**{k: v for k, v in assessment.items() if k != "_id"}, "id": assessment["_id"]}


def _record_written_assessment_evidence(
    classroom_id: str,
    assessment: dict,
    submission: dict,
    score: float,
    concept_scores: dict[str, float],
    activity_status: str,
    user: dict,
):
    topic_id = assessment.get("topicId")
    if not topic_id:
        return
    topic = db.classroom_curriculum_topics.find_one({"_id": topic_id, "classroomId": classroom_id}) or {}
    allowed = {str(item["name"]) for item in topic.get("concepts", []) if item.get("name")}
    scoped = [value for value in assessment.get("conceptIds", []) if value in allowed]
    if concept_scores:
        scoped = [value for value in concept_scores if value in allowed]
    concept_results = {}
    question_results = []
    weak_concepts = []
    for concept in scoped:
        percent = float(concept_scores.get(concept, score / assessment["maxMarks"] * 100))
        passed = percent > 85
        concept_results[concept] = {
            "correct": int(passed),
            "incorrect": int(not passed),
            "unanswered": 0,
            "total": 1,
            "score": round(percent),
        }
        question_id = f"{submission['_id']}:{concept}"
        question_results.append({
            "questionId": question_id,
            "correct": passed,
            "unanswered": False,
            "concepts": [concept],
        })
        if not passed:
            weak_concepts.append(concept)
    if not scoped:
        question_results.append({
            "questionId": submission["_id"],
            "correct": score / assessment["maxMarks"] * 100 > 85,
            "unanswered": False,
            "concepts": [],
        })
    event_id = f"learning_event_submission_{submission['_id']}"
    event = {
        "userId": submission["studentId"],
        "classroomId": classroom_id,
        "moduleId": topic.get("moduleId"),
        "topicId": topic_id,
        "concepts": scoped,
        "conceptResults": concept_results,
        "questionResults": question_results,
        "mappingStatus": "mapped" if scoped else "insufficient",
        "activityType": assessment["kind"],
        "evidenceType": "assessment",
        "sourceSubmissionId": submission["_id"],
        "score": score,
        "maxScore": assessment["maxMarks"],
        "masteryScore": round(score / assessment["maxMarks"] * 100),
        "coverage": False,
        "total": 1,
        "correct": int(score / assessment["maxMarks"] * 100 > 85),
        "incorrect": int(score / assessment["maxMarks"] * 100 <= 85),
        "unanswered": 0,
        "attempt": 1,
        "evaluationStatus": activity_status,
        "occurredAt": now(),
    }
    db.learning_events.update_one(
        {"_id": event_id},
        {"$set": event, "$setOnInsert": {"createdAt": now()}},
        upsert=True,
    )
    if event["incorrect"] or weak_concepts:
        student_record = db.users.find_one({"_id": submission["studentId"]}) or {}
        student_user = {
            "id": submission["studentId"],
            "name": student_record.get("name", "Student"),
            "email": student_record.get("email", ""),
            "role": normalize_role(student_record.get("role")),
        }
        session = {
            "_id": submission["_id"],
            "userId": submission["studentId"],
            "classroomId": classroom_id,
            "curriculumTopicId": topic_id,
            "curriculumModuleId": topic.get("moduleId"),
            "learningContent": {
                "quiz": [
                    {"id": item["questionId"], "question": f"{assessment['title']}: {assessment.get('instructions', '')}"}
                    for item in question_results
                ]
            },
            "difficulty": "beginner",
            "provider": os.getenv("EVALUATION_PROVIDER", "groq"),
            "model": os.getenv("EVALUATION_MODEL") or "qwen/qwen3.8-27b",
        }
        _orchestrate_classroom_assessment(session, {"_id": event_id, **event}, student_user)


def list_classroom_assessments(classroom_id: str, user: dict):
    classroom = get_classroom(classroom_id, user)
    rows = list(db.classroom_assessments.find({"classroomId": classroom_id}))
    if not _classroom_editor(classroom, user):
        rows = [row for row in rows if row.get("published")]
    rows.sort(key=lambda row: row.get("createdAt", now()), reverse=True)
    return [{**{k: v for k, v in row.items() if k != "_id"}, "id": row["_id"]} for row in rows]


def submit_classroom_assessment(classroom_id: str, assessment_id: str, payload: ClassroomSubmissionIn, user: dict):
    require_role(user, "STUDENT")
    get_classroom(classroom_id, user)
    assessment = db.classroom_assessments.find_one({"_id": assessment_id, "classroomId": classroom_id, "published": True})
    if not assessment:
        raise err(404, "not_found", "Published assessment not found in this classroom.")
    if db.classroom_submissions.find_one({"assessmentId": assessment_id, "studentId": user["id"]}):
        raise err(409, "submission_exists", "A submission already exists for this assessment.")
    submission = {"_id": f"submission_{uuid.uuid4().hex[:12]}", "classroomId": classroom_id, "assessmentId": assessment_id, "studentId": user["id"], "answer": payload.answer.strip(), "status": "submitted", "evaluationStatus": "pending", "submittedAt": now()}
    try:
        db.classroom_submissions.insert_one(submission)
    except IntegrityError as exc:
        if "uq_submission_student_assessment" in str(exc.orig):
            raise err(409, "submission_exists", "A submission already exists for this assessment.") from exc
        raise
    return {**{k: v for k, v in submission.items() if k != "_id"}, "id": submission["_id"]}


def list_classroom_submissions(classroom_id: str, assessment_id: str, user: dict):
    classroom = get_classroom(classroom_id, user)
    if not db.classroom_assessments.find_one({"_id": assessment_id, "classroomId": classroom_id}):
        raise err(404, "not_found", "Assessment not found in this classroom.")
    editor = _classroom_editor(classroom, user)
    query = {"assessmentId": assessment_id} if editor else {"assessmentId": assessment_id, "studentId": user["id"]}
    result = []
    for row in db.classroom_submissions.find(query):
        item = {**{k: v for k, v in row.items() if k != "_id"}, "id": row["_id"]}
        if editor:
            student = db.users.find_one({"_id": item["studentId"]}) or {}
            item["studentName"] = student.get("name") or "Student"
        if not editor and not item.get("released"):
            for key in ("score", "feedback", "aiEvaluation"):
                item.pop(key, None)
        result.append(item)
    return result


def grade_classroom_submission(classroom_id: str, assessment_id: str, submission_id: str, payload: ClassroomGradeIn, user: dict):
    require_classroom_editor(classroom_id, user)
    assessment = db.classroom_assessments.find_one({"_id": assessment_id, "classroomId": classroom_id})
    submission = db.classroom_submissions.find_one({"_id": submission_id, "assessmentId": assessment_id, "classroomId": classroom_id})
    if not assessment or not submission:
        raise err(404, "not_found", "Assessment submission not found.")
    if payload.score > assessment["maxMarks"]:
        raise err(400, "invalid_score", "Score cannot exceed the assessment maximum marks.")
    db.classroom_submissions.update_one({"_id": submission_id}, {"$set": {"score": payload.score, "feedback": payload.feedback.strip(), "released": payload.release, "status": "graded", "evaluationStatus": "faculty_graded", "gradedBy": user["id"], "gradedAt": now()}})
    _record_written_assessment_evidence(
        classroom_id, assessment, submission, payload.score, {}, "faculty_graded", user
    )
    return {"id": submission_id, "score": payload.score, "released": payload.release}


def evaluate_classroom_submission(classroom_id: str, assessment_id: str, submission_id: str, user: dict):
    require_classroom_editor(classroom_id, user)
    assessment = db.classroom_assessments.find_one({"_id": assessment_id, "classroomId": classroom_id})
    submission = db.classroom_submissions.find_one({"_id": submission_id, "classroomId": classroom_id, "assessmentId": assessment_id})
    if not assessment or not submission:
        raise err(404, "not_found", "Assessment submission not found.")
    topic = db.classroom_curriculum_topics.find_one({"_id": assessment.get("topicId"), "classroomId": classroom_id}) or {}
    expected = assessment.get("conceptIds") or [item["name"] for item in topic.get("concepts", [])]
    context = "\n".join([topic.get("description", ""), *topic.get("learningObjectives", [])] + [item.get("content", "") for item in topic.get("materials", [])])
    try:
        result = evaluate_written_answer(question=f"{assessment['title']}\n{assessment.get('instructions', '')}", answer=submission["answer"], rubric=assessment.get("rubric", ""), expected_answer=assessment.get("expectedAnswer", ""), max_marks=assessment["maxMarks"], expected_concepts=expected, course_context=context, provider=os.getenv("EVALUATION_PROVIDER", "groq"), model=os.getenv("EVALUATION_MODEL") or None)
    except LLMError as exc:
        raise err(504 if exc.code == "timeout" else 502, exc.code, exc.message)
    db.classroom_submissions.update_one({"_id": submission_id}, {"$set": {"aiEvaluation": result, "aiEvaluatedAt": now(), "evaluationStatus": "ai_evaluated"}})
    _record_written_assessment_evidence(
        classroom_id,
        assessment,
        submission,
        result["score"],
        result["conceptScores"],
        "complete",
        user,
    )
    return result


def list_classroom_posts(classroom_id: str, user: dict):
    classroom = db.classrooms.find_one({"_id": classroom_id})
    if not classroom or classroom.get("deletionState") == "pending":
        raise err(404, "not_found", "Classroom not found.")

    role = require_role(user, "ADMIN", "FACULTY", "STUDENT")
    member = any(m.get("userId") == user["id"] for m in classroom.get("members", []))
    if role != "ADMIN" and classroom.get("ownerId") != user["id"] and not member:
        raise err(403, "forbidden", "You do not have access to this classroom.")

    posts = list(db.classroom_posts.find({"classroomId": classroom_id}))
    posts.sort(key=lambda row: row.get("createdAt", now()), reverse=True)

    if not posts:
        return []

    post_ids = [post["_id"] for post in posts]
    replies_by_post: dict[str, list[dict]] = {post_id: [] for post_id in post_ids}
    for reply in db.classroom_replies.find({"classroomId": classroom_id, "postId": {"$in": post_ids}}):
        replies_by_post.setdefault(reply["postId"], []).append(reply)

    for reply_group in replies_by_post.values():
        reply_group.sort(key=lambda row: row.get("createdAt", now()))

    result = []
    for post in posts:
        post_replies = replies_by_post.get(post["_id"], [])
        result.append({
            **{k: v for k, v in post.items() if k != "_id"},
            "id": post["_id"],
            "replies": [{**{k: v for k, v in row.items() if k != "_id"}, "id": row["_id"]} for row in post_replies],
        })
    return result


def create_classroom_post(classroom_id: str, payload: ClassroomPostIn, user: dict):
    classroom = get_classroom(classroom_id, user)
    if payload.kind == "announcement" and not _classroom_editor(classroom, user):
        raise err(403, "forbidden", "Only classroom faculty can post announcements.")
    post = {"_id": f"post_{uuid.uuid4().hex[:12]}", "classroomId": classroom_id, "kind": payload.kind, "title": payload.title.strip(), "body": payload.body.strip(), "authorId": user["id"], "createdAt": now()}
    db.classroom_posts.insert_one(post)
    return {**{k: v for k, v in post.items() if k != "_id"}, "id": post["_id"], "replies": []}


def create_classroom_reply(classroom_id: str, post_id: str, payload: ClassroomReplyIn, user: dict):
    get_classroom(classroom_id, user)
    if not db.classroom_posts.find_one({"_id": post_id, "classroomId": classroom_id}):
        raise err(404, "not_found", "Classroom post not found.")
    reply = {"_id": f"reply_{uuid.uuid4().hex[:12]}", "classroomId": classroom_id, "postId": post_id, "authorId": user["id"], "body": payload.body.strip(), "createdAt": now()}
    db.classroom_replies.insert_one(reply)
    return {**{k: v for k, v in reply.items() if k != "_id"}, "id": reply["_id"]}


def current_user(
    request: Request,
):
    session_id = request.cookies.get(SESSION_COOKIE)
    user_id = get_session_user_id(session_id)
    if user_id:
        user = db.users.find_one({"_id": user_id})
        if user:
            is_guest = user_id.startswith("guest_")
            return {
                "id": user["_id"],
                "name": user.get("name", "Guest" if is_guest else "Learner"),
                "email": user.get("email", ""),
                "picture": user.get("picture", ""),
                "role": "STUDENT" if is_guest else normalize_role(user.get("role")),
                "isGuest": is_guest,
            }
        db.sessions.delete_one({"_id": session_id})
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


@app.post("/api/auth/google")
def google_auth(body: GoogleAuthIn, request: Request, response: Response):
    claims = verify_google_credential(body.credential)
    existing_session_id = request.cookies.get(SESSION_COOKIE)
    if existing_session_id:
        db.sessions.delete_one({"_id": existing_session_id})
    user_id = claims["sub"]
    existing = db.users.find_one({"_id": user_id}) or {}
    role = normalize_role(existing.get("role"))
    bootstrap_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    is_bootstrap_user = (
        bool(bootstrap_email)
        and claims.get("email_verified") is True
        and str(claims.get("email", "")).strip().lower() == bootstrap_email
    )
    if is_bootstrap_user and not db.users.find_one({"role": "ADMIN"}):
        role = "ADMIN"
    db.users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "name": claims.get("name", "Learner"),
                "email": claims.get("email", ""),
                "picture": claims.get("picture", ""),
                "role": role,
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
    return {
        "user": {
            "id": user_id,
            "name": claims.get("name", "Learner"),
            "email": claims.get("email", ""),
            "picture": claims.get("picture", ""),
            "role": role,
        },
        "csrfToken": session["csrf_token"],
    }


@app.post("/api/auth/guest")
def create_guest_session(request: Request, response: Response):
    existing_session_id = request.cookies.get(SESSION_COOKIE)
    if existing_session_id:
        existing_user_id = get_session_user_id(existing_session_id)
        if existing_user_id:
            existing_user = db.users.find_one({"_id": existing_user_id}) or {}
            if existing_user_id.startswith("guest_"):
                csrf = secrets.token_urlsafe(32)
                db.sessions.update_one(
                    {"_id": existing_session_id},
                    {"$set": {"csrf_token_hash": hash_token(csrf)}},
                )
                return {
                    "user": {"id": existing_user_id, "name": existing_user.get("name", "Guest"), "email": "", "picture": "", "role": "STUDENT", "isGuest": True},
                    "csrfToken": csrf,
                }

    guest_id = f"guest_{secrets.token_urlsafe(24)}"
    db.users.insert_one({
        "_id": guest_id,
        "name": "Guest",
        "email": "",
        "picture": "",
        "role": "STUDENT",
        "createdAt": now(),
        "updatedAt": now(),
        "stats": {"topicsStudied": 0, "sessionsCompleted": 0, "averageScore": 0, "cardsReviewed": 0, "quizzesCompleted": 0},
    })
    session = create_session(guest_id)
    response.set_cookie(key=SESSION_COOKIE, value=session["id"], **session_cookie_settings())
    if existing_session_id:
        db.sessions.delete_one({"_id": existing_session_id})
    return {
        "user": {"id": guest_id, "name": "Guest", "email": "", "picture": "", "role": "STUDENT", "isGuest": True},
        "csrfToken": session["csrf_token"],
    }


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        db.sessions.delete_one({"_id": session_id})
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        secure=SESSION_COOKIE_SECURE,
        samesite=SESSION_COOKIE_SAMESITE,
        domain=SESSION_COOKIE_DOMAIN,
    )
    return {"status": "ok"}


@app.exception_handler(SQLAlchemyError)
async def db_error(_: Request, __: SQLAlchemyError):
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
    except SQLAlchemyError:
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
def learn_document(
    file: UploadFile = File(...),
    difficulty: str = Form("beginner"),
    provider: str = Form("groq"),
    model: str = Form("qwen/qwen3.8-27b"),
    instructions: str = Form(""),
    user: dict = Depends(current_user),
):
    if not file.filename:
        raise err(400, "unsupported_file", "No document file was provided.")
    raw = file.file.read()
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
    def events():
        yield 'data: {"stage":"understanding"}\n\n'
        try:
            prompt = body.content
            classroom = module = topic = None
            if body.classroomId and body.curriculumTopicId:
                classroom, module, topic = classroom_topic_learning_context(
                    body.classroomId, body.curriculumTopicId, user
                )
                curriculum = get_classroom_curriculum(body.classroomId, user)
                student_events = [
                    event for event in db.learning_events.find({"classroomId": body.classroomId})
                    if event.get("userId") == user["id"]
                ]
                student_tasks = _classroom_revision_tasks(body.classroomId, user["id"])
                adaptive_path = build_adaptive_path(curriculum["modules"], student_events, student_tasks)
                selected_path_item = next(
                    (item for item in adaptive_path["items"] if item["topicId"] == topic["_id"]),
                    None,
                )
                if not selected_path_item:
                    raise err(404, "not_found", "Topic is not available in the published learning path.")
                if selected_path_item["status"] == "locked":
                    raise err(409, "prerequisite_locked", selected_path_item["reason"])
                prompt = render_classroom_learning_prompt(
                    body.content, classroom, module, topic,
                    {"recommendation": selected_path_item},
                )
                active_topic_tasks = [
                    task for task in student_tasks
                    if task.get("topicId") == topic["_id"]
                    and task.get("status") in {"pending", "ready", "failed", "revision_complete", "generating_retest", "retest_available"}
                ]
                prompt += "\nOfficial quiz concept identifiers (exact names only): " + json.dumps(
                    [item["name"] for item in topic.get("concepts", [])]
                )
                if active_topic_tasks:
                    prompt += "\nTargeted learner revision context (summary only): " + json.dumps([
                        {"concepts": task.get("conceptIds", []), "status": task.get("status"), "missedQuestions": task.get("weakQuestionTexts", [])[:3]}
                        for task in active_topic_tasks[:5]
                    ])
            lesson = generate_lesson(prompt, body.difficulty, body.provider, body.model)
            yield 'data: {"stage":"building"}\n\n'
            sid = f"session_{uuid.uuid4().hex[:12]}"
            topic_key = "topic_" + re.sub(
                r"[^a-z0-9]+", "_", lesson.topic.lower()
            ).strip("_")
            tid = user_topic_id(topic_key, user["id"])
            data = lesson.model_dump()
            if topic:
                allowed_concepts = {item["name"] for item in topic.get("concepts", [])}
                for question in data.get("quiz", []):
                    question["conceptIds"] = [
                        concept for concept in question.get("conceptIds", [])
                        if concept in allowed_concepts
                    ]
            db.sessions.insert_one(
                {
                    "_id": sid,
                    "userId": user["id"],
                    "topicId": tid,
                    "topic": lesson.topic,
                    "difficulty": body.difficulty,
                    "provider": body.provider,
                    "model": body.model,
                    "input": {"content": prompt},
                    **({
                        "classroomId": body.classroomId,
                        "curriculumTopicId": topic["_id"],
                        "curriculumModuleId": module.get("_id"),
                        "concepts": [item["name"] for item in topic.get("concepts", [])],
                        "classroomSearch": body.content,
                    } if topic else {}),
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
            current_session().commit()
            yield 'data: {"stage":"ready"}\n\n'
            yield f"data: {json.dumps({'sessionId': sid, 'topic': lesson.topic, 'learningContent': data})}\n\n"
        except LLMError as error:
            yield f"data: {json.dumps({'error': error.code, 'message': error.message})}\n\n"

    def stream_events():
        session = session_factory()()
        iterator = events()
        try:
            while True:
                token = set_request_session(session)
                try:
                    chunk = next(iterator)
                except StopIteration:
                    return
                finally:
                    reset_request_session(token)
                yield chunk
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    return StreamingResponse(stream_events(), media_type="text/event-stream")


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
    if s.get("evaluation", {}).get("completed"):
        if s.get("answers", {}) == body.answers:
            if not s.get("classroomId") or s.get("orchestrationStatus") == "ready":
                return {"evaluation": s["evaluation"], "topicProgress": s["evaluation"].get("score", 0), "stats": recompute_stats(user_id), "idempotent": True}
        else:
            raise err(409, "submission_exists", "This quiz attempt has already been completed.")

    allowed_concepts = None
    if s.get("classroomId") and s.get("curriculumTopicId"):
        classroom, _, curriculum_topic = classroom_topic_learning_context(
            s["classroomId"], s["curriculumTopicId"], user
        )
        allowed_concepts = {
            str(concept["name"])
            for concept in curriculum_topic.get("concepts", [])
            if concept.get("name")
        }
        if classroom.get("curriculumStatus") != "published":
            raise err(409, "curriculum_unavailable", "The curriculum topic is no longer published.")

    try:
        graded = grade_quiz(
            s.get("learningContent", {}).get("quiz", []),
            body.answers,
            allowed_concepts,
        )
    except AssessmentValidationError as exc:
        raise err(400, "invalid_assessment", str(exc))

    score = graded["score"]
    ev = {
        "score": score,
        "correct": graded["correct"],
        "incorrect": graded["incorrect"],
        "unanswered": graded["unanswered"],
        "total": graded["total"],
        "completed": True,
    }
    update = db.sessions.update_one(
        {"_id": sid, "userId": user_id, "evaluation.completed": {"$ne": True}},
        {
            "$set": {
                "evaluation": ev,
                "answers": body.answers,
                "questionResults": graded["questionResults"],
                "conceptResults": graded["conceptResults"],
                "cardsReviewed": body.cardsReviewed,
                "completedAt": now(),
                "orchestrationStatus": "pending" if s.get("classroomId") else "ready",
            }
        },
    )
    if update.matched_count == 0:
        current = db.sessions.find_one({"_id": sid, "userId": user_id}) or {}
        if current.get("answers", {}) != body.answers or not current.get("evaluation", {}).get("completed"):
            raise err(409, "submission_exists", "This quiz attempt has already been completed.")
        s = current

    adaptive_tasks = []
    if s.get("classroomId") and s.get("curriculumTopicId"):
        mapped_concepts = sorted({concept for result in graded["questionResults"] for concept in result["concepts"]})
        mapping_status = "mapped" if mapped_concepts else "insufficient"
        coverage_complete = graded["total"] >= 2
        event = {
            "_id": f"learning_event_session_{sid}",
            "userId": user_id,
            "classroomId": s["classroomId"],
            "moduleId": s.get("curriculumModuleId"),
            "topicId": s["curriculumTopicId"],
            "concepts": mapped_concepts,
            "conceptResults": graded["conceptResults"],
            "questionResults": graded["questionResults"],
            "mappingStatus": mapping_status,
            "activityType": "curiosity_quiz",
            "evidenceType": "assessment",
            "sourceSessionId": sid,
            "score": score,
            "maxScore": 100,
            "masteryScore": score,
            "coverage": coverage_complete,
            "total": graded["total"],
            "correct": graded["correct"],
            "incorrect": graded["incorrect"],
            "unanswered": graded["unanswered"],
            "attempt": 1,
            "evaluationStatus": "complete",
            "occurredAt": now(),
        }
        db.learning_events.update_one(
            {"_id": event["_id"]},
            {
                "$set": {key: value for key, value in event.items() if key != "_id"},
                "$setOnInsert": {"createdAt": now()},
            },
            upsert=True,
        )
        adaptive_tasks = _orchestrate_classroom_assessment({**s, "_id": sid}, event, user)
        db.sessions.update_one(
            {"_id": sid, "userId": user_id},
            {"$set": {"orchestrationStatus": "ready", "orchestratedAt": now()}},
        )
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
    return {"evaluation": ev, "topicProgress": avg, "stats": recompute_stats(user_id), "adaptiveTasks": adaptive_tasks}


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


@app.get("/api/profile")
def profile(user: dict = Depends(current_user)):
    user_id = user["id"]
    u = out(db.users.find_one({"_id": user_id}))

    retest_counts = {}
    for row in db.sessions.find(
        {"userId": user_id, "input.retest": True},
        {"topicId": 1},
    ):
        topic_id = row.get("topicId")
        if topic_id:
            retest_counts[topic_id] = retest_counts.get(topic_id, 0) + 1

    topic_projection = {
        "_id": 1,
        "userId": 1,
        "name": 1,
        "firstStudied": 1,
        "lastStudied": 1,
        "summary": 1,
        "keyConcepts": 1,
        "progress": 1,
    }
    topics = []
    for topic in db.topics.find(
        {"userId": user_id, "progress.sessionsCompleted": {"$gt": 0}},
        topic_projection,
    ):
        item = out(topic)
        item["retestsUsed"] = retest_counts.get(item.get("id"), 0)
        topics.append(item)

    topic_ids = [topic["id"] for topic in topics]
    session_ids_by_topic: dict[str, list[str]] = {topic_id: [] for topic_id in topic_ids}
    if topic_ids:
        for topic_id, session_id in current_session().execute(
            select(TopicSession.topicId, TopicSession.sessionId).where(TopicSession.topicId.in_(topic_ids))
        ):
            session_ids_by_topic[topic_id].append(session_id)
    for topic in topics:
        topic["sessionIds"] = session_ids_by_topic[topic["id"]]

    return {
        **u,
        "role": normalize_role(user.get("role")),
        **({"isGuest": True} if user.get("isGuest") else {}),
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


@app.post("/api/classrooms/{classroom_id}/curriculum/generate")
def generate_classroom_curriculum_route(
    classroom_id: str,
    body: CurriculumGenerateIn,
    user: dict = Depends(current_user),
):
    classroom = db.classrooms.find_one({"_id": classroom_id}, {"ownerId": 1})
    if not classroom:
        raise err(404, "not_found", "Classroom not found.")
    if classroom.get("ownerId") != user["id"]:
        raise err(403, "forbidden", "Only the classroom owner can generate its curriculum.")
    try:
        return generate_curriculum(body.prompt, body.provider, body.model)
    except LLMError as exc:
        raise err(504 if exc.code == "timeout" else 502, exc.code, exc.message)


@app.post("/api/classrooms/{classroom_id}/curriculum/draft")
def apply_classroom_curriculum_draft_route(
    classroom_id: str,
    body: CurriculumDraftApplyIn,
    user: dict = Depends(current_user),
):
    require_classroom_editor(classroom_id, user)
    module_position = db.classroom_modules.count_documents({"classroomId": classroom_id})
    for module_offset, draft_module in enumerate(body.modules):
        module_id = f"module_{uuid.uuid4().hex[:12]}"
        db.classroom_modules.insert_one({
            "_id": module_id,
            "classroomId": classroom_id,
            "title": draft_module.title.strip(),
            "description": draft_module.description.strip(),
            "position": module_position + module_offset,
            "createdAt": now_iso(),
            "updatedAt": now_iso(),
        })
        for topic_position, draft_topic in enumerate(draft_module.topics):
            db.classroom_curriculum_topics.insert_one({
                "_id": f"topic_{uuid.uuid4().hex[:12]}",
                "classroomId": classroom_id,
                "moduleId": module_id,
                "title": draft_topic.title.strip(),
                "description": draft_topic.description.strip(),
                "learningObjectives": [value.strip() for value in draft_topic.learningObjectives if value.strip()],
                "prerequisites": draft_topic.prerequisites,
                "concepts": [concept.model_dump() for concept in draft_topic.concepts],
                "materials": [material.model_dump() for material in draft_topic.materials],
                "position": topic_position,
                "published": False,
                "createdAt": now_iso(),
                "updatedAt": now_iso(),
            })
    return get_classroom_curriculum(classroom_id, user)


@app.get("/api/auth/session")
def auth_session(request: Request, response: Response):
    session_id = request.cookies.get(SESSION_COOKIE)
    status = auth_session_status(session_id)
    if not status["authenticated"]:
        response.delete_cookie(
            key=SESSION_COOKIE,
            path="/",
            secure=SESSION_COOKIE_SECURE,
            samesite=SESSION_COOKIE_SAMESITE,
            domain=SESSION_COOKIE_DOMAIN,
        )
    return status


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


@app.patch("/api/classrooms/{classroom_id}")
def update_classroom_route(classroom_id: str, body: ClassroomCreateIn, user: dict = Depends(current_user)):
    return update_classroom(classroom_id, body.model_dump(), user)


@app.post("/api/classrooms/join")
def join_classroom_route(body: dict, user: dict = Depends(current_user)):
    return join_classroom(body, user)


@app.delete("/api/classrooms/{classroom_id}")
def delete_classroom_route(classroom_id: str, user: dict = Depends(current_user)):
    return delete_classroom(classroom_id, user)


@app.post("/api/classrooms/{classroom_id}/undo-delete")
def undo_delete_classroom_route(classroom_id: str, body: dict, user: dict = Depends(current_user)):
    token = str(body.get("undoToken", ""))
    if not token:
        raise err(400, "invalid_undo", "An undo token is required.")
    return undo_delete_classroom(classroom_id, token, user)


@app.get("/api/classrooms/{classroom_id}")
def get_classroom_route(classroom_id: str, user: dict = Depends(current_user)):
    return get_classroom(classroom_id, user)


@app.get("/api/classrooms/{classroom_id}/members")
def get_classroom_members_route(classroom_id: str, user: dict = Depends(current_user)):
    return get_classroom_members(classroom_id, user)


@app.post("/api/classrooms/{classroom_id}/members")
def add_classroom_member_route(classroom_id: str, body: ClassroomMemberAddIn, user: dict = Depends(current_user)):
    return add_classroom_member(classroom_id, body.model_dump(), user)


@app.patch("/api/classrooms/{classroom_id}/members/{user_id}/role")
def update_classroom_member_role_route(classroom_id: str, user_id: str, body: ClassroomMemberRoleUpdateIn, user: dict = Depends(current_user)):
    return update_classroom_member_role(classroom_id, user_id, body.model_dump(), user)


@app.post("/api/classrooms/{classroom_id}/members/{user_id}/role")
def update_classroom_member_role_post_route(classroom_id: str, user_id: str, body: ClassroomMemberRoleUpdateIn, user: dict = Depends(current_user)):
    return update_classroom_member_role(classroom_id, user_id, body.model_dump(), user)


@app.delete("/api/classrooms/{classroom_id}/members/{user_id}")
def remove_classroom_member_route(classroom_id: str, user_id: str, user: dict = Depends(current_user)):
    return remove_classroom_member(classroom_id, user_id, user)


@app.get("/api/classrooms/{classroom_id}/curriculum")
def get_classroom_curriculum_route(classroom_id: str, user: dict = Depends(current_user)):
    return get_classroom_curriculum(classroom_id, user)


@app.post("/api/classrooms/{classroom_id}/curriculum/publish")
def publish_classroom_curriculum_route(classroom_id: str, user: dict = Depends(current_user)):
    return publish_classroom_curriculum(classroom_id, user)


@app.get("/api/classrooms/{classroom_id}/progress")
def classroom_progress_route(classroom_id: str, user: dict = Depends(current_user)):
    return classroom_progress(classroom_id, user)


@app.get("/api/classrooms/{classroom_id}/topics/{topic_id}/sessions")
def classroom_topic_sessions_route(classroom_id: str, topic_id: str, user: dict = Depends(current_user)):
    return classroom_topic_sessions(classroom_id, topic_id, user)


@app.post("/api/classrooms/{classroom_id}/revision-tasks/{task_id}/generate")
def generate_adaptive_revision_route(classroom_id: str, task_id: str, user: dict = Depends(current_user)):
    return generate_adaptive_revision(classroom_id, task_id, user)


@app.post("/api/classrooms/{classroom_id}/revision-tasks/{task_id}/complete")
def complete_adaptive_revision_route(classroom_id: str, task_id: str, user: dict = Depends(current_user)):
    return complete_adaptive_revision(classroom_id, task_id, user)


@app.post("/api/classrooms/{classroom_id}/revision-tasks/{task_id}/retest")
def create_adaptive_retest_route(classroom_id: str, task_id: str, user: dict = Depends(current_user)):
    return create_adaptive_retest(classroom_id, task_id, user)


@app.get("/api/classrooms/{classroom_id}/analytics")
def classroom_analytics_route(classroom_id: str, user: dict = Depends(current_user)):
    return classroom_analytics(classroom_id, user)


@app.get("/api/classrooms/{classroom_id}/graph")
def classroom_graph_route(classroom_id: str, student_id: str | None = None, user: dict = Depends(current_user)):
    return classroom_knowledge_graph(classroom_id, user, student_id)


@app.get("/api/classrooms/{classroom_id}/stream")
def classroom_stream_route(classroom_id: str, user: dict = Depends(current_user)):
    return list_classroom_posts(classroom_id, user)


@app.post("/api/classrooms/{classroom_id}/stream")
def create_classroom_post_route(classroom_id: str, body: ClassroomPostIn, user: dict = Depends(current_user)):
    return create_classroom_post(classroom_id, body, user)


@app.post("/api/classrooms/{classroom_id}/stream/{post_id}/replies")
def create_classroom_reply_route(classroom_id: str, post_id: str, body: ClassroomReplyIn, user: dict = Depends(current_user)):
    return create_classroom_reply(classroom_id, post_id, body, user)


@app.post("/api/classrooms/{classroom_id}/modules")
def create_curriculum_module_route(classroom_id: str, body: CurriculumModuleIn, user: dict = Depends(current_user)):
    return create_curriculum_module(classroom_id, body, user)


@app.post("/api/classrooms/{classroom_id}/modules/{module_id}/topics")
def create_curriculum_topic_route(classroom_id: str, module_id: str, body: CurriculumTopicIn, user: dict = Depends(current_user)):
    return create_curriculum_topic(classroom_id, module_id, body, user)


@app.delete("/api/classrooms/{classroom_id}/modules/{module_id}")
def delete_curriculum_module_route(classroom_id: str, module_id: str, user: dict = Depends(current_user)):
    return delete_curriculum_module(classroom_id, module_id, user)


@app.delete("/api/classrooms/{classroom_id}/topics/{topic_id}")
def delete_curriculum_topic_route(classroom_id: str, topic_id: str, user: dict = Depends(current_user)):
    return delete_curriculum_topic(classroom_id, topic_id, user)


@app.get("/api/classrooms/{classroom_id}/classwork")
def list_classroom_assessments_route(classroom_id: str, user: dict = Depends(current_user)):
    return list_classroom_assessments(classroom_id, user)


@app.post("/api/classrooms/{classroom_id}/classwork")
def create_classroom_assessment_route(classroom_id: str, body: ClassroomAssessmentIn, user: dict = Depends(current_user)):
    return create_classroom_assessment(classroom_id, body, user)


@app.post("/api/classrooms/{classroom_id}/classwork/{assessment_id}/submissions")
def submit_classroom_assessment_route(classroom_id: str, assessment_id: str, body: ClassroomSubmissionIn, user: dict = Depends(current_user)):
    return submit_classroom_assessment(classroom_id, assessment_id, body, user)


@app.get("/api/classrooms/{classroom_id}/classwork/{assessment_id}/submissions")
def list_classroom_submissions_route(classroom_id: str, assessment_id: str, user: dict = Depends(current_user)):
    return list_classroom_submissions(classroom_id, assessment_id, user)


@app.patch("/api/classrooms/{classroom_id}/classwork/{assessment_id}/submissions/{submission_id}")
def grade_classroom_submission_route(classroom_id: str, assessment_id: str, submission_id: str, body: ClassroomGradeIn, user: dict = Depends(current_user)):
    return grade_classroom_submission(classroom_id, assessment_id, submission_id, body, user)


@app.post("/api/classrooms/{classroom_id}/classwork/{assessment_id}/submissions/{submission_id}/evaluate")
def evaluate_classroom_submission_route(classroom_id: str, assessment_id: str, submission_id: str, user: dict = Depends(current_user)):
    return evaluate_classroom_submission(classroom_id, assessment_id, submission_id, user)


# =============================================================================
# Classroom Study Materials
# =============================================================================

MATERIALS_STORAGE_DIR = os.path.join(os.path.dirname(__file__), "uploads", "materials")
os.makedirs(MATERIALS_STORAGE_DIR, exist_ok=True)
ALLOWED_MATERIAL_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg",
    ".gif", ".webp", ".txt", ".md", ".csv", ".xlsx", ".xls"
}
MAX_MATERIAL_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB


def upload_classroom_material(classroom_id: str, title: str, description: str, file: UploadFile, user: dict):
    require_classroom_editor(classroom_id, user)
    if not file.filename:
        raise err(400, "invalid_file", "No file provided.")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_MATERIAL_EXTENSIONS:
        raise err(400, "unsupported_file_type", f"Unsupported file type '{ext}'. Supported formats: PDF, Word (.doc/.docx), PowerPoint (.ppt/.pptx), Images, and Text files.")
    raw = file.file.read()
    if len(raw) == 0:
        raise err(400, "empty_file", "The uploaded file is empty.")
    if len(raw) > MAX_MATERIAL_SIZE_BYTES:
        raise err(400, "file_too_large", "File size exceeds the maximum limit of 25 MB.")

    material_id = f"mat_{uuid.uuid4().hex[:12]}"
    clean_filename = re.sub(r"[^a-zA-Z0-9_.-]", "_", file.filename)
    dest_dir = os.path.join(MATERIALS_STORAGE_DIR, classroom_id)
    os.makedirs(dest_dir, exist_ok=True)
    storage_path = os.path.join(dest_dir, f"{material_id}_{clean_filename}")
    with open(storage_path, "wb") as f:
        f.write(raw)

    material = {
        "_id": material_id,
        "classroomId": classroom_id,
        "title": title.strip() or file.filename,
        "description": description.strip(),
        "filename": file.filename,
        "fileType": file.content_type or "application/octet-stream",
        "fileSize": len(raw),
        "storagePath": storage_path,
        "uploadedBy": user["id"],
        "createdAt": now(),
        "updatedAt": now(),
    }
    db.classroom_materials.insert_one(material)
    res = {k: v for k, v in material.items() if k not in ("_id", "storagePath")}
    res["id"] = material_id
    res["uploadedByName"] = user.get("name") or "Teacher"
    return res


def list_classroom_materials(classroom_id: str, user: dict):
    get_classroom(classroom_id, user)
    materials = list(db.classroom_materials.find({"classroomId": classroom_id}))
    materials.sort(key=lambda m: m.get("createdAt", now()), reverse=True)
    uploader_ids = list({m.get("uploadedBy") for m in materials if m.get("uploadedBy")})
    uploaders = {u["_id"]: u.get("name") for u in db.users.find({"_id": {"$in": uploader_ids}})} if uploader_ids else {}
    result = []
    for m in materials:
        item = {k: v for k, v in m.items() if k not in ("_id", "storagePath")}
        item["id"] = m["_id"]
        item["uploadedByName"] = uploaders.get(m.get("uploadedBy")) or "Teacher"
        result.append(item)
    return result


def download_classroom_material(classroom_id: str, material_id: str, user: dict, inline: bool = False):
    get_classroom(classroom_id, user)
    material = db.classroom_materials.find_one({"_id": material_id, "classroomId": classroom_id})
    if not material:
        raise err(404, "not_found", "Study material not found.")
    storage_path = material.get("storagePath")
    if not storage_path or not os.path.exists(storage_path):
        raise err(404, "file_missing", "The requested file is no longer available on disk.")

    filename = material.get("filename", "download")
    ext = os.path.splitext(filename)[1].lower()
    media_type = material.get("fileType") or "application/octet-stream"
    if ext == ".pdf":
        media_type = "application/pdf"
    elif ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        media_type = f"image/{ext.lstrip('.')}"
    elif ext in {".txt", ".md", ".csv"}:
        media_type = "text/plain"

    disposition = "inline" if inline else "attachment"
    return FileResponse(
        path=storage_path,
        media_type=media_type,
        content_disposition_type=disposition,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


def update_classroom_material(classroom_id: str, material_id: str, payload: ClassroomMaterialUpdateIn, user: dict):
    require_classroom_editor(classroom_id, user)
    material = db.classroom_materials.find_one({"_id": material_id, "classroomId": classroom_id})
    if not material:
        raise err(404, "not_found", "Study material not found.")
    updates = {"title": payload.title.strip(), "description": (payload.description or "").strip(), "updatedAt": now()}
    db.classroom_materials.update_one({"_id": material_id}, {"$set": updates})
    updated = db.classroom_materials.find_one({"_id": material_id}) or material
    res = {k: v for k, v in updated.items() if k not in ("_id", "storagePath")}
    res["id"] = material_id
    uploader = db.users.find_one({"_id": updated.get("uploadedBy")}) or {}
    res["uploadedByName"] = uploader.get("name") or "Teacher"
    return res


def delete_classroom_material(classroom_id: str, material_id: str, user: dict):
    require_classroom_editor(classroom_id, user)
    material = db.classroom_materials.find_one({"_id": material_id, "classroomId": classroom_id})
    if not material:
        raise err(404, "not_found", "Study material not found.")
    storage_path = material.get("storagePath")
    if storage_path and os.path.exists(storage_path):
        try:
            os.remove(storage_path)
        except OSError:
            pass
    db.classroom_materials.delete_one({"_id": material_id})
    return {"deleted": True, "id": material_id}


# =============================================================================
# Classroom Lecture Videos
# =============================================================================

def create_classroom_lecture(classroom_id: str, payload: ClassroomLectureIn, user: dict):
    require_classroom_editor(classroom_id, user)
    info = parse_video_url(payload.videoUrl)
    if not info["valid"]:
        raise err(400, "invalid_video_url", info["message"])

    duration = payload.durationSeconds if (payload.durationSeconds and payload.durationSeconds > 0) else (info.get("durationSeconds") or 0)

    lecture_id = f"lec_{uuid.uuid4().hex[:12]}"
    if payload.position is None or payload.position == 0:
        existing = list(db.classroom_lectures.find({"classroomId": classroom_id}))
        pos = max([lec.get("position", 0) for lec in existing], default=0) + 1
    else:
        pos = payload.position

    lecture = {
        "_id": lecture_id,
        "classroomId": classroom_id,
        "title": payload.title.strip(),
        "description": (payload.description or "").strip(),
        "videoUrl": payload.videoUrl.strip(),
        "platform": info["platform"],
        "embedUrl": info["embedUrl"],
        "durationSeconds": duration,
        "completionThreshold": max(1, min(100, payload.completionThreshold)),
        "position": pos,
        "trackingSupported": info["trackingSupported"],
        "createdBy": user["id"],
        "createdAt": now(),
        "updatedAt": now(),
    }
    db.classroom_lectures.insert_one(lecture)
    res = {k: v for k, v in lecture.items() if k != "_id"}
    res["id"] = lecture_id
    return res


def list_classroom_lectures(classroom_id: str, user: dict):
    classroom = get_classroom(classroom_id, user)
    lectures = list(db.classroom_lectures.find({"classroomId": classroom_id}))
    lectures.sort(key=lambda l: (l.get("position", 0), l.get("createdAt", now())))

    progress_by_lecture = {}
    rows = list(db.classroom_lecture_progress.find({"classroomId": classroom_id, "studentId": user["id"]}))
    progress_by_lecture = {r["lectureId"]: r for r in rows}

    result = []
    for l in lectures:
        item = {k: v for k, v in l.items() if k != "_id"}
        item["id"] = l["_id"]
        if item.get("platform") == "gdrive":
            item["trackingSupported"] = True
        p = progress_by_lecture.get(l["_id"])
        if p:
            item["progress"] = {
                "watchedSeconds": p.get("watchedSeconds", 0.0),
                "lastPositionSeconds": p.get("lastPositionSeconds", 0.0),
                "watchPercent": p.get("watchPercent", 0.0),
                "completed": p.get("completed", False),
                "status": "completed" if p.get("completed") else ("in_progress" if p.get("watchedSeconds", 0) > 0 else "not_started"),
            }
        else:
            item["progress"] = {
                "watchedSeconds": 0.0,
                "lastPositionSeconds": 0.0,
                "watchPercent": 0.0,
                "completed": False,
                "status": "not_started",
            }
        result.append(item)
    return result


def update_classroom_lecture(classroom_id: str, lecture_id: str, payload: ClassroomLectureUpdateIn, user: dict):
    require_classroom_editor(classroom_id, user)
    lecture = db.classroom_lectures.find_one({"_id": lecture_id, "classroomId": classroom_id})
    if not lecture:
        raise err(404, "not_found", "Lecture not found.")

    updates = {"updatedAt": now()}
    if payload.title is not None:
        updates["title"] = payload.title.strip()
    if payload.description is not None:
        updates["description"] = payload.description.strip()
    if payload.durationSeconds is not None:
        updates["durationSeconds"] = payload.durationSeconds
    if payload.position is not None:
        updates["position"] = payload.position
    if payload.completionThreshold is not None:
        threshold = max(1, min(100, payload.completionThreshold))
        updates["completionThreshold"] = threshold
        all_progress = list(db.classroom_lecture_progress.find({"lectureId": lecture_id}))
        for prg in all_progress:
            is_comp = prg.get("watchPercent", 0.0) >= threshold
            if is_comp != prg.get("completed", False):
                db.classroom_lecture_progress.update_one(
                    {"_id": prg["_id"]},
                    {"$set": {"completed": is_comp, "completedAt": now() if is_comp else None, "updatedAt": now()}},
                )
    if payload.videoUrl is not None and payload.videoUrl.strip() != lecture.get("videoUrl"):
        info = parse_video_url(payload.videoUrl)
        if not info["valid"]:
            raise err(400, "invalid_video_url", info["message"])
        updates["videoUrl"] = payload.videoUrl.strip()
        updates["platform"] = info["platform"]
        updates["embedUrl"] = info["embedUrl"]
        updates["trackingSupported"] = True if info["platform"] == "gdrive" else info["trackingSupported"]

    db.classroom_lectures.update_one({"_id": lecture_id}, {"$set": updates})
    updated = db.classroom_lectures.find_one({"_id": lecture_id}) or lecture
    res = {k: v for k, v in updated.items() if k != "_id"}
    res["id"] = lecture_id
    return res


def delete_classroom_lecture(classroom_id: str, lecture_id: str, user: dict):
    require_classroom_editor(classroom_id, user)
    lecture = db.classroom_lectures.find_one({"_id": lecture_id, "classroomId": classroom_id})
    if not lecture:
        raise err(404, "not_found", "Lecture not found.")
    db.classroom_lectures.delete_one({"_id": lecture_id})
    db.classroom_lecture_progress.delete_many({"lectureId": lecture_id})
    return {"deleted": True, "id": lecture_id}


def record_lecture_progress(classroom_id: str, lecture_id: str, payload: ClassroomLectureProgressIn, user: dict):
    get_classroom(classroom_id, user)
    lecture = db.classroom_lectures.find_one({"_id": lecture_id, "classroomId": classroom_id})
    if not lecture:
        raise err(404, "not_found", "Lecture not found.")

    total_dur = payload.totalDurationSeconds
    if total_dur <= 0:
        total_dur = float(lecture.get("durationSeconds", 0))
    if total_dur <= 0:
        total_dur = 3600.0

    watched = min(payload.watchedSeconds, total_dur)
    last_pos = min(payload.lastPositionSeconds, total_dur)
    watch_pct = round(min(100.0, (watched / total_dur) * 100.0), 1)

    threshold = lecture.get("completionThreshold", 100)
    is_completed = watch_pct >= threshold

    existing = db.classroom_lecture_progress.find_one({"lectureId": lecture_id, "studentId": user["id"]})
    if existing:
        highest_watched = max(watched, existing.get("watchedSeconds", 0.0))
        highest_pct = round(min(100.0, (highest_watched / total_dur) * 100.0), 1)
        was_completed = existing.get("completed", False)
        comp = was_completed or (highest_pct >= threshold)

        updates = {
            "watchedSeconds": highest_watched,
            "lastPositionSeconds": last_pos,
            "totalDurationSeconds": total_dur,
            "watchPercent": highest_pct,
            "completed": comp,
            "completedAt": (existing.get("completedAt") or now()) if comp else None,
            "updatedAt": now(),
        }
        db.classroom_lecture_progress.update_one({"_id": existing["_id"]}, {"$set": updates})
        return {
            "lectureId": lecture_id,
            "studentId": user["id"],
            "watchedSeconds": highest_watched,
            "lastPositionSeconds": last_pos,
            "totalDurationSeconds": total_dur,
            "watchPercent": highest_pct,
            "completed": comp,
            "status": "completed" if comp else ("in_progress" if highest_watched > 0 else "not_started"),
        }
    else:
        progress_id = f"prog_{uuid.uuid4().hex[:12]}"
        doc = {
            "_id": progress_id,
            "classroomId": classroom_id,
            "lectureId": lecture_id,
            "studentId": user["id"],
            "watchedSeconds": watched,
            "lastPositionSeconds": last_pos,
            "totalDurationSeconds": total_dur,
            "watchPercent": watch_pct,
            "completed": is_completed,
            "completedAt": now() if is_completed else None,
            "createdAt": now(),
            "updatedAt": now(),
        }
        db.classroom_lecture_progress.insert_one(doc)
        return {
            "lectureId": lecture_id,
            "studentId": user["id"],
            "watchedSeconds": watched,
            "lastPositionSeconds": last_pos,
            "totalDurationSeconds": total_dur,
            "watchPercent": watch_pct,
            "completed": is_completed,
            "status": "completed" if is_completed else ("in_progress" if watched > 0 else "not_started"),
        }


def get_classroom_lecture_analytics(classroom_id: str, user: dict):
    classroom = require_classroom_editor(classroom_id, user)
    lectures = list(db.classroom_lectures.find({"classroomId": classroom_id}))
    lectures.sort(key=lambda l: (l.get("position", 0), l.get("createdAt", now())))

    students = [m for m in classroom.get("members", []) if m.get("role") == "STUDENT"]
    total_students = len(students)

    lecture_analytics = []
    for l in lectures:
        threshold = l.get("completionThreshold", 100)
        progress_rows = list(db.classroom_lecture_progress.find({"lectureId": l["_id"]}))
        progress_by_student = {p["studentId"]: p for p in progress_rows}

        student_details = []
        completed_count = 0
        in_progress_count = 0
        not_started_count = 0
        total_watch_percent = 0.0

        for s in students:
            sid = s["userId"]
            sname = s.get("name") or "Student"
            p = progress_by_student.get(sid)
            if p:
                pct = p.get("watchPercent", 0.0)
                is_comp = p.get("completed", False) or (pct >= threshold)
                if is_comp:
                    status = "completed"
                    completed_count += 1
                elif pct > 0:
                    status = "in_progress"
                    in_progress_count += 1
                else:
                    status = "not_started"
                    not_started_count += 1
                total_watch_percent += pct
                student_details.append({
                    "studentId": sid,
                    "studentName": sname,
                    "watchPercent": pct,
                    "watchedSeconds": p.get("watchedSeconds", 0.0),
                    "status": status,
                })
            else:
                not_started_count += 1
                student_details.append({
                    "studentId": sid,
                    "studentName": sname,
                    "watchPercent": 0.0,
                    "watchedSeconds": 0.0,
                    "status": "not_started",
                })

        avg_watch = round(total_watch_percent / total_students, 1) if total_students > 0 else 0.0
        lecture_analytics.append({
            "lectureId": l["_id"],
            "title": l.get("title", ""),
            "durationSeconds": l.get("durationSeconds", 0),
            "completionThreshold": threshold,
            "platform": l.get("platform", "other"),
            "trackingSupported": l.get("trackingSupported", True),
            "totalEnrolled": total_students,
            "completedCount": completed_count,
            "inProgressCount": in_progress_count,
            "notStartedCount": not_started_count,
            "averageWatchPercent": avg_watch,
            "students": student_details,
        })

    return {
        "classroomId": classroom_id,
        "totalStudents": total_students,
        "lectures": lecture_analytics,
    }


# =============================================================================
# FastAPI Route Handlers for Materials & Lectures
# =============================================================================

@app.post("/api/classrooms/{classroom_id}/materials")
def upload_classroom_material_route(
    classroom_id: str,
    title: str = Form(""),
    description: str = Form(""),
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
):
    return upload_classroom_material(classroom_id, title, description, file, user)


@app.get("/api/classrooms/{classroom_id}/materials")
def list_classroom_materials_route(classroom_id: str, user: dict = Depends(current_user)):
    return list_classroom_materials(classroom_id, user)


@app.get("/api/classrooms/{classroom_id}/materials/{material_id}/download")
def download_classroom_material_route(classroom_id: str, material_id: str, inline: bool = False, user: dict = Depends(current_user)):
    return download_classroom_material(classroom_id, material_id, user, inline=inline)


@app.get("/api/classrooms/{classroom_id}/materials/{material_id}/view")
def view_classroom_material_route(classroom_id: str, material_id: str, user: dict = Depends(current_user)):
    return download_classroom_material(classroom_id, material_id, user, inline=True)


@app.patch("/api/classrooms/{classroom_id}/materials/{material_id}")
def update_classroom_material_route(
    classroom_id: str,
    material_id: str,
    body: ClassroomMaterialUpdateIn,
    user: dict = Depends(current_user),
):
    return update_classroom_material(classroom_id, material_id, body, user)


@app.delete("/api/classrooms/{classroom_id}/materials/{material_id}")
def delete_classroom_material_route(classroom_id: str, material_id: str, user: dict = Depends(current_user)):
    return delete_classroom_material(classroom_id, material_id, user)


@app.post("/api/classrooms/{classroom_id}/lectures")
def create_classroom_lecture_route(
    classroom_id: str,
    body: ClassroomLectureIn,
    user: dict = Depends(current_user),
):
    return create_classroom_lecture(classroom_id, body, user)


@app.get("/api/classrooms/{classroom_id}/lectures")
def list_classroom_lectures_route(classroom_id: str, user: dict = Depends(current_user)):
    return list_classroom_lectures(classroom_id, user)


@app.patch("/api/classrooms/{classroom_id}/lectures/{lecture_id}")
def update_classroom_lecture_route(
    classroom_id: str,
    lecture_id: str,
    body: ClassroomLectureUpdateIn,
    user: dict = Depends(current_user),
):
    return update_classroom_lecture(classroom_id, lecture_id, body, user)


@app.delete("/api/classrooms/{classroom_id}/lectures/{lecture_id}")
def delete_classroom_lecture_route(classroom_id: str, lecture_id: str, user: dict = Depends(current_user)):
    return delete_classroom_lecture(classroom_id, lecture_id, user)


@app.post("/api/classrooms/{classroom_id}/lectures/{lecture_id}/progress")
def record_lecture_progress_route(
    classroom_id: str,
    lecture_id: str,
    body: ClassroomLectureProgressIn,
    user: dict = Depends(current_user),
):
    return record_lecture_progress(classroom_id, lecture_id, body, user)


@app.get("/api/classrooms/{classroom_id}/lectures-analytics")
def get_classroom_lecture_analytics_route(classroom_id: str, user: dict = Depends(current_user)):
    return get_classroom_lecture_analytics(classroom_id, user)


@app.post("/api/classrooms/{classroom_id}/lectures/validate-url")
def validate_lecture_url_route(
    classroom_id: str,
    body: dict,
    user: dict = Depends(current_user),
):
    require_classroom_editor(classroom_id, user)
    url = body.get("videoUrl", "")
    return parse_video_url(url)

