import os
import sys
import types
import asyncio
import json
from pathlib import Path

import pytest
from fastapi import Request, Response

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/testdb")

import main  # noqa: E402
import llm  # noqa: E402
from models import Explanation, Flashcard, Lesson, QuizQuestion, Section  # noqa: E402


class InMemoryCollection:
    def __init__(self):
        self.docs = []

    @staticmethod
    def _matches(doc, query):
        for key, expected in (query or {}).items():
            if key in doc:
                actual = doc[key]
            else:
                actual = doc
                for part in key.split("."):
                    actual = actual.get(part) if isinstance(actual, dict) else None
            if isinstance(expected, dict):
                if "$ne" in expected and actual == expected["$ne"]:
                    return False
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$gt" in expected and (actual is None or actual <= expected["$gt"]):
                    return False
            elif actual != expected:
                return False
        return True

    def find_one(self, query=None, projection=None, sort=None):
        query = query or {}
        for doc in self.docs:
            if self._matches(doc, query):
                return doc
        return None

    def find(self, query=None, projection=None, sort=None):
        query = query or {}
        results = [doc for doc in self.docs if self._matches(doc, query)]
        if sort is not None:
            for field, direction in sort:
                results.sort(key=lambda d: d.get(field, 0), reverse=direction == -1)
        return results

    def insert_one(self, doc):
        self.docs.append(doc)
        return types.SimpleNamespace(inserted_id=doc.get("_id"))

    def update_one(self, query, update, upsert=False):
        overlapping_fields = set(update.get("$set", {})) & set(update.get("$setOnInsert", {}))
        if overlapping_fields:
            raise AssertionError(f"Conflicting MongoDB update paths: {overlapping_fields}")
        for doc in self.docs:
            if self._matches(doc, query):
                if "$set" in update:
                    doc.update(update["$set"])
                if "$setOnInsert" in update:
                    for key, value in update["$setOnInsert"].items():
                        doc.setdefault(key, value)
                return types.SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            merged = dict(query)
            if "$set" in update:
                merged.update(update["$set"])
            if "$setOnInsert" in update:
                merged.update(update["$setOnInsert"])
            self.docs.append(merged)
            return types.SimpleNamespace(matched_count=0, modified_count=1)
        return types.SimpleNamespace(matched_count=0, modified_count=0)

    def update_many(self, query, update):
        matched = 0
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                matched += 1
                if "$set" in update:
                    doc.update(update["$set"])
        return types.SimpleNamespace(matched_count=matched, modified_count=matched)

    def count_documents(self, query=None):
        query = query or {}
        return sum(1 for doc in self.docs if self._matches(doc, query))

    def delete_one(self, query):
        for idx, doc in enumerate(self.docs):
            if self._matches(doc, query):
                del self.docs[idx]
                return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)

    def delete_many(self, query):
        original_count = len(self.docs)
        self.docs[:] = [
            doc for doc in self.docs
            if not self._matches(doc, query)
        ]
        return types.SimpleNamespace(deleted_count=original_count - len(self.docs))


def reset_db():
    for timer in main._classroom_delete_timers.values():
        timer.cancel()
    main._classroom_delete_timers.clear()
    main.db = types.SimpleNamespace(
        users=InMemoryCollection(),
        sessions=InMemoryCollection(),
        topics=InMemoryCollection(),
        classrooms=InMemoryCollection(),
        classroom_modules=InMemoryCollection(),
        classroom_curriculum_topics=InMemoryCollection(),
        classroom_assessments=InMemoryCollection(),
        classroom_submissions=InMemoryCollection(),
        classroom_posts=InMemoryCollection(),
        classroom_replies=InMemoryCollection(),
        classroom_members=InMemoryCollection(),
        learning_events=InMemoryCollection(),
        learning_paths=InMemoryCollection(),
        adaptive_tasks=InMemoryCollection(),
        client=types.SimpleNamespace(admin=types.SimpleNamespace(command=lambda *args, **kwargs: {"ok": 1})),
    )
    main.db.users.insert_one({"_id": "faculty-1", "name": "Faculty User", "email": "faculty@example.com", "role": "FACULTY"})
    main.db.users.insert_one({"_id": "student-1", "name": "Student User", "email": "student@example.com", "role": "STUDENT"})
    main.db.users.insert_one({"_id": "student-2", "name": "Second Student", "email": "student2@example.com", "role": "STUDENT"})
    main.db.users.insert_one({"_id": "admin-1", "name": "Admin User", "email": "admin@example.com", "role": "ADMIN"})


def _user(user_id: str):
    return {
        "id": user_id,
        "name": main.db.users.find_one({"_id": user_id})["name"],
        "email": main.db.users.find_one({"_id": user_id})["email"],
        "role": main.db.users.find_one({"_id": user_id}).get("role", "STUDENT"),
    }


def _request_with_cookie(cookie: str | None = None, headers: list[tuple[bytes, bytes]] | None = None):
    request_headers = list(headers or [])
    if cookie:
        request_headers.append((b"cookie", f"curiosity_session={cookie}".encode()))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": request_headers})


def _published_topic_for(student):
    classroom = main.create_classroom(
        {"name": "DBMS", "subject": "Database systems", "section": "A", "semester": "Fall", "description": ""},
        _user("faculty-1"),
    )
    module = main.create_curriculum_module(
        classroom["id"], main.CurriculumModuleIn(title="Relational design"), _user("faculty-1")
    )
    topic = main.create_curriculum_topic(
        classroom["id"], module["id"],
        main.CurriculumTopicIn(title="Normalization", concepts=[main.CurriculumConceptIn(name="3NF")]),
        _user("faculty-1"),
    )
    main.publish_classroom_curriculum(classroom["id"], _user("faculty-1"))
    main.join_classroom({"joinCode": classroom["joinCode"]}, student)
    return classroom, module, topic


def _fake_revision_lesson(*args, **kwargs):
    return Lesson(
        topic="Targeted revision",
        explanation=Explanation(
            overview="A focused explanation.",
            sections=[Section(title="Core concept", content="Understand the dependency.")],
            keyTakeaways=["Use the key dependency."],
        ),
        flashcards=[Flashcard(id="revision-1", question="What is the key?", answer="A dependency.")],
        quiz=[QuizQuestion(id="r1", question="Which key?", options=["A", "B"], correctAnswer="A", explanation="It is A.")],
    )


def test_faculty_can_create_classroom_and_student_can_join():
    reset_db()
    faculty_user = _user("faculty-1")
    created = main.create_classroom(
        {
            "name": "DBMS",
            "subject": "Database Management Systems",
            "section": "A",
            "semester": "2026-01",
            "description": "Intro to SQL and design.",
        },
        faculty_user,
    )
    assert created["name"] == "DBMS"
    assert created["joinCode"]

    student_user = _user("student-1")
    joined = main.join_classroom({"joinCode": created["joinCode"]}, student_user)
    assert joined["memberCount"] >= 2

    visible = main.list_classrooms(student_user)
    assert any(item["name"] == "DBMS" for item in visible)


def test_curriculum_generation_is_owner_scoped_and_returns_ai_draft(monkeypatch):
    reset_db()
    owner = _user("faculty-1")
    main.db.classrooms.insert_one({"_id": "class-1", "ownerId": owner["id"]})
    monkeypatch.setattr(
        main,
        "generate_curriculum",
        lambda prompt, provider, model: {"modules": [{"title": prompt}]},
    )

    result = main.generate_classroom_curriculum_route(
        "class-1",
        main.CurriculumGenerateIn(prompt="A syllabus about operating systems"),
        owner,
    )

    assert result == {"modules": [{"title": "A syllabus about operating systems"}]}
    with pytest.raises(main.HTTPException) as denied:
        main.generate_classroom_curriculum_route(
            "class-1",
            main.CurriculumGenerateIn(prompt="A syllabus about operating systems"),
            _user("student-1"),
        )
    assert denied.value.status_code == 403


