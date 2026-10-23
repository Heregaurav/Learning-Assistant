import os
import sys
import asyncio
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MONGODB_URI", "mongodb://localhost/unused")

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to an isolated PostgreSQL database.",
)

import database  # noqa: E402
import main  # noqa: E402
from orm_models import Base, ClassroomMember, ConceptPrerequisite, TopicSession, User  # noqa: E402
from migrate_mongo_to_postgres import import_batch  # noqa: E402
from persistence import db  # noqa: E402
from models import Explanation, Flashcard, Lesson, QuizQuestion, Section  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_postgres(monkeypatch):
    database.dispose_engine()
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("MIGRATION_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setattr(main, "db", db)
    engine = database.get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
    database.dispose_engine()


def _add_users():
    db.users.insert_one({"_id": "faculty-postgres", "name": "Faculty", "role": "FACULTY"})
    db.users.insert_one({"_id": "student-postgres", "name": "Student", "role": "STUDENT"})


def _faculty():
    return {"id": "faculty-postgres", "name": "Faculty", "role": "FACULTY"}


def _student():
    return {"id": "student-postgres", "name": "Student", "role": "STUDENT"}


def _seed_curriculum_case():
    _add_users()
    owner = _faculty()
    student = _student()
    classroom = main.create_classroom(
        {"name": "Curriculum", "subject": "CS", "section": "A", "semester": "Fall", "description": "Ordered curriculum"},
        owner,
    )
    main.join_classroom({"joinCode": classroom["joinCode"]}, student)

    later_module = main.create_curriculum_module(
        classroom["id"], main.CurriculumModuleIn(title="Later module", position=9), owner
    )
    later_second = main.create_curriculum_topic(
        classroom["id"], later_module["id"], main.CurriculumTopicIn(title="Later second"), owner
    )
    later_first = main.create_curriculum_topic(
        classroom["id"], later_module["id"], main.CurriculumTopicIn(title="Later first"), owner
    )

    earlier_module = main.create_curriculum_module(
        classroom["id"], main.CurriculumModuleIn(title="Earlier module", position=0), owner
    )
    earlier_second = main.create_curriculum_topic(
        classroom["id"], earlier_module["id"], main.CurriculumTopicIn(title="Earlier second"), owner
    )
    earlier_first = main.create_curriculum_topic(
        classroom["id"], earlier_module["id"], main.CurriculumTopicIn(title="Earlier first"), owner
    )

    main.publish_classroom_curriculum(classroom["id"], owner)
    db.classroom_curriculum_topics.update_one(
        {"_id": earlier_second["id"], "classroomId": classroom["id"]},
        {"$set": {"published": False}},
    )
    return classroom, owner, student, [later_second, later_first, earlier_second, earlier_first]


def test_concurrent_join_is_idempotent_and_preserves_membership():
    with database.session_scope():
        _add_users()
        classroom = main.create_classroom(
            {"name": "Persistence", "subject": "DB", "section": "A", "semester": "Fall", "description": ""},
            _faculty(),
        )

    def join():
        with database.session_scope():
            return main.join_classroom({"joinCode": classroom["joinCode"]}, _student())

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: join(), range(2)))

    assert all(result["memberCount"] == 2 for result in results)
    with database.session_scope():
        membership_count = database.current_session().scalar(
            select(func.count()).select_from(ClassroomMember).where(
                ClassroomMember.classroomId == classroom["id"],
                ClassroomMember.userId == "student-postgres",
            )
        )
    assert membership_count == 1


