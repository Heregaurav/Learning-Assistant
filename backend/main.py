import base64
import json
import os, re, uuid
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError

from models import CompleteIn, GoogleAuthIn, LearnIn, RefineIn
from llm import generate_lesson, generate_retest_quiz, refine_lesson, LLMError

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
bearer = HTTPBearer(auto_error=False)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def err(status: int, code: str, message: str):
    return HTTPException(status, detail={"code": code, "message": message})


def out(doc):
    if doc is not None and "_id" in doc:
        doc["id"] = doc.pop("_id")
    return doc


def level(score: int) -> str:
    return "Strong" if score >= 85 else "Good" if score >= 70 else "Needs review"


def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials:
        raise err(401, "auth_required", "Sign in with Google to continue.")
    if not GOOGLE_CLIENT_ID:
        raise err(503, "auth_not_configured", "Set GOOGLE_CLIENT_ID in backend/.env.")
    try:
        claims = id_token.verify_oauth2_token(
            credentials.credentials,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=GOOGLE_CLOCK_SKEW_SECONDS,
        )
    except ValueError as exc:
        reason = str(exc).lower()
        claim_audience = "unknown"
        try:
            encoded_claims = credentials.credentials.split(".")[1]
            encoded_claims += "=" * (-len(encoded_claims) % 4)
            claim_audience = json.loads(base64.urlsafe_b64decode(encoded_claims)).get(
                "aud", "unknown"
            )
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
            raise err(
                401,
                "auth_expired",
                "Your Google sign-in has expired. Please sign in again.",
            )
        raise err(
            401,
            "invalid_auth",
            "Google rejected this sign-in token. Check the OAuth client ID and authorized origin.",
        )
    except GoogleAuthError:
        logger.warning("Google token rejected: google_auth_error")
        raise err(
            401,
            "invalid_auth",
            "Google rejected this sign-in token. Check the OAuth client ID and authorized origin.",
        )
    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise err(401, "invalid_auth", "Invalid Google identity.")
    user_id = claims["sub"]
    db.users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "name": claims.get("name", "Learner"),
                "email": claims.get("email", ""),
                "picture": claims.get("picture", ""),
                "updatedAt": now(),
            },
            "$setOnInsert": {
                "createdAt": now(),
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
    return {
        "id": user_id,
        "name": claims.get("name", "Learner"),
        "email": claims.get("email", ""),
        "picture": claims.get("picture", ""),
    }


@app.post("/api/auth/google")
def google_auth(body: GoogleAuthIn):
    if not GOOGLE_CLIENT_ID:
        raise err(503, "auth_not_configured", "Set GOOGLE_CLIENT_ID in backend/.env.")
    user = current_user(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=body.credential)
    )
    return {"user": user, "token": body.credential}


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
    sid, tid = f"session_{uuid.uuid4().hex[:12]}", "topic_" + re.sub(
        r"[^a-z0-9]+", "_", lesson.topic.lower()
    ).strip("_")
    data = lesson.model_dump()
    user_id = user["id"]
    db.sessions.insert_one(
        {
            "_id": sid,
            "userId": user_id,
            "topicId": tid,
            "topic": lesson.topic,
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


@app.post("/api/learn/stream")
def learn_stream(body: LearnIn, user: dict = Depends(current_user)):
    def events():
        yield 'data: {"stage":"understanding"}\n\n'
        try:
            lesson = generate_lesson(body.content, body.difficulty, body.provider, body.model)
            yield 'data: {"stage":"building"}\n\n'
            sid, tid = f"session_{uuid.uuid4().hex[:12]}", "topic_" + re.sub(
                r"[^a-z0-9]+", "_", lesson.topic.lower()
            ).strip("_")
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
    # topic progress = mean score of its completed sessions (idempotent on re-complete)
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
    return {"sessionId": sid, "learningContent": data}


@app.get("/api/profile")
def profile(user: dict = Depends(current_user)):
    user_id = user["id"]
    u = out(db.users.find_one({"_id": user_id}))
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
    # no invented relationships: topics are independent nodes until real links exist
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