def test_applying_ai_curriculum_draft_batches_ordered_modules_and_topics():
    reset_db()
    owner = _user("faculty-1")
    classroom = main.create_classroom(
        {"name": "Operating Systems", "subject": "CS", "section": "A", "semester": "Fall", "description": ""},
        owner,
    )
    draft = main.CurriculumDraftApplyIn(modules=[
        main.CurriculumDraftModuleIn(
            title="Foundations",
            description="Core ideas",
            topics=[
                main.CurriculumTopicIn(title="Processes", learningObjectives=["Explain a process"]),
                main.CurriculumTopicIn(title="Threads"),
            ],
        ),
        main.CurriculumDraftModuleIn(
            title="Memory",
            topics=[main.CurriculumTopicIn(title="Virtual memory")],
        ),
    ])

    result = main.apply_classroom_curriculum_draft_route(classroom["id"], draft, owner)

    assert result["status"] == "draft"
    assert [module["title"] for module in result["modules"]] == ["Foundations", "Memory"]
    assert [topic["title"] for topic in result["modules"][0]["topics"]] == ["Processes", "Threads"]
    assert [topic["position"] for topic in result["modules"][0]["topics"]] == [0, 1]
    assert result["modules"][0]["topics"][0]["learningObjectives"] == ["Explain a process"]
    with pytest.raises(main.HTTPException) as denied:
        main.apply_classroom_curriculum_draft_route(classroom["id"], draft, _user("student-1"))
    assert denied.value.status_code == 403


def test_curriculum_prompt_requests_concise_module_detail_without_changing_schema(monkeypatch):
    generated = {
        "modules": [{
            "title": "Core Concepts",
            "description": "Introduces the foundations and their role in the course.",
            "topics": [{
                "title": "Processes",
                "description": "How programs execute and share resources.",
                "learningObjectives": ["Describe process states"],
                "prerequisites": [],
                "concepts": [{"name": "Process state", "description": "An execution condition.", "prerequisites": []}],
            }],
        }]
    }
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps(generated)))]
            )

    fake_client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm, "client", lambda _provider: fake_client)

    result = llm.generate_curriculum("Operating systems syllabus")

    assert result == generated
    system_prompt = captured["messages"][0]["content"]
    assert '"description":"..."' in system_prompt
    assert "1-2 sentences" in system_prompt
    assert "modest, syllabus-proportional set" in system_prompt
    assert "not over-detailed" in system_prompt


def test_curriculum_stays_draft_until_owner_publishes_and_initializes_student_path():
    reset_db()
    faculty = _user("faculty-1")
    student = _user("student-1")
    classroom = main.create_classroom(
        {"name": "Operating Systems", "subject": "OS", "section": "A", "semester": "Fall", "description": ""}, faculty
    )
    module = main.create_curriculum_module(classroom["id"], main.CurriculumModuleIn(title="Processes"), faculty)
    topic = main.create_curriculum_topic(classroom["id"], module["id"], main.CurriculumTopicIn(title="Process states"), faculty)
    main.join_classroom({"joinCode": classroom["joinCode"]}, student)
    assert main.get_classroom_curriculum(classroom["id"], student)["modules"] == []
    main.publish_classroom_curriculum(classroom["id"], faculty)
    visible = main.get_classroom_curriculum(classroom["id"], student)
    assert visible["status"] == "published"
    assert visible["modules"][0]["topics"][0]["id"] == topic["id"]
    path = main.db.learning_paths.find_one({"classroomId": classroom["id"], "userId": student["id"]})
    assert path["path"]["items"][0]["topicId"] == topic["id"]


def test_legacy_missing_curriculum_status_infers_published_state():
    reset_db()
    faculty = _user("faculty-1")
    student = _user("student-1")
    classroom_id = "legacy-classroom"
    main.db.classrooms.insert_one({
        "_id": classroom_id,
        "ownerId": faculty["id"],
        "joinCode": "OLD123",
        "curriculumVersion": 2,
        "members": [
            {"userId": faculty["id"], "role": "OWNER"},
            {"userId": student["id"], "role": "STUDENT"},
        ],
    })
    main.db.classroom_modules.insert_one({
        "_id": "legacy-module",
        "classroomId": classroom_id,
        "title": "Legacy module",
        "position": 0,
    })
    main.db.classroom_curriculum_topics.insert_one({
        "_id": "legacy-published-topic",
        "classroomId": classroom_id,
        "moduleId": "legacy-module",
        "title": "Published topic",
        "position": 0,
        "published": True,
    })

    result = main.get_classroom_curriculum(classroom_id, student)

    assert result["status"] == "published"
    assert result["version"] == 2
    assert [topic["id"] for topic in result["modules"][0]["topics"]] == ["legacy-published-topic"]
    assert "joinCode" not in result["classroom"]


def test_classroom_delete_can_be_undone_before_purge():
    reset_db()
    owner = _user("faculty-1")
    student = _user("student-1")
    classroom = main.create_classroom(
        {"name": "Networks", "subject": "CN", "section": "A", "semester": "Fall", "description": ""},
        owner,
    )
    main.join_classroom({"joinCode": classroom["joinCode"]}, student)
    main.db.classroom_modules.insert_one({"_id": "module-1", "classroomId": classroom["id"]})
    main.db.learning_paths.insert_one({"_id": "path-1", "classroomId": classroom["id"], "userId": student["id"]})

    with pytest.raises(main.HTTPException) as denied:
        main.delete_classroom(classroom["id"], student)
    assert denied.value.status_code == 403
    assert main.db.classrooms.find_one({"_id": classroom["id"]}) is not None

    result = main.delete_classroom(classroom["id"], owner)
    assert result["deleted"] is True
    assert result["undoToken"]
    assert classroom["id"] not in {item["id"] for item in main.list_classrooms(owner)}
    assert main.db.classroom_modules.find_one({"classroomId": classroom["id"]}) is not None

    restored = main.undo_delete_classroom(classroom["id"], result["undoToken"], owner)

    assert restored["id"] == classroom["id"]
    assert restored["name"] == "Networks"
    assert classroom["id"] in {item["id"] for item in main.list_classrooms(owner)}
    assert main.db.classroom_modules.find_one({"classroomId": classroom["id"]}) is not None
    assert main.db.learning_paths.find_one({"classroomId": classroom["id"]}) is not None


def test_classroom_delete_purges_related_data_after_undo_window():
    reset_db()
    owner = _user("faculty-1")
    classroom = main.create_classroom(
        {"name": "Networks", "subject": "CN", "section": "A", "semester": "Fall", "description": ""},
        owner,
    )
    main.db.classroom_modules.insert_one({"_id": "module-1", "classroomId": classroom["id"]})
    main.db.learning_paths.insert_one({"_id": "path-1", "classroomId": classroom["id"], "userId": "student-1"})

    result = main.delete_classroom(classroom["id"], owner)
    main.finalize_classroom_delete(classroom["id"], result["undoToken"])

    assert main.db.classrooms.find_one({"_id": classroom["id"]}) is None
    assert main.db.classroom_modules.find_one({"classroomId": classroom["id"]}) is None
    assert main.db.learning_paths.find_one({"classroomId": classroom["id"]}) is None


def test_classroom_update_is_owner_or_faculty_scoped():
    reset_db()
    owner = _user("faculty-1")
    classroom = main.create_classroom(
        {"name": "Networks", "subject": "CN", "section": "A", "semester": "Fall", "description": "Old"},
        owner,
    )
    changes = {"name": "Computer Networks", "subject": "Networking", "section": "B", "semester": "Spring", "description": "Updated course details"}

    updated = main.update_classroom(classroom["id"], changes, owner)

    assert updated["name"] == "Computer Networks"
    assert updated["subject"] == "Networking"
    assert updated["description"] == "Updated course details"
    with pytest.raises(main.HTTPException) as denied:
        main.update_classroom(classroom["id"], changes, _user("student-1"))
    assert denied.value.status_code == 403


def test_teacher_can_edit_published_curriculum_by_deleting_module_and_topic():
    reset_db()
    faculty = _user("faculty-1")
    classroom = main.create_classroom(
        {"name": "Algorithms", "subject": "CS", "section": "C", "semester": "Fall", "description": ""}, faculty
    )
    module = main.create_curriculum_module(classroom["id"], main.CurriculumModuleIn(title="Core theory"), faculty)
    topic = main.create_curriculum_topic(
        classroom["id"],
        module["id"],
        main.CurriculumTopicIn(title="Big-O notation", learningObjectives=["Define complexity"], concepts=[]),
        faculty,
    )
    main.publish_classroom_curriculum(classroom["id"], faculty)

    module_deleted = main.delete_curriculum_module(classroom["id"], module["id"], faculty)
    assert module_deleted["deleted"] is True
    assert main.get_classroom_curriculum(classroom["id"], faculty)["modules"] == []

    module = main.create_curriculum_module(classroom["id"], main.CurriculumModuleIn(title="Graphs"), faculty)
    topic = main.create_curriculum_topic(
        classroom["id"],
        module["id"],
        main.CurriculumTopicIn(title="Shortest path", learningObjectives=["Explain BFS"], concepts=[]),
        faculty,
    )
    topic_deleted = main.delete_curriculum_topic(classroom["id"], topic["id"], faculty)
    assert topic_deleted["deleted"] is True
    assert main.get_classroom_curriculum(classroom["id"], faculty)["modules"][0]["topics"] == []