def test_curriculum_response_preserves_order_visibility_and_join_code_privacy():
    with database.session_scope():
        classroom, owner, student, topics = _seed_curriculum_case()

    with database.session_scope():
        owner_result = main.get_classroom_curriculum(classroom["id"], owner)
    assert owner_result["status"] == "published"
    assert owner_result["version"] == 1
    assert owner_result["classroom"]["joinCode"] == classroom["joinCode"]
    assert [module["title"] for module in owner_result["modules"]] == ["Earlier module", "Later module"]
    assert [topic["title"] for topic in owner_result["modules"][0]["topics"]] == ["Earlier second", "Earlier first"]
    assert [topic["id"] for topic in owner_result["modules"][1]["topics"]] == [topics[0]["id"], topics[1]["id"]]
    assert set(owner_result["modules"][0]) == {"id", "title", "description", "position", "topics"}
    owner_topic = owner_result["modules"][1]["topics"][0]
    assert {"id", "classroomId", "moduleId", "title", "description", "learningObjectives", "prerequisites", "concepts", "materials", "position", "published", "createdAt", "updatedAt"} <= set(owner_topic)
    assert owner_topic["id"] == topics[0]["id"]
    assert owner_topic["prerequisites"] == []
    assert owner_topic["concepts"] == []
    assert owner_topic["materials"] == []

    with database.session_scope():
        student_result = main.get_classroom_curriculum(classroom["id"], student)
    assert "joinCode" not in student_result["classroom"]
    assert [module["title"] for module in student_result["modules"]] == ["Earlier module", "Later module"]
    assert [topic["title"] for topic in student_result["modules"][0]["topics"]] == ["Earlier first"]
    assert [topic["title"] for topic in student_result["modules"][1]["topics"]] == ["Later second", "Later first"]


def test_draft_curriculum_visibility_and_authorization_contracts():
    with database.session_scope():
        classroom, owner, student, _ = _seed_curriculum_case()
        db.classrooms.update_one({"_id": classroom["id"]}, {"$set": {"curriculumStatus": "draft"}})

    with database.session_scope():
        draft_for_student = main.get_classroom_curriculum(classroom["id"], student)
        draft_for_owner = main.get_classroom_curriculum(classroom["id"], owner)
    assert draft_for_student["status"] == "draft"
    assert draft_for_student["modules"] == []
    assert "joinCode" not in draft_for_student["classroom"]
    assert len(draft_for_owner["modules"]) == 2

    outsider = {"id": "outsider", "role": "STUDENT"}
    with pytest.raises(main.HTTPException) as denied:
        with database.session_scope():
            main.get_classroom_curriculum(classroom["id"], outsider)
    assert denied.value.status_code == 403

    with database.session_scope():
        db.classrooms.update_one({"_id": classroom["id"]}, {"$set": {"deletionState": "pending"}})
    with pytest.raises(main.HTTPException) as hidden:
        with database.session_scope():
            main.get_classroom_curriculum(classroom["id"], owner)
    assert hidden.value.status_code == 404


