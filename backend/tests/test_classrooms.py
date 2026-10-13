import os
import sys
import types
import asyncio
from pathlib import Path

import pytest
from fastapi import Response

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/testdb")

import main  # noqa: E402
from models import Explanation, Flashcard, Lesson, QuizQuestion, Section  # noqa: E402


class InMemoryCollection:
    def __init__(self):
        self.docs = []

    def find_one(self, query=None, projection=None, sort=None):
        query = query or {}
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    def find(self, query=None, projection=None, sort=None):
        query = query or {}
        results = [doc for doc in self.docs if all(doc.get(k) == v for k, v in query.items())]
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
            if all(doc.get(k) == v for k, v in query.items()):
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
        return sum(1 for doc in self.docs if all(doc.get(k) == v for k, v in query.items()))

    def delete_one(self, query):
        for idx, doc in enumerate(self.docs):
            if all(doc.get(k) == v for k, v in query.items()):
                del self.docs[idx]
                return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)

    def delete_many(self, query):
        original_count = len(self.docs)
        self.docs[:] = [
            doc for doc in self.docs
            if not all(doc.get(k) == v for k, v in query.items())
        ]
        return types.SimpleNamespace(deleted_count=original_count - len(self.docs))


def reset_db():
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


def test_only_classroom_owner_can_delete_and_related_data_is_removed():
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
    assert main.db.classrooms.find_one({"_id": classroom["id"]}) is None
    assert main.db.classroom_modules.find_one({"classroomId": classroom["id"]}) is None
    assert main.db.learning_paths.find_one({"classroomId": classroom["id"]}) is None


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

    result = main.google_auth(main.GoogleAuthIn(credential="x" * 20), Response())

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

    result = main.google_auth(main.GoogleAuthIn(credential="x" * 20), Response())

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

    result = main.google_auth(main.GoogleAuthIn(credential="x" * 20), Response())

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


def test_session_cookie_is_cross_site_compatible_when_secure(monkeypatch):
    monkeypatch.setattr(main, "SESSION_COOKIE_SECURE", True)
    monkeypatch.setattr(main, "SESSION_COOKIE_SAMESITE", "none")

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


def test_completed_classroom_quiz_records_learning_evidence():
    reset_db()
    student = _user("student-1")
    main.db.sessions.insert_one(
        {
            "_id": "session-classroom-quiz",
            "userId": student["id"],
            "topicId": "topic-personal",
            "classroomId": "class-1",
            "curriculumTopicId": "curriculum-topic-1",
            "curriculumModuleId": "module-1",
            "concepts": ["3NF"],
            "evaluation.completed": True,
            "evaluation": {"completed": True, "score": 80},
        }
    )

    result = main.complete(
        "session-classroom-quiz",
        main.CompleteIn(correct=4, incorrect=1, total=5),
        student,
    )

    event = main.db.learning_events.find_one(
        {"_id": "learning_event_session_session-classroom-quiz"}
    )
    assert result["evaluation"]["score"] == 80
    assert event["classroomId"] == "class-1"
    assert event["topicId"] == "curriculum-topic-1"
    assert event["activityType"] == "curiosity_quiz"
    assert event["masteryScore"] == 80


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