def test_student_can_create_classroom_and_admin_can_manage_roles():
    reset_db()
    student_user = _user("student-1")
    created = main.create_classroom(
        {
            "name": "Student-Owned Course",
            "subject": "Security",
            "section": "B",
            "semester": "2026-01",
            "description": "Any user can start a course space.",
        },
        student_user,
    )
    assert created["ownerId"] == student_user["id"]
    assert created["members"][0]["name"] == student_user["name"]
    assert "email" not in created["members"][0]
    assert main.get_classroom(created["id"], student_user)["id"] == created["id"]
    module = main.create_curriculum_module(
        created["id"], main.CurriculumModuleIn(title="Owner-authored module"), student_user
    )
    assert module["title"] == "Owner-authored module"
    assessment = main.create_classroom_assessment(
        created["id"],
        main.ClassroomAssessmentIn(title="Practice", kind="practice", maxMarks=5, published=True),
        student_user,
    )
    assert assessment["createdBy"] == student_user["id"]
    assert main.db.users.find_one({"_id": student_user["id"]})["role"] == "STUDENT"


def test_google_auth_user_upsert_uses_non_conflicting_role_update(monkeypatch):
    reset_db()
    monkeypatch.setattr(
        main,
        "verify_google_credential",
        lambda _: {
            "sub": "new-google-user",
            "name": "New User",
            "email": "new@example.com",
            "picture": "https://example.com/photo.png",
            "iss": "https://accounts.google.com",
        },
    )

    result = main.google_auth(main.GoogleAuthIn(credential="x" * 20), _request_with_cookie(), Response())

    assert result["user"]["id"] == "new-google-user"
    assert result["user"]["role"] == "STUDENT"
    assert main.db.users.find_one({"_id": "new-google-user"})["role"] == "STUDENT"


def test_verified_bootstrap_email_becomes_first_admin_once(monkeypatch):
    reset_db()
    main.db.users.delete_one({"_id": "admin-1"})
    main.db.users.insert_one({"_id": "bootstrap-user", "name": "Platform Owner", "email": "owner@example.com", "role": "STUDENT"})
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setattr(
        main,
        "verify_google_credential",
        lambda _: {
            "sub": "bootstrap-user",
            "name": "Platform Owner",
            "email": "Owner@Example.com",
            "email_verified": True,
            "iss": "https://accounts.google.com",
        },
    )

    result = main.google_auth(main.GoogleAuthIn(credential="x" * 20), _request_with_cookie(), Response())

    assert result["user"]["role"] == "ADMIN"
    assert main.db.users.find_one({"_id": "bootstrap-user"})["role"] == "ADMIN"


def test_bootstrap_email_cannot_create_second_admin(monkeypatch):
    reset_db()
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "another@example.com")
    monkeypatch.setattr(
        main,
        "verify_google_credential",
        lambda _: {
            "sub": "another-user",
            "name": "Another User",
            "email": "another@example.com",
            "email_verified": True,
            "iss": "https://accounts.google.com",
        },
    )

    result = main.google_auth(main.GoogleAuthIn(credential="x" * 20), _request_with_cookie(), Response())

    assert result["user"]["role"] == "STUDENT"


def test_invalid_role_is_rejected_instead_of_becoming_student():
    reset_db()

    with pytest.raises(main.HTTPException) as invalid:
        main.update_user_role("student-1", {"role": "TEACHER"}, _user("admin-1"))

    assert invalid.value.status_code == 400
    assert main.db.users.find_one({"_id": "student-1"})["role"] == "STUDENT"


def test_platform_user_listing_is_admin_only_and_excludes_guests():
    reset_db()
    main.db.users.insert_one({"_id": "guest_123", "name": "Guest", "role": "STUDENT"})

    with pytest.raises(main.HTTPException) as denied:
        main.list_platform_users(_user("student-1"))
    assert denied.value.status_code == 403

    users = main.list_platform_users(_user("admin-1"))
    assert {item["id"] for item in users} == {"faculty-1", "student-1", "student-2", "admin-1"}


def test_auth_status_returns_unauthenticated_without_http_error():
    reset_db()

    result = main.auth_session_status(None)

    assert result == {"authenticated": False, "user": None}


def test_guest_session_is_server_issued_cookie_and_persists_on_refresh():
    reset_db()
    response = Response()

    result = main.create_guest_session(_request_with_cookie(), response)

    cookie_header = response.headers["set-cookie"]
    session_id = cookie_header.split("curiosity_session=", 1)[1].split(";", 1)[0]
    assert "httponly" in cookie_header.lower()
    assert result["user"]["id"].startswith("guest_")
    assert result["user"]["role"] == "STUDENT"
    assert result["user"]["isGuest"] is True
    assert session_id != result["user"]["id"]
    assert session_id not in str(result)

    refreshed = main.auth_session_status(session_id)
    assert refreshed["authenticated"] is True
    assert refreshed["user"]["id"] == result["user"]["id"]
    assert refreshed["user"]["isGuest"] is True
    assert main.current_user(_request_with_cookie(session_id))["role"] == "STUDENT"


def test_guest_header_is_not_accepted_as_authentication():
    reset_db()
    main.db.users.insert_one({"_id": "guest_legacy", "name": "Guest", "role": "STUDENT"})

    with pytest.raises(main.HTTPException) as denied:
        main.current_user(_request_with_cookie(headers=[(b"x-guest-id", b"guest_legacy")]))

    assert denied.value.status_code == 401


def test_logout_revokes_cookie_session_and_clears_cookie():
    reset_db()
    session = main.create_session("student-1")
    response = Response()

    result = main.logout(_request_with_cookie(session["id"]), response)

    assert result == {"status": "ok"}
    assert main.db.sessions.find_one({"_id": session["id"]}) is None
    assert 'curiosity_session=""' in response.headers["set-cookie"]
    assert "max-age=0" in response.headers["set-cookie"].lower()


def test_google_login_rotates_guest_session_without_merging_guest_data(monkeypatch):
    reset_db()
    guest_response = Response()
    guest = main.create_guest_session(_request_with_cookie(), guest_response)
    old_session_id = guest_response.headers["set-cookie"].split("curiosity_session=", 1)[1].split(";", 1)[0]
    main.db.topics.insert_one({"_id": "guest-topic", "userId": guest["user"]["id"], "name": "Guest topic"})
    monkeypatch.setattr(main, "verify_google_credential", lambda _: {
        "sub": "google-after-guest", "name": "Google User", "email": "google@example.com",
        "iss": "https://accounts.google.com",
    })
    google_response = Response()

    result = main.google_auth(
        main.GoogleAuthIn(credential="x" * 20),
        _request_with_cookie(old_session_id),
        google_response,
    )

    new_session_id = google_response.headers["set-cookie"].split("curiosity_session=", 1)[1].split(";", 1)[0]
    assert new_session_id != old_session_id
    assert main.db.sessions.find_one({"_id": old_session_id}) is None
    assert main.db.sessions.find_one({"_id": new_session_id})["user_id"] == "google-after-guest"
    assert main.db.topics.find_one({"_id": "guest-topic"})["userId"] == guest["user"]["id"]
    assert result["user"]["id"] == "google-after-guest"
    assert new_session_id not in str(result)


def test_csrf_validation_and_origin_allowlist(monkeypatch):
    reset_db()
    session = main.create_session("student-1", csrf_token="known-csrf")

    assert main.is_valid_csrf_token(session["id"], "known-csrf") is True
    assert main.is_valid_csrf_token(session["id"], "wrong-token") is False
    assert main._origin_allowed("http://localhost:5174") is True
    assert main._origin_allowed("https://malicious.example") is False

    monkeypatch.setattr(main, "FRONTEND_ORIGIN_REGEX", r"https://[a-z0-9-]+\.vercel\.app")
    assert main._origin_allowed("https://curiosity-preview.vercel.app") is True
    assert main._origin_allowed("https://evil.example") is False