def test_curriculum_sql_query_count_budget_two_modules_four_topics():
    with database.session_scope():
        classroom, owner, student, _ = _seed_curriculum_case()

    engine = database.get_engine()
    statements = []
    def count_statement(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    from sqlalchemy import event

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        with database.session_scope():
            result = main.get_classroom_curriculum(classroom["id"], student)
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert len(result["modules"]) == 2
    assert sum(len(module["topics"]) for module in result["modules"]) == 3
    assert len(statements) < 10, [" ".join(statement.split()) for statement in statements]


def test_classroom_stream_sql_query_count_avoids_post_reply_n_plus_one():
    with database.session_scope():
        faculty = _faculty()
        student = _student()
        db.users.insert_one({"_id": faculty["id"], "name": faculty["name"], "role": faculty["role"]})
        db.users.insert_one({"_id": student["id"], "name": student["name"], "role": student["role"]})
        classroom = main.create_classroom(
            {"name": "Stream", "subject": "CS", "section": "A", "semester": "Fall", "description": ""},
            faculty,
        )
        main.join_classroom({"joinCode": classroom["joinCode"]}, student)
        post_ids = []
        for i in range(3):
            post = main.create_classroom_post(
                classroom["id"],
                main.ClassroomPostIn(kind="discussion", title=f"Question {i}", body=f"Body {i}"),
                student,
            )
            post_ids.append(post["id"])
            for j in range(3):
                main.create_classroom_reply(
                    classroom["id"],
                    post["id"],
                    main.ClassroomReplyIn(body=f"Reply {i}-{j}"),
                    faculty,
                )

    engine = database.get_engine()
    statements = []

    def count_statement(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    from sqlalchemy import event

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        with database.session_scope():
            original_stream = main.get_classroom(classroom["id"], student)
            posts = list(db.classroom_posts.find({"classroomId": classroom["id"]}))
            posts.sort(key=lambda row: row.get("createdAt", main.now()), reverse=True)
            expected = []
            for post in posts:
                replies = list(db.classroom_replies.find({"classroomId": classroom["id"], "postId": post["_id"]}))
                replies.sort(key=lambda row: row.get("createdAt", main.now()))
                expected.append({
                    **{key: value for key, value in post.items() if key != "_id"},
                    "id": post["_id"],
                    "replies": [
                        {**{key: value for key, value in reply.items() if key != "_id"}, "id": reply["_id"]}
                        for reply in replies
                    ],
                })
            stream_statements_start = len(statements)
            stream = main.list_classroom_posts(classroom["id"], student)
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert original_stream["id"] == classroom["id"]
    assert jsonable_encoder(stream) == jsonable_encoder(expected)
    assert [post["id"] for post in stream] == list(reversed(post_ids))
    assert [reply["body"] for reply in stream[0]["replies"]] == ["Reply 2-0", "Reply 2-1", "Reply 2-2"]
    assert stream[0]["authorId"] == student["id"]
    assert stream[0]["replies"][0]["authorId"] == faculty["id"]
    assert len(statements) - stream_statements_start == 4, [" ".join(statement.split()) for statement in statements]


def test_classroom_stream_authorization_owner_faculty_member_outsider_and_removed_member():
    owner = {"id": "stream-owner", "name": "Owner", "role": "FACULTY"}
    faculty = {"id": "stream-faculty", "name": "Faculty", "role": "FACULTY"}
    member = {"id": "stream-member", "name": "Member", "role": "STUDENT"}
    outsider = {"id": "stream-outsider", "name": "Outsider", "role": "STUDENT"}

    with database.session_scope():
        for user in (owner, faculty, member, outsider):
            db.users.insert_one({"_id": user["id"], "name": user["name"], "role": user["role"]})
        classroom = main.create_classroom(
            {"name": "Stream access", "subject": "CS", "section": "A", "semester": "Fall", "description": ""},
            owner,
        )
        main.join_classroom({"joinCode": classroom["joinCode"]}, faculty)
        main.join_classroom({"joinCode": classroom["joinCode"]}, member)
        db.classrooms.update_one({"_id": classroom["id"]}, {"$set": {"facultyIds": [faculty["id"]]}})

    for user in (owner, faculty, member):
        with database.session_scope():
            assert main.list_classroom_posts(classroom["id"], user) == []

    for user in (outsider, {"id": "stream-pending", "role": "STUDENT"}):
        with pytest.raises(main.HTTPException) as denied:
            with database.session_scope():
                main.list_classroom_posts(classroom["id"], user)
        assert denied.value.status_code == 403

    with database.session_scope():
        current = db.classrooms.find_one({"_id": classroom["id"]})
        db.classrooms.update_one(
            {"_id": classroom["id"]},
            {"$set": {"members": [item for item in current["members"] if item.get("userId") != member["id"]]}},
        )
    with pytest.raises(main.HTTPException) as removed:
        with database.session_scope():
            main.list_classroom_posts(classroom["id"], member)
    assert removed.value.status_code == 403


def test_profile_sql_query_count_budgets_topic_retests_and_recent_history():
    with database.session_scope():
        _add_users()
        topic_data = [
            ("topic-strong", "Strong topic", 90, 2),
            ("topic-review", "Needs review", 60, 3),
            ("topic-new", "New topic", 10, 0),
        ]
        for session_id, topic_id, retest in [
            ("session-1", "topic-strong", True),
            ("session-2", "topic-review", True),
            ("session-3", "topic-review", False),
            ("session-4", "topic-strong", False),
        ]:
            db.sessions.insert_one({
                "_id": session_id,
                "userId": "student-postgres",
                "topicId": topic_id,
                "topic": topic_id,
                "createdAt": main.now(),
                "input": {"retest": retest},
                "learningContent": {"markdown": "ok"},
                "evaluation": {"completed": True},
            })
        for topic_id, title, score, sessions_completed in topic_data:
            session_ids = {
                "topic-strong": ["session-1", "session-4"],
                "topic-review": ["session-2", "session-3"],
                "topic-new": [],
            }[topic_id]
            db.topics.insert_one({
                "_id": topic_id,
                "userId": "student-postgres",
                "name": title,
                "progress": {"score": score, "sessionsCompleted": sessions_completed},
                "lastStudied": main.now(),
                "summary": f"Summary for {title}",
                "keyConcepts": [f"Concept for {title}"],
                "sessionIds": session_ids,
            })

    def original_profile():
        user = _student()
        user_doc = main.out(db.users.find_one({"_id": user["id"]}))
        topics = []
        for row in db.topics.find({"userId": user["id"], "progress.sessionsCompleted": {"$gt": 0}}):
            item = main.out(row)
            item["retestsUsed"] = db.sessions.count_documents(
                {"userId": user["id"], "topicId": item["id"], "input.retest": True}
            )
            topics.append(item)
        return {
            **user_doc,
            "role": main.normalize_role(user.get("role")),
            "strong": [topic for topic in topics if topic["progress"]["score"] >= 80],
            "needsReview": [topic for topic in topics if topic["progress"]["score"] < 70],
            "recent": [
                main.out(row)
                for row in db.sessions.find(
                    {"userId": user["id"]},
                    {"learningContent": 0, "input": 0, "answers": 0},
                ).sort("createdAt", -1).limit(5)
            ],
        }

    with database.session_scope():
        expected = original_profile()

    engine = database.get_engine()
    statements = []

    def count_statement(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    from sqlalchemy import event

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        with database.session_scope():
            result = main.profile(_student())
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert jsonable_encoder(result) == jsonable_encoder(expected)
    assert result["strong"][0]["sessionIds"] == ["session-1", "session-4"]
    assert result["needsReview"][0]["sessionIds"] == ["session-2", "session-3"]
    assert len(result["recent"]) == 4
    assert len(statements) == 5, [" ".join(statement.split()) for statement in statements]


def test_http_guest_cookie_persistence_protected_requests_csrf_logout_and_cors(monkeypatch):
    client = TestClient(main.app)
    origin = "http://localhost:5174"
    headers = {"Origin": origin}

    guest_response = client.post("/api/auth/guest", headers=headers)
    assert guest_response.status_code == 200
    guest = guest_response.json()
    cookie = guest_response.cookies.get(main.SESSION_COOKIE)
    assert cookie
    assert guest["user"]["isGuest"] is True
    assert cookie != guest["user"]["id"]
    set_cookie = guest_response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "path=/" in set_cookie
    assert f"samesite={main.SESSION_COOKIE_SAMESITE}" in set_cookie
    assert f"max-age={main.SESSION_TTL_SECONDS}" in set_cookie
    assert ("secure" in set_cookie) is main.SESSION_COOKIE_SECURE

    status = client.get("/api/auth/session", headers=headers)
    assert status.status_code == 200
    assert status.json()["authenticated"] is True
    assert status.json()["user"]["id"] == guest["user"]["id"]
    assert status.json()["user"]["role"] == "STUDENT"

    profile_response = client.get("/api/profile", headers=headers)
    assert profile_response.status_code == 200
    assert profile_response.json()["isGuest"] is True

    no_csrf = client.post("/api/classrooms/join", json={"joinCode": "UNKNOWN"}, headers=headers)
    assert no_csrf.status_code == 403
    csrf = status.json()["csrfToken"]
    allowed_request = client.post(
        "/api/classrooms/join",
        json={"joinCode": "UNKNOWN"},
        headers={**headers, "X-CSRF-Token": csrf},
    )
    assert allowed_request.status_code == 404
    disallowed_origin_request = client.post(
        "/api/classrooms/join",
        json={"joinCode": "UNKNOWN"},
        headers={"Origin": "https://malicious.example", "X-CSRF-Token": csrf},
    )
    assert disallowed_origin_request.status_code == 403
    assert disallowed_origin_request.json()["detail"]["code"] == "origin_forbidden"

    preflight = client.options(
        "/api/auth/session",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert preflight.headers.get("access-control-allow-origin") == origin
    assert preflight.headers.get("access-control-allow-credentials") == "true"
    disallowed_preflight = client.options(
        "/api/auth/session",
        headers={"Origin": "https://malicious.example", "Access-Control-Request-Method": "GET"},
    )
    assert disallowed_preflight.headers.get("access-control-allow-origin") is None

    logout_response = client.post("/api/auth/logout", headers=headers)
    assert logout_response.status_code == 200
    assert "max-age=0" in logout_response.headers["set-cookie"].lower()
    with database.session_scope():
        assert db.sessions.find_one({"_id": cookie}) is None
    assert client.get("/api/profile", headers=headers).status_code == 401

    client.cookies.clear()
    assert client.get("/api/profile", headers={"X-Guest-ID": guest["user"]["id"]}).status_code == 401


def test_http_expired_guest_session_is_rejected_and_cookie_cleared():
    client = TestClient(main.app)
    response = client.post("/api/auth/guest", headers={"Origin": "http://localhost:5174"})
    session_id = response.cookies.get(main.SESSION_COOKIE)
    assert session_id
    with database.session_scope():
        db.sessions.update_one(
            {"_id": session_id},
            {"$set": {"expires_at": main.now() - main.timedelta(seconds=1)}},
        )

    status = client.get("/api/auth/session", headers={"Origin": "http://localhost:5174"})

    assert status.status_code == 200
    assert status.json() == {"authenticated": False, "user": None}
    assert "max-age=0" in status.headers["set-cookie"].lower()
    client.cookies.set(main.SESSION_COOKIE, session_id)
    protected = client.get("/api/profile")
    assert protected.status_code == 401
    assert "max-age=0" in protected.headers["set-cookie"].lower()


def test_http_google_login_replaces_guest_cookie_without_merging_data(monkeypatch):
    client = TestClient(main.app)
    origin = "http://localhost:5174"
    guest_response = client.post("/api/auth/guest", headers={"Origin": origin})
    old_session_id = guest_response.cookies.get(main.SESSION_COOKIE)
    guest_id = guest_response.json()["user"]["id"]
    with database.session_scope():
        db.topics.insert_one({"_id": "guest-owned-topic", "userId": guest_id, "name": "Guest topic"})
    monkeypatch.setattr(main, "verify_google_credential", lambda _: {
        "sub": "google-http-user", "name": "Google User", "email": "google@example.com",
        "iss": "https://accounts.google.com",
    })

    login = client.post(
        "/api/auth/google",
        json={"credential": "x" * 20},
        headers={"Origin": origin},
    )

    new_session_id = login.cookies.get(main.SESSION_COOKIE)
    assert login.status_code == 200
    assert new_session_id and new_session_id != old_session_id
    assert "csrfToken" in login.json()
    assert new_session_id not in str(login.json())
    with database.session_scope():
        assert db.sessions.find_one({"_id": old_session_id}) is None
        assert db.sessions.find_one({"_id": new_session_id})["user_id"] == "google-http-user"
        assert db.topics.find_one({"_id": "guest-owned-topic"})["userId"] == guest_id
    assert client.get("/api/auth/session").json()["user"]["id"] == "google-http-user"


def test_concurrent_submission_returns_existing_409_contract():
    with database.session_scope():
        _add_users()
        classroom = main.create_classroom(
            {"name": "Assessment", "subject": "DB", "section": "A", "semester": "Fall", "description": ""},
            _faculty(),
        )
        main.join_classroom({"joinCode": classroom["joinCode"]}, _student())
        assessment = main.create_classroom_assessment(
            classroom["id"],
            main.ClassroomAssessmentIn(title="Write", kind="assignment", maxMarks=10, published=True),
            _faculty(),
        )

    def submit():
        with database.session_scope():
            try:
                result = main.submit_classroom_assessment(
                    classroom["id"], assessment["id"], main.ClassroomSubmissionIn(answer="Answer"), _student()
                )
                return "ok", result
            except main.HTTPException as exc:
                return "error", exc.status_code, exc.detail

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))

    assert sorted(result[0] for result in results) == ["error", "ok"]
    conflict = next(result for result in results if result[0] == "error")
    assert conflict[1] == 409
    assert conflict[2]["code"] == "submission_exists"


def test_foreign_key_rejects_topic_from_another_classroom():
    with database.session_scope():
        _add_users()
        first = main.create_classroom(
            {"name": "First", "subject": "DB", "section": "A", "semester": "Fall", "description": ""},
            _faculty(),
        )
        second = main.create_classroom(
            {"name": "Second", "subject": "DB", "section": "B", "semester": "Fall", "description": ""},
            _faculty(),
        )
        module = main.create_curriculum_module(first["id"], main.CurriculumModuleIn(title="Module"), _faculty())
        topic = main.create_curriculum_topic(
            first["id"], module["id"],
            main.CurriculumTopicIn(
                title="Topic",
                concepts=[main.CurriculumConceptIn(name="3NF", prerequisites=["BCNF"])],
            ),
            _faculty(),
        )
        concept_edge = database.current_session().scalar(
            select(ConceptPrerequisite).where(
                ConceptPrerequisite.topicId == topic["id"],
                ConceptPrerequisite.conceptName == "3NF",
                ConceptPrerequisite.prerequisiteName == "BCNF",
            )
        )
        assert concept_edge is not None

    with pytest.raises(IntegrityError):
        with database.session_scope():
            db.classroom_assessments.insert_one({
                "_id": "cross-class-assessment",
                "classroomId": second["id"],
                "title": "Invalid reference",
                "kind": "assignment",
                "topicId": topic["id"],
                "maxMarks": 10,
                "createdBy": "faculty-postgres",
            })


def test_importer_rerun_upserts_preserved_string_ids():
    report = {"invalid": [], "duplicate": [], "orphaned": [], "unsupportedFields": []}
    imported = defaultdict(int)
    batch = [({"_id": "legacy-google-subject", "name": "Old name", "role": "STUDENT"}, User)]

    import_batch("users", batch, imported, report)
    batch[0][0]["name"] = "Updated name"
    import_batch("users", batch, imported, report)

    with database.session_scope():
        record = db.users.find_one({"_id": "legacy-google-subject"})
        count = db.users.count_documents({"_id": "legacy-google-subject"})
    assert record["name"] == "Updated name"
    assert count == 1


def test_first_learning_session_can_precede_topic_aggregate_creation():
    with database.session_scope():
        _add_users()
        db.sessions.insert_one({
            "_id": "first-lesson-session",
            "userId": "student-postgres",
            "topicId": "first-topic",
            "topic": "First topic",
            "learningContent": {"quiz": []},
            "evaluation": {"completed": False},
        })
        db.topics.update_one(
            {"_id": "first-topic", "userId": "student-postgres"},
            {"$setOnInsert": {"name": "First topic", "progress": {}}, "$addToSet": {"sessionIds": "first-lesson-session"}},
            upsert=True,
        )

    with database.session_scope():
        association_count = database.current_session().scalar(
            select(func.count()).select_from(TopicSession).where(
                TopicSession.topicId == "first-topic",
                TopicSession.sessionId == "first-lesson-session",
                TopicSession.userId == "student-postgres",
            )
        )
    assert association_count == 1


def test_summary_projection_keeps_string_id_without_loading_lesson_content():
    with database.session_scope():
        _add_users()
        db.topics.insert_one({"_id": "topic-projection", "userId": "student-postgres", "name": "Projection"})
        db.sessions.insert_one({
            "_id": "lesson-projection",
            "userId": "student-postgres",
            "topicId": "topic-projection",
            "learningContent": {"explanation": {"overview": "Large body"}, "quiz": []},
            "input": {"content": "source"},
            "answers": {"q1": "A"},
            "evaluation": {"completed": True, "score": 100},
            "createdAt": main.now(),
        })

    with database.session_scope():
        summary = db.sessions.find_one(
            {"_id": "lesson-projection", "userId": "student-postgres"},
            {"evaluation": 1, "createdAt": 1},
        )

    assert summary["_id"] == "lesson-projection"
    assert summary["evaluation"]["score"] == 100
    assert "learningContent" not in summary
    assert "input" not in summary


def test_streamed_lesson_is_committed_before_success_event(monkeypatch):
    lesson = Lesson(
        topic="Persisted streaming lesson",
        explanation=Explanation(
            overview="Saved before the client receives the lesson.",
            sections=[Section(title="Persistence", content="Commit before final SSE event.")],
            keyTakeaways=["Write first"],
        ),
        flashcards=[Flashcard(id="card-1", question="When?", answer="Before success is sent.")],
        quiz=[QuizQuestion(
            id="question-1",
            question="Was it saved?",
            options=["Yes", "No"],
            correctAnswer="Yes",
            explanation="The database commit precedes the success event.",
        )],
    )
    monkeypatch.setattr(main, "generate_lesson", lambda *args, **kwargs: lesson)

    with database.session_scope():
        _add_users()
    response = main.learn_stream(main.LearnIn(content="Teach persistence briefly."), _student())

    async def consume():
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(consume())
    final_event = next(chunk for chunk in chunks if '"sessionId"' in chunk)
    payload = json.loads(final_event.removeprefix("data: ").strip())
    session_id = payload["sessionId"]

    with database.session_scope():
        saved = db.sessions.find_one({"_id": session_id, "userId": "student-postgres"})
    assert saved is not None
    assert saved["learningContent"]["topic"] == lesson.topic


def test_quiz_completion_uses_persisted_answer_key_and_enforces_owner():
    with database.session_scope():
        _add_users()
        db.topics.insert_one({
            "_id": "topic-graded",
            "userId": "student-postgres",
            "name": "Grading",
            "progress": {"score": 0, "level": "New", "sessionsCompleted": 0},
        })
        db.sessions.insert_one({
            "_id": "session-graded",
            "userId": "student-postgres",
            "topicId": "topic-graded",
            "topic": "Grading",
            "learningContent": {"quiz": [
                {"id": "q1", "options": ["right", "wrong"], "correctAnswer": "right", "conceptIds": []},
                {"id": "q2", "options": ["right", "wrong"], "correctAnswer": "wrong", "conceptIds": []},
            ]},
            "evaluation": {"completed": False},
            "input": {},
            "answers": {},
            "createdAt": main.now(),
        })

    with pytest.raises(main.HTTPException) as denied:
        with database.session_scope():
            main.session("session-graded", {"id": "faculty-postgres", "role": "FACULTY"})
    assert denied.value.status_code == 404

    with database.session_scope():
        result = main.complete(
            "session-graded",
            main.CompleteIn(correct=2, incorrect=0, total=2, answers={"q1": "right", "q2": "right"}),
            _student(),
        )

    assert result["evaluation"]["score"] == 50
    assert result["evaluation"]["correct"] == 1
    with database.session_scope():
        saved = db.sessions.find_one({"_id": "session-graded", "userId": "student-postgres"})
        topic = db.topics.find_one({"_id": "topic-graded", "userId": "student-postgres"})
        user = db.users.find_one({"_id": "student-postgres"})
    assert saved["answers"] == {"q1": "right", "q2": "right"}
    assert topic["progress"]["score"] == 50
    assert user["stats"]["sessionsCompleted"] == 1
    with database.session_scope():
        profile = main.profile(_student())
    assert profile["needsReview"][0]["id"] == "topic-graded"
    assert profile["recent"][0]["id"] == "session-graded"