def test_session_cookie_is_cross_site_compatible_when_secure(monkeypatch):
    monkeypatch.setattr(main, "SESSION_COOKIE_SECURE", True)
    monkeypatch.setattr(main, "SESSION_COOKIE_SAMESITE", "none")
    monkeypatch.setattr(main, "SESSION_COOKIE_DOMAIN", None)

    settings = main.session_cookie_settings()

    assert settings["secure"] is True
    assert settings["samesite"] == "none"


def test_naive_mongodb_session_expiry_is_treated_as_utc():
    reset_db()
    expired_at = main.now().replace(tzinfo=None)
    main.db.sessions.insert_one(
        {"_id": "legacy-session", "user_id": "student-1", "expires_at": expired_at}
    )

    assert main.get_session_user_id("legacy-session") is None
    assert main.db.sessions.find_one({"_id": "legacy-session"}) is None


def test_curriculum_is_classroom_scoped_and_student_can_read():
    reset_db()
    faculty = _user("faculty-1")
    first_class = main.create_classroom(
        {"name": "DBMS A", "subject": "DBMS", "section": "A", "semester": "Fall", "description": ""},
        faculty,
    )
    second_class = main.create_classroom(
        {"name": "DBMS B", "subject": "DBMS", "section": "B", "semester": "Fall", "description": ""},
        faculty,
    )
    module = main.create_curriculum_module(
        first_class["id"],
        main.CurriculumModuleIn(title="Relational Design", position=0),
        faculty,
    )
    topic = main.create_curriculum_topic(
        first_class["id"],
        module["id"],
        main.CurriculumTopicIn(
            title="Normalization",
            learningObjectives=["Explain 3NF"],
            concepts=[main.CurriculumConceptIn(name="3NF", description="Third normal form")],
            materials=[main.CurriculumMaterialIn(kind="note", title="Lecture notes", content="Lossless decomposition")],
        ),
        faculty,
    )

    main.publish_classroom_curriculum(first_class["id"], faculty)
    student = _user("student-1")
    main.join_classroom({"joinCode": first_class["joinCode"]}, student)
    first_curriculum = main.get_classroom_curriculum(first_class["id"], student)
    second_curriculum = main.get_classroom_curriculum(second_class["id"], faculty)

    assert first_curriculum["modules"][0]["topics"][0]["id"] == topic["id"]
    assert second_curriculum["modules"] == []


def test_non_owner_cannot_edit_curriculum_and_cross_class_module_is_rejected():
    reset_db()
    faculty = _user("faculty-1")
    classroom = main.create_classroom(
        {"name": "Networks", "subject": "CN", "section": "A", "semester": "Fall", "description": ""},
        faculty,
    )
    outsider = {"id": "other-faculty", "role": "FACULTY"}
    with pytest.raises(main.HTTPException) as denied:
        main.create_curriculum_module(
            classroom["id"], main.CurriculumModuleIn(title="Unauthorized"), outsider
        )
    assert denied.value.status_code == 403

    with pytest.raises(main.HTTPException) as missing:
        main.create_curriculum_topic(
            classroom["id"],
            "module-from-another-class",
            main.CurriculumTopicIn(title="Should not attach"),
            faculty,
        )
    assert missing.value.status_code == 404


def test_link_material_rejects_unsafe_schemes():
    with pytest.raises(ValueError):
        main.CurriculumMaterialIn(kind="link", title="Unsafe", url="javascript:alert(1)")


def test_classroom_topic_learning_reuses_curiosity_stream_and_persists_context(monkeypatch):
    reset_db()
    faculty = _user("faculty-1")
    classroom = main.create_classroom(
        {"name": "DBMS", "subject": "Database systems", "section": "A", "semester": "Fall", "description": ""},
        faculty,
    )
    module = main.create_curriculum_module(
        classroom["id"], main.CurriculumModuleIn(title="Relational theory"), faculty
    )
    topic = main.create_curriculum_topic(
        classroom["id"],
        module["id"],
        main.CurriculumTopicIn(
            title="Normalization",
            learningObjectives=["Explain functional dependencies"],
            concepts=[main.CurriculumConceptIn(name="3NF")],
            materials=[main.CurriculumMaterialIn(kind="note", title="Class notes", content="Avoid update anomalies")],
        ),
        faculty,
    )
    main.publish_classroom_curriculum(classroom["id"], faculty)
    student = _user("student-1")
    main.join_classroom({"joinCode": classroom["joinCode"]}, student)
    generated_prompts = []
    lesson = Lesson(
        topic="Normalization",
        explanation=Explanation(
            overview="Normalization organizes relational data.",
            sections=[Section(title="3NF", content="A relation is in third normal form.")],
            keyTakeaways=["Reduce anomalies"],
        ),
        flashcards=[Flashcard(id="f1", question="What is 3NF?", answer="A normal form")],
        quiz=[QuizQuestion(id="q1", question="Why normalize?", options=["Reduce anomalies", "Add redundancy"], correctAnswer="Reduce anomalies", explanation="It avoids update anomalies.")],
    )

    def fake_generate(prompt, *_args):
        generated_prompts.append(prompt)
        return lesson

    monkeypatch.setattr(main, "generate_lesson", fake_generate)
    response = main.learn_stream(
        main.LearnIn(
            content="Explain it simply",
            classroomId=classroom["id"],
            curriculumTopicId=topic["id"],
        ),
        student,
    )

    async def consume():
        return [chunk async for chunk in response.body_iterator]

    asyncio.run(consume())
    saved = main.db.sessions.find_one({"classroomId": classroom["id"]})

    assert "Explain functional dependencies" in generated_prompts[0]
    assert "Avoid update anomalies" in generated_prompts[0]
    assert "adaptive learning agent" in generated_prompts[0]
    assert "selected official curriculum topic" in generated_prompts[0]
    assert "Start lesson" in generated_prompts[0]
    assert saved["curriculumTopicId"] == topic["id"]
    assert saved["curriculumModuleId"] == module["id"]
    assert saved["concepts"] == ["3NF"]
    assert saved["classroomSearch"] == "Explain it simply"


def test_classroom_topic_history_only_lists_current_users_saved_lessons():
    reset_db()
    student = _user("student-1")
    other_student = _user("student-2")
    classroom, module, topic = _published_topic_for(student)
    other_topic = main.create_curriculum_topic(
        classroom["id"], module["id"],
        main.CurriculumTopicIn(title="Keys"),
        _user("faculty-1"),
    )
    for session_record in [
        {"_id": "lesson-old", "userId": student["id"], "classroomId": classroom["id"], "curriculumTopicId": topic["id"], "topic": "Normalization", "classroomSearch": "Explain normalization simply", "createdAt": "2026-10-20T10:00:00Z", "learningContent": {"quiz": []}},
        {"_id": "lesson-new", "userId": student["id"], "classroomId": classroom["id"], "curriculumTopicId": topic["id"], "topic": "Normalization follow-up", "createdAt": "2026-10-21T10:00:00Z", "learningContent": {"quiz": []}},
        {"_id": "other-user", "userId": other_student["id"], "classroomId": classroom["id"], "curriculumTopicId": topic["id"], "topic": "Private lesson", "createdAt": "2026-10-22T10:00:00Z", "learningContent": {"quiz": []}},
        {"_id": "other-topic", "userId": student["id"], "classroomId": classroom["id"], "curriculumTopicId": other_topic["id"], "topic": "Keys", "createdAt": "2026-10-23T10:00:00Z", "learningContent": {"quiz": []}},
    ]:
        main.db.sessions.insert_one(session_record)

    history = main.classroom_topic_sessions(classroom["id"], topic["id"], student)

    assert [item["id"] for item in history] == ["lesson-new", "lesson-old"]
    assert "learningContent" not in history[0]
    assert history[1]["search"] == "Explain normalization simply"


def test_completed_classroom_quiz_records_learning_evidence(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    monkeypatch.setattr(main, "generate_lesson", _fake_revision_lesson)
    main.db.sessions.insert_one(
        {
            "_id": "session-classroom-quiz",
            "userId": student["id"],
            "topicId": "topic-personal",
            "classroomId": classroom["id"],
            "curriculumTopicId": topic["id"],
            "curriculumModuleId": module["id"],
            "learningContent": {"quiz": [
                {"id": f"q{i}", "question": "Question", "options": ["A", "B"], "correctAnswer": "A", "conceptIds": ["3NF"]}
                for i in range(5)
            ]},
            "evaluation": {"completed": False},
        }
    )

    result = main.complete(
        "session-classroom-quiz",
        main.CompleteIn(correct=5, incorrect=0, total=5, answers={"q0": "A", "q1": "A", "q2": "A", "q3": "A", "q4": "B"}),
        student,
    )

    event = main.db.learning_events.find_one({"_id": "learning_event_session_session-classroom-quiz"})
    assert result["evaluation"]["score"] == 80
    assert event["classroomId"] == classroom["id"]
    assert event["topicId"] == topic["id"]
    assert event["activityType"] == "curiosity_quiz"
    assert event["masteryScore"] == 80


def test_classroom_quiz_score_is_derived_from_saved_answer_key(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    monkeypatch.setattr(main, "generate_lesson", _fake_revision_lesson)
    main.db.sessions.insert_one(
        {
            "_id": "session-server-graded",
            "userId": student["id"],
            "topicId": "topic-personal",
            "classroomId": classroom["id"],
            "curriculumTopicId": topic["id"],
            "curriculumModuleId": module["id"],
            "learningContent": {
                "quiz": [
                    {"id": "q1", "correctAnswer": "A", "options": ["A", "B"], "conceptIds": ["3NF"]},
                    {"id": "q2", "correctAnswer": "B", "options": ["A", "B"], "conceptIds": ["3NF"]},
                ]
            },
            "evaluation": {"completed": False},
        }
    )

    result = main.complete(
        "session-server-graded",
        main.CompleteIn(
            correct=2,
            incorrect=0,
            total=2,
            answers={"q1": "A", "q2": "A"},
        ),
        student,
    )

    event = main.db.learning_events.find_one(
        {"_id": "learning_event_session_session-server-graded"}
    )
    assert result["evaluation"]["score"] == 50
    assert result["evaluation"]["correct"] == 1
    assert event["questionResults"] == [
        {"questionId": "q1", "concepts": ["3NF"], "correct": True, "unanswered": False},
        {"questionId": "q2", "concepts": ["3NF"], "correct": False, "unanswered": False},
    ]
    task = main.db.adaptive_tasks.find_one({"userId": student["id"], "topicId": topic["id"]})
    assert task["conceptIds"] == ["3NF"]
    assert task["mappingStatus"] == "mapped"
    assert task["status"] == "ready"


def _adaptive_task(classroom, module, topic, student, *, status="revision_complete"):
    task_id = main._revision_task_id(classroom["id"], student["id"], topic["id"], ["3NF"])
    task = {
        "_id": task_id,
        "id": task_id,
        "classroomId": classroom["id"],
        "userId": student["id"],
        "moduleId": module["id"],
        "topicId": topic["id"],
        "conceptIds": ["3NF"],
        "weakQuestionIds": ["old-q"],
        "weakQuestionTexts": ["Explain 3NF"],
        "mappingStatus": "mapped",
        "status": status,
        "generationStatus": "ready",
        "revisionContent": _fake_revision_lesson().model_dump(),
        "provider": "groq",
        "model": "qwen/qwen3.8-27b",
    }
    main.db.adaptive_tasks.insert_one(task)
    return task


def _fresh_retest_questions(*args, **kwargs):
    return [
        QuizQuestion(id=f"fresh-{index}", question=f"New question {index}", options=["A", "B"], correctAnswer="A", explanation="A is correct.", conceptIds=["3NF"])
        for index in range(1, 4)
    ]


def test_passing_retest_requires_strict_score_and_mapped_coverage(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    task = _adaptive_task(classroom, module, topic, student)
    monkeypatch.setattr(main, "generate_retest_quiz", _fresh_retest_questions)
    retest = main.create_adaptive_retest(classroom["id"], task["id"], student)
    session = main.db.sessions.find_one({"_id": retest["sessionId"]})
    assert len(session["learningContent"]["quiz"]) == 3
    result = main.complete(
        retest["sessionId"],
        main.CompleteIn(answers={question["id"]: "A" for question in session["learningContent"]["quiz"]}),
        student,
    )

    saved_task = main.db.adaptive_tasks.find_one({"_id": task["id"]})
    assert result["evaluation"]["score"] == 100
    assert saved_task["status"] == "mastered"
    assert saved_task["lastRetestScore"] == 100
    progress = main.classroom_progress(classroom["id"], student)
    assert progress["revisionTasks"] == []
    assert progress["revisionHistory"][0]["id"] == task["id"]
    assert progress["revisionHistory"][0]["status"] == "mastered"
    assert progress["revisionHistory"][0]["revisionContent"]
    assert progress["learningPath"]["items"][0]["status"] == "completed"


def test_successful_regular_assessment_resolves_matching_active_weakness(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    task = _adaptive_task(classroom, module, topic, student)
    session_id = "regular-success-after-weakness"
    main.db.sessions.insert_one({
        "_id": session_id, "userId": student["id"], "topicId": "personal-topic",
        "classroomId": classroom["id"], "curriculumTopicId": topic["id"], "curriculumModuleId": module["id"],
        "learningContent": {"quiz": [
            {"id": "q1", "options": ["A", "B"], "correctAnswer": "A", "conceptIds": ["3NF"]},
            {"id": "q2", "options": ["A", "B"], "correctAnswer": "B", "conceptIds": ["3NF"]},
        ]}, "evaluation": {"completed": False},
    })

    main.complete(session_id, main.CompleteIn(answers={"q1": "A", "q2": "B"}), student)

    assert main.db.adaptive_tasks.find_one({"_id": task["id"]})["status"] == "mastered"


def test_later_failed_assessment_reopens_previously_mastered_weakness(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    task = _adaptive_task(classroom, module, topic, student, status="mastered")
    monkeypatch.setattr(main, "generate_lesson", _fake_revision_lesson)
    session_id = "regression-after-mastery"
    main.db.sessions.insert_one({
        "_id": session_id, "userId": student["id"], "topicId": "personal-topic",
        "classroomId": classroom["id"], "curriculumTopicId": topic["id"], "curriculumModuleId": module["id"],
        "learningContent": {"quiz": [
            {"id": "q1", "options": ["A", "B"], "correctAnswer": "A", "conceptIds": ["3NF"]},
            {"id": "q2", "options": ["A", "B"], "correctAnswer": "B", "conceptIds": ["3NF"]},
        ]}, "evaluation": {"completed": False},
    })

    main.complete(session_id, main.CompleteIn(answers={"q1": "B", "q2": "B"}), student)

    reopened = main.db.adaptive_tasks.find_one({"_id": task["id"]})
    assert reopened["status"] == "ready"
    assert len(reopened["attemptHistory"]) == 1


def test_repeated_retest_request_returns_same_uncompleted_attempt(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    task = _adaptive_task(classroom, module, topic, student)
    monkeypatch.setattr(main, "generate_retest_quiz", _fresh_retest_questions)

    first = main.create_adaptive_retest(classroom["id"], task["id"], student)
    second = main.create_adaptive_retest(classroom["id"], task["id"], student)

    assert first["sessionId"] == second["sessionId"]
    assert second["idempotent"] is True
    assert len(main.db.sessions.find({"adaptiveTaskId": task["id"]})) == 1


def test_concurrent_retest_generation_is_rejected_without_second_ai_call(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    task = _adaptive_task(classroom, module, topic, student)
    main.db.adaptive_tasks.update_one(
        {"_id": task["id"]},
        {"$set": {"status": "generating_retest", "retestGenerationStartedAt": main.now()}},
    )
    calls = {"count": 0}
    monkeypatch.setattr(main, "generate_retest_quiz", lambda *args, **kwargs: calls.__setitem__("count", calls["count"] + 1))

    with pytest.raises(main.HTTPException) as preparing:
        main.create_adaptive_retest(classroom["id"], task["id"], student)

    assert preparing.value.status_code == 409
    assert calls["count"] == 0


def test_targeted_retest_requires_persisted_revision_completion(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    task = _adaptive_task(classroom, module, topic, student, status="ready")
    monkeypatch.setattr(main, "generate_retest_quiz", _fresh_retest_questions)

    with pytest.raises(main.HTTPException) as blocked:
        main.create_adaptive_retest(classroom["id"], task["id"], student)
    assert blocked.value.status_code == 409
    completed = main.complete_adaptive_revision(classroom["id"], task["id"], student)
    assert completed["status"] == "revision_complete"
    attempt = main.create_adaptive_retest(classroom["id"], task["id"], student)
    assert attempt["sessionId"]


def test_failed_retest_keeps_task_active_and_regenerates_revision(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    task = _adaptive_task(classroom, module, topic, student)
    monkeypatch.setattr(main, "generate_retest_quiz", _fresh_retest_questions)
    monkeypatch.setattr(main, "generate_lesson", _fake_revision_lesson)
    retest = main.create_adaptive_retest(classroom["id"], task["id"], student)
    session = main.db.sessions.find_one({"_id": retest["sessionId"]})
    main.complete(
        retest["sessionId"],
        main.CompleteIn(answers={question["id"]: "B" for question in session["learningContent"]["quiz"]}),
        student,
    )

    saved_task = main.db.adaptive_tasks.find_one({"_id": task["id"]})
    assert saved_task["status"] == "ready"
    assert saved_task["lastRetestScore"] == 0
    assert saved_task["revisionContent"]["topic"] == "Targeted revision"


def test_assessment_and_revision_task_are_idempotent(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    monkeypatch.setattr(main, "generate_lesson", _fake_revision_lesson)
    session_id = "idempotent-quiz"
    main.db.sessions.insert_one({
        "_id": session_id, "userId": student["id"], "topicId": "personal-topic",
        "classroomId": classroom["id"], "curriculumTopicId": topic["id"], "curriculumModuleId": module["id"],
        "learningContent": {"quiz": [
            {"id": "q1", "options": ["A", "B"], "correctAnswer": "A", "conceptIds": ["3NF"]},
            {"id": "q2", "options": ["A", "B"], "correctAnswer": "B", "conceptIds": ["3NF"]},
        ]}, "evaluation": {"completed": False},
    })
    submission = main.CompleteIn(answers={"q1": "B", "q2": "B"})
    first = main.complete(session_id, submission, student)
    second = main.complete(session_id, submission, student)

    assert first["evaluation"]["score"] == 50
    assert second["idempotent"] is True
    assert len(main.db.learning_events.find({"sourceSessionId": session_id})) == 1
    assert len(main.db.adaptive_tasks.find({"userId": student["id"], "topicId": topic["id"]})) == 1


def test_duplicate_completion_resumes_pending_orchestration(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    monkeypatch.setattr(main, "generate_lesson", _fake_revision_lesson)
    session_id = "resume-orchestration"
    main.db.sessions.insert_one({
        "_id": session_id, "userId": student["id"], "topicId": "personal-topic",
        "classroomId": classroom["id"], "curriculumTopicId": topic["id"], "curriculumModuleId": module["id"],
        "learningContent": {"quiz": [
            {"id": "q1", "options": ["A", "B"], "correctAnswer": "A", "conceptIds": ["3NF"]},
            {"id": "q2", "options": ["A", "B"], "correctAnswer": "B", "conceptIds": ["3NF"]},
        ]}, "evaluation": {"completed": False},
    })
    original = main._orchestrate_classroom_assessment
    calls = {"count": 0}

    def fail_once(session, event, acting_user):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated interruption")
        return original(session, event, acting_user)

    monkeypatch.setattr(main, "_orchestrate_classroom_assessment", fail_once)
    payload = main.CompleteIn(answers={"q1": "B", "q2": "B"})
    with pytest.raises(RuntimeError):
        main.complete(session_id, payload, student)
    assert main.db.sessions.find_one({"_id": session_id})["orchestrationStatus"] == "pending"

    result = main.complete(session_id, payload, student)

    assert result["evaluation"]["score"] == 50
    assert main.db.sessions.find_one({"_id": session_id})["orchestrationStatus"] == "ready"
    assert main.db.learning_events.find_one({"sourceSessionId": session_id}) is not None
    assert main.db.adaptive_tasks.find_one({"userId": student["id"], "topicId": topic["id"]}) is not None


def test_revision_generation_claim_suppresses_duplicate_provider_call(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    task = _adaptive_task(classroom, module, topic, student, status="pending")
    task["generationStatus"] = "generating"
    task["generationToken"] = "active-claim"
    task["generationStartedAt"] = main.now()
    calls = {"count": 0}
    monkeypatch.setattr(main, "generate_lesson", lambda *args, **kwargs: calls.__setitem__("count", calls["count"] + 1))

    result = main.generate_adaptive_revision(classroom["id"], task["id"], student)

    assert result["generationStatus"] == "generating"
    assert calls["count"] == 0


def test_failed_revision_generation_preserves_assessment_evidence(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    monkeypatch.setattr(main, "generate_lesson", lambda *args, **kwargs: (_ for _ in ()).throw(main.LLMError("llm_failed", "offline")))
    session_id = "provider-failure-quiz"
    main.db.sessions.insert_one({
        "_id": session_id, "userId": student["id"], "topicId": "personal-topic",
        "classroomId": classroom["id"], "curriculumTopicId": topic["id"], "curriculumModuleId": module["id"],
        "learningContent": {"quiz": [
            {"id": "q1", "options": ["A", "B"], "correctAnswer": "A", "conceptIds": ["3NF"]},
            {"id": "q2", "options": ["A", "B"], "correctAnswer": "B", "conceptIds": ["3NF"]},
        ]}, "evaluation": {"completed": False},
    })

    result = main.complete(session_id, main.CompleteIn(answers={"q1": "B", "q2": "B"}), student)

    event = main.db.learning_events.find_one({"sourceSessionId": session_id})
    task = main.db.adaptive_tasks.find_one({"userId": student["id"], "topicId": topic["id"]})
    assert result["evaluation"]["score"] == 50
    assert event["questionResults"][0]["correct"] is False
    assert task["status"] == "failed"
    assert task["generationError"] == "llm_failed"


def test_unmapped_question_creates_topic_fallback_not_concept_evidence(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    monkeypatch.setattr(main, "generate_lesson", _fake_revision_lesson)
    session_id = "unmapped-quiz"
    main.db.sessions.insert_one({
        "_id": session_id, "userId": student["id"], "topicId": "personal-topic",
        "classroomId": classroom["id"], "curriculumTopicId": topic["id"], "curriculumModuleId": module["id"],
        "learningContent": {"quiz": [
            {"id": "q1", "options": ["A", "B"], "correctAnswer": "A", "conceptIds": ["Invented concept"]},
            {"id": "q2", "options": ["A", "B"], "correctAnswer": "B", "conceptIds": ["Invented concept"]},
        ]}, "evaluation": {"completed": False},
    })
    main.complete(session_id, main.CompleteIn(answers={"q1": "B", "q2": "B"}), student)

    event = main.db.learning_events.find_one({"sourceSessionId": session_id})
    task = main.db.adaptive_tasks.find_one({"userId": student["id"], "topicId": topic["id"]})
    assert event["concepts"] == []
    assert event["mappingStatus"] == "insufficient"
    assert task["conceptIds"] == []
    assert task["mappingStatus"] == "insufficient"


def test_one_students_events_do_not_change_another_students_path():
    reset_db()
    student = _user("student-1")
    other = _user("student-2")
    classroom, module, topic = _published_topic_for(student)
    main.join_classroom({"joinCode": classroom["joinCode"]}, other)
    main.db.learning_events.insert_one({
        "_id": "other-student-evidence", "userId": other["id"], "classroomId": classroom["id"],
        "moduleId": module["id"], "topicId": topic["id"], "activityType": "quiz",
        "evaluationStatus": "complete", "masteryScore": 100, "coverage": True,
    })

    progress = main.classroom_progress(classroom["id"], student)

    assert progress["learningPath"]["items"][0]["status"] == "available"
    assert progress["learningPath"]["items"][0]["mastery"]["score"] is None


def test_faculty_progress_endpoint_payload_contains_authoritative_revision_state(monkeypatch):
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    monkeypatch.setattr(main, "generate_lesson", _fake_revision_lesson)
    session_id = "progress-contract-quiz"
    main.db.sessions.insert_one({
        "_id": session_id, "userId": student["id"], "topicId": "personal-topic",
        "classroomId": classroom["id"], "curriculumTopicId": topic["id"], "curriculumModuleId": module["id"],
        "learningContent": {"quiz": [
            {"id": "q1", "options": ["A", "B"], "correctAnswer": "A", "conceptIds": ["3NF"]},
            {"id": "q2", "options": ["A", "B"], "correctAnswer": "B", "conceptIds": ["3NF"]},
        ]}, "evaluation": {"completed": False},
    })
    main.complete(session_id, main.CompleteIn(answers={"q1": "B", "q2": "B"}), student)

    progress = main.classroom_progress(classroom["id"], student)

    assert progress["revisionTasks"][0]["status"] == "ready"
    assert progress["revisionTasks"][0]["revisionContent"]["topic"] == "Targeted revision"
    assert progress["revisionTasks"][0]["revisionContent"]["flashcards"][0]["question"] == "What is the key?"
    assert progress["revisionTasks"][0]["id"] == progress["revisionTasks"][0]["_id"]
    assert progress["learningPath"]["items"][0]["status"] == "revision_needed"


def test_revision_materials_remain_visible_after_new_progress_read():
    reset_db()
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    task = _adaptive_task(classroom, module, topic, student)
    first = main.classroom_progress(classroom["id"], student)
    second = main.classroom_progress(classroom["id"], student)

    assert first["revisionTasks"][0]["id"] == task["id"]
    assert second["revisionTasks"][0]["revisionContent"]["topic"] == "Targeted revision"
    assert second["revisionTasks"][0]["revisionContent"]["flashcards"][0]["answer"] == "A dependency."


def test_classwork_submission_privacy_and_faculty_grade_release():
    reset_db()
    faculty = _user("faculty-1")
    classroom = main.create_classroom(
        {"name": "DBMS", "subject": "Database systems", "section": "A", "semester": "Fall", "description": ""},
        faculty,
    )
    assessment = main.create_classroom_assessment(
        classroom["id"],
        main.ClassroomAssessmentIn(
            title="Normalization exercise",
            kind="assignment",
            maxMarks=20,
            rubric="Explain the normal forms",
            published=True,
        ),
        faculty,
    )
    first_student = _user("student-1")
    second_student = _user("student-2")
    main.join_classroom({"joinCode": classroom["joinCode"]}, first_student)
    main.join_classroom({"joinCode": classroom["joinCode"]}, second_student)

    submission = main.submit_classroom_assessment(
        classroom["id"], assessment["id"], main.ClassroomSubmissionIn(answer="My answer"), first_student
    )
    faculty_submissions = main.list_classroom_submissions(classroom["id"], assessment["id"], faculty)
    assert faculty_submissions[0]["studentName"] == "Student User"
    with pytest.raises(main.HTTPException) as duplicate:
        main.submit_classroom_assessment(
            classroom["id"], assessment["id"], main.ClassroomSubmissionIn(answer="Again"), first_student
        )
    assert duplicate.value.status_code == 409
    assert main.list_classroom_submissions(classroom["id"], assessment["id"], second_student) == []

    main.grade_classroom_submission(
        classroom["id"],
        assessment["id"],
        submission["id"],
        main.ClassroomGradeIn(score=16, feedback="Good explanation", release=False),
        faculty,
    )
    private_result = main.list_classroom_submissions(classroom["id"], assessment["id"], first_student)[0]
    assert "score" not in private_result
    assert "feedback" not in private_result

    main.grade_classroom_submission(
        classroom["id"],
        assessment["id"],
        submission["id"],
        main.ClassroomGradeIn(score=16, feedback="Good explanation", release=True),
        faculty,
    )
    released_result = main.list_classroom_submissions(classroom["id"], assessment["id"], first_student)[0]
    assert released_result["score"] == 16
    assert released_result["feedback"] == "Good explanation"


def test_low_faculty_grade_creates_topic_scoped_revision_without_mastery(monkeypatch):
    reset_db()
    faculty = _user("faculty-1")
    student = _user("student-1")
    classroom, module, topic = _published_topic_for(student)
    monkeypatch.setattr(main, "generate_lesson", _fake_revision_lesson)
    assessment = main.create_classroom_assessment(
        classroom["id"],
        main.ClassroomAssessmentIn(
            title="Explain 3NF", kind="assignment", topicId=topic["id"], conceptIds=["3NF"],
            maxMarks=10, published=True,
        ),
        faculty,
    )
    submission = main.submit_classroom_assessment(
        classroom["id"], assessment["id"], main.ClassroomSubmissionIn(answer="An incomplete answer"), student
    )

    main.grade_classroom_submission(
        classroom["id"], assessment["id"], submission["id"],
        main.ClassroomGradeIn(score=8, feedback="Review dependencies", release=False), faculty,
    )

    event = main.db.learning_events.find_one({"sourceSubmissionId": submission["id"]})
    task = main.db.adaptive_tasks.find_one({"userId": student["id"], "topicId": topic["id"]})
    progress = main.classroom_progress(classroom["id"], student)
    assert event["coverage"] is False
    assert event["concepts"] == ["3NF"]
    assert task["conceptIds"] == ["3NF"]
    assert progress["learningPath"]["items"][0]["status"] == "revision_needed"
    assert progress["learningPath"]["items"][0]["mastery"]["score"] is None
    assert progress["modules"][0]["topics"][0]["mastery"]["score"] is None


def test_student_progress_graph_and_faculty_analytics_are_scoped_to_classroom():
    reset_db()
    faculty = _user("faculty-1")
    classroom = main.create_classroom(
        {"name": "DBMS", "subject": "Database systems", "section": "A", "semester": "Fall", "description": ""},
        faculty,
    )
    module = main.create_curriculum_module(
        classroom["id"], main.CurriculumModuleIn(title="Relational design"), faculty
    )
    completed_topic = main.create_curriculum_topic(
        classroom["id"],
        module["id"],
        main.CurriculumTopicIn(
            title="Normalization",
            concepts=[
                main.CurriculumConceptIn(name="3NF", prerequisites=["BCNF"]),
                main.CurriculumConceptIn(name="BCNF"),
            ],
        ),
        faculty,
    )
    pending_topic = main.create_curriculum_topic(
        classroom["id"],
        module["id"],
        main.CurriculumTopicIn(
            title="Indexing",
            concepts=[main.CurriculumConceptIn(name="B-tree")],
        ),
        faculty,
    )
    struggling_topic = main.create_curriculum_topic(
        classroom["id"],
        module["id"],
        main.CurriculumTopicIn(title="Query tuning", concepts=[main.CurriculumConceptIn(name="Index scans")]),
        faculty,
    )
    started_topic = main.create_curriculum_topic(
        classroom["id"],
        module["id"],
        main.CurriculumTopicIn(title="Deadlocks", concepts=[main.CurriculumConceptIn(name="Wait-for graph")]),
        faculty,
    )
    main.publish_classroom_curriculum(classroom["id"], faculty)
    student = _user("student-1")
    main.join_classroom({"joinCode": classroom["joinCode"]}, student)
    assert main.classroom_knowledge_graph(classroom["id"], student)["nodes"] == []
    main.db.sessions.insert_one(
        {
            "_id": "started-session",
            "userId": student["id"],
            "classroomId": classroom["id"],
            "curriculumTopicId": started_topic["id"],
            "curriculumModuleId": module["id"],
            "concepts": ["Wait-for graph"],
            "evaluation": {"completed": False},
        }
    )
    for event_id, score, activity in (("quiz-1", 80, "quiz"), ("assignment-1", 100, "assignment")):
        main.db.learning_events.insert_one(
            {
                "_id": event_id,
                "userId": student["id"],
                "classroomId": classroom["id"],
                "moduleId": module["id"],
                "topicId": completed_topic["id"],
                "concepts": ["3NF"],
                    "conceptResults": {"3NF": {"score": score, "total": 2, "correct": 2, "incorrect": 0, "unanswered": 0}},
                "activityType": activity,
                "evidenceType": "assessment",
                "masteryScore": score,
                "coverage": True,
                "evaluationStatus": "complete",
            }
        )
    for event_id, activity in (("weak-quiz", "quiz"), ("weak-assignment", "assignment")):
        main.db.learning_events.insert_one(
            {
                "_id": event_id,
                "userId": student["id"],
                "classroomId": classroom["id"],
                "moduleId": module["id"],
                "topicId": struggling_topic["id"],
                "concepts": ["Index scans"],
                    "conceptResults": {"Index scans": {"score": 35, "total": 2, "correct": 0, "incorrect": 2, "unanswered": 0}},
                "activityType": activity,
                "evidenceType": "assessment",
                "masteryScore": 35,
                "coverage": True,
                "evaluationStatus": "complete",
            }
        )

    progress = main.classroom_progress(classroom["id"], student)
    graph = main.classroom_knowledge_graph(classroom["id"], student)
    analytics = main.classroom_analytics(classroom["id"], faculty)

    assert progress["coverage"]["percent"] == 50
    assert progress["modules"][0]["topics"][0]["mastery"]["evidenceCount"] == 2
    assert {node["label"] for node in graph["nodes"]} == {"Normalization", "3NF", "Deadlocks", "Query tuning", "Index scans"}
    assert pending_topic["id"] not in {node["curriculumId"] for node in graph["nodes"] if node["kind"] == "topic"}
    assert struggling_topic["id"] in {node["curriculumId"] for node in graph["nodes"] if node["kind"] == "topic"}
    started_node = next(node for node in graph["nodes"] if node["curriculumId"] == started_topic["id"])
    assert started_node["started"] is True
    assert started_node["completed"] is False
    assert started_node["mastery"]["score"] is None
    assert all(edge["source"] in {node["id"] for node in graph["nodes"]} and edge["target"] in {node["id"] for node in graph["nodes"]} for edge in graph["edges"])
    assert not any(edge["kind"] == "prerequisite" for edge in graph["edges"])
    assert all(node["moduleId"] == module["id"] and node["moduleName"] == module["title"] for node in graph["nodes"])
    assert analytics["enrolledStudents"] == 1
    assert analytics["students"][0]["name"] == "Student User"
    assert analytics["averageMastery"] == progress["mastery"]["score"]

    with pytest.raises(main.HTTPException) as private_graph:
        main.classroom_knowledge_graph(classroom["id"], student, "student-2")
    assert private_graph.value.status_code == 403

    with pytest.raises(main.HTTPException) as unowned_analytics:
        main.classroom_analytics(classroom["id"], {"id": "other-faculty", "role": "FACULTY"})
    assert unowned_analytics.value.status_code == 403


def test_ai_evaluation_preserves_submission_and_records_private_evidence(monkeypatch):
    reset_db()
    faculty = _user("faculty-1")
    classroom = main.create_classroom(
        {"name": "DBMS", "subject": "Database systems", "section": "A", "semester": "Fall", "description": ""},
        faculty,
    )
    module = main.create_curriculum_module(
        classroom["id"], main.CurriculumModuleIn(title="Relational design"), faculty
    )
    topic = main.create_curriculum_topic(
        classroom["id"], module["id"],
        main.CurriculumTopicIn(title="Normalization", concepts=[main.CurriculumConceptIn(name="3NF")]),
        faculty,
    )
    main.publish_classroom_curriculum(classroom["id"], faculty)
    assessment = main.create_classroom_assessment(
        classroom["id"],
        main.ClassroomAssessmentIn(title="Explain 3NF", kind="assignment", topicId=topic["id"], conceptIds=["3NF"], maxMarks=10, published=True),
        faculty,
    )
    student = _user("student-1")
    main.join_classroom({"joinCode": classroom["joinCode"]}, student)
    submission = main.submit_classroom_assessment(
        classroom["id"], assessment["id"], main.ClassroomSubmissionIn(answer="A student's original answer"), student
    )
    monkeypatch.setattr(
        main,
        "evaluate_written_answer",
        lambda **_: {"score": 8, "conceptScores": {"3NF": 80}, "strengths": [], "misconceptions": [], "feedback": "Good.", "recommendedTopics": []},
    )
    monkeypatch.setattr(main, "generate_lesson", _fake_revision_lesson)

    result = main.evaluate_classroom_submission(
        classroom["id"], assessment["id"], submission["id"], faculty
    )

    saved = main.db.classroom_submissions.find_one({"_id": submission["id"]})
    event = main.db.learning_events.find_one({"_id": f"learning_event_submission_{submission['id']}"})
    student_view = main.list_classroom_submissions(classroom["id"], assessment["id"], student)[0]
    assert result["score"] == 8
    assert saved["answer"] == "A student's original answer"
    assert saved["aiEvaluation"]["feedback"] == "Good."
    assert event["masteryScore"] == 80
    assert "aiEvaluation" not in student_view


def test_classroom_stream_persists_discussions_and_limits_announcements_to_owner():
    reset_db()
    faculty = _user("faculty-1")
    classroom = main.create_classroom(
        {"name": "DBMS", "subject": "Database systems", "section": "A", "semester": "Fall", "description": ""},
        faculty,
    )
    student = _user("student-1")
    main.join_classroom({"joinCode": classroom["joinCode"]}, student)

    with pytest.raises(main.HTTPException) as denied:
        main.create_classroom_post(
            classroom["id"], main.ClassroomPostIn(kind="announcement", title="Notice", body="Hello"), student
        )
    assert denied.value.status_code == 403

    post = main.create_classroom_post(
        classroom["id"], main.ClassroomPostIn(kind="discussion", title="Question", body="How does 3NF help?"), student
    )
    reply = main.create_classroom_reply(
        classroom["id"], post["id"], main.ClassroomReplyIn(body="It reduces transitive dependency."), faculty
    )
    stream = main.list_classroom_posts(classroom["id"], student)
    assert stream[0]["id"] == post["id"]
    assert stream[0]["replies"][0]["id"] == reply["id"]

    with pytest.raises(main.HTTPException) as private:
        main.list_classroom_posts(classroom["id"], _user("student-2"))
    assert private.value.status_code == 403

    admin_user = _user("admin-1")
    updated = main.update_user_role("student-1", {"role": "FACULTY"}, admin_user)
    assert updated["role"] == "FACULTY"

    target = main.db.users.find_one({"_id": "student-1"})
    assert target["role"] == "FACULTY"


def test_classroom_learning_prompt_handles_empty_optional_topic_fields():
    prompt = main.render_classroom_learning_prompt(
        "Explain the topic",
        {"name": "DBMS", "subject": "Databases"},
        {"title": "Foundations"},
        {
            "_id": "topic-empty",
            "title": "Normalization",
            "description": "",
            "concepts": [],
            "learningObjectives": [],
            "prerequisites": [],
            "materials": [],
        },
    )

    assert "Expected concepts:\nNone specified" in prompt
    assert "Learning objectives:\nNone specified" in prompt
    assert "Prerequisites:\nNone specified" in prompt
    assert "Teacher materials:\nNone provided" in prompt


def test_classroom_ai_stream_emits_lesson_for_topic_without_optional_metadata(monkeypatch):
    reset_db()
    faculty = _user("faculty-1")
    student = _user("student-1")
    classroom = main.create_classroom(
        {"name": "DBMS", "subject": "Databases", "section": "A", "semester": "Fall", "description": ""},
        faculty,
    )
    module = main.create_curriculum_module(
        classroom["id"], main.CurriculumModuleIn(title="Foundations"), faculty
    )
    topic = main.create_curriculum_topic(
        classroom["id"], module["id"], main.CurriculumTopicIn(title="Normalization"), faculty
    )
    main.publish_classroom_curriculum(classroom["id"], faculty)
    main.join_classroom({"joinCode": classroom["joinCode"]}, student)
    monkeypatch.setattr(main, "generate_lesson", lambda *_args, **_kwargs: _fake_revision_lesson())

    response = main.learn_stream(
        main.LearnIn(
            content="Explain normalization",
            classroomId=classroom["id"],
            curriculumTopicId=topic["id"],
        ),
        student,
    )

    async def consume():
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(consume())
    output = "".join(chunks)
    assert '"stage":"ready"' in output
    assert '"learningContent"' in output


def test_student_cannot_view_other_classroom_details():
    reset_db()
    faculty_user = _user("faculty-1")
    created = main.create_classroom(
        {
            "name": "Operating Systems",
            "subject": "OS",
            "section": "B",
            "semester": "2026-01",
            "description": "No access for others.",
        },
        faculty_user,
    )

    external_user = _user("student-1")
    try:
        main.get_classroom(created["id"], external_user)
        raise AssertionError("Expected forbidden error")
    except main.HTTPException as exc:
        assert exc.status_code == 403
