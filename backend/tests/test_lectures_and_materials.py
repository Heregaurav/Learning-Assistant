import os
import sys
import types
from pathlib import Path
import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main
from models import (
    ClassroomLectureIn,
    ClassroomLectureProgressIn,
    ClassroomLectureUpdateIn,
    ClassroomMaterialUpdateIn,
)
from video_helper import parse_video_url


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
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$ne" in expected and actual == expected["$ne"]:
                    return False
            elif actual != expected:
                return False
        return True

    def find_one(self, query=None, projection=None, sort=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return dict(doc)
        return None

    def find(self, query=None, projection=None, sort=None):
        results = [dict(doc) for doc in self.docs if self._matches(doc, query)]
        return results

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return types.SimpleNamespace(inserted_id=doc.get("_id"))

    def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if self._matches(doc, query):
                if "$set" in update:
                    doc.update(update["$set"])
                return types.SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            merged = dict(query)
            if "$set" in update:
                merged.update(update["$set"])
            self.docs.append(merged)
            return types.SimpleNamespace(matched_count=0, modified_count=1)
        return types.SimpleNamespace(matched_count=0, modified_count=0)

    def delete_one(self, query):
        for idx, doc in enumerate(self.docs):
            if self._matches(doc, query):
                del self.docs[idx]
                return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)

    def delete_many(self, query):
        orig = len(self.docs)
        self.docs[:] = [d for d in self.docs if not self._matches(d, query)]
        return types.SimpleNamespace(deleted_count=orig - len(self.docs))


def setup_test_db():
    main.db = types.SimpleNamespace(
        users=InMemoryCollection(),
        classrooms=InMemoryCollection(),
        classroom_materials=InMemoryCollection(),
        classroom_lectures=InMemoryCollection(),
        classroom_lecture_progress=InMemoryCollection(),
    )
    main.db.users.insert_one({"_id": "teacher-1", "name": "Prof. Smith", "email": "smith@example.com", "role": "FACULTY"})
    main.db.users.insert_one({"_id": "student-1", "name": "Alice Johnson", "email": "alice@example.com", "role": "STUDENT"})
    main.db.users.insert_one({"_id": "student-2", "name": "Bob Lee", "email": "bob@example.com", "role": "STUDENT"})
    main.db.users.insert_one({"_id": "other-user", "name": "Eve Stranger", "email": "eve@example.com", "role": "STUDENT"})

    # Setup classroom
    classroom = {
        "_id": "class-101",
        "name": "Microservices 101",
        "subject": "CS",
        "section": "A",
        "semester": "Fall",
        "description": "Distributed systems",
        "ownerId": "teacher-1",
        "joinCode": "MICRO101",
        "members": [
            {"userId": "teacher-1", "role": "TEACHER", "name": "Prof. Smith"},
            {"userId": "student-1", "role": "STUDENT", "name": "Alice Johnson"},
            {"userId": "student-2", "role": "STUDENT", "name": "Bob Lee"},
        ],
    }
    main.db.classrooms.insert_one(classroom)


def test_video_helper_platform_detection():
    # YouTube watch URL
    yt = parse_video_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert yt["valid"] is True
    assert yt["platform"] == "youtube"
    assert yt["trackingSupported"] is True
    assert "dQw4w9WgXcQ" in yt["embedUrl"]

    # YouTube short URL
    yt_short = parse_video_url("https://youtu.be/dQw4w9WgXcQ")
    assert yt_short["platform"] == "youtube"
    assert yt_short["trackingSupported"] is True

    # Google Drive share URL
    gd = parse_video_url("https://drive.google.com/file/d/1a2b3c4d5e/view?usp=sharing")
    assert gd["valid"] is True
    assert gd["platform"] == "gdrive"
    assert gd["trackingSupported"] is True
    assert "https://drive.google.com/file/d/1a2b3c4d5e/preview" == gd["embedUrl"]

    # Direct video URL
    direct = parse_video_url("https://example.com/videos/lecture1.mp4")
    assert direct["valid"] is True
    assert direct["platform"] == "direct"
    assert direct["trackingSupported"] is True

    # Vimeo URL
    vimeo = parse_video_url("https://vimeo.com/76979871")
    assert vimeo["valid"] is True
    assert vimeo["platform"] == "vimeo"
    assert "player.vimeo.com/video/76979871" in vimeo["embedUrl"]

    # Invalid URL
    invalid = parse_video_url("ftp://not-http.com/test")
    assert invalid["valid"] is False


def test_create_and_list_lectures():
    setup_test_db()
    teacher = {"id": "teacher-1", "role": "FACULTY", "name": "Prof. Smith"}
    student = {"id": "student-1", "role": "STUDENT", "name": "Alice Johnson"}
    stranger = {"id": "other-user", "role": "STUDENT", "name": "Eve Stranger"}

    # Unauthorized student cannot create lecture
    with pytest.raises(HTTPException) as exc_info:
        main.create_classroom_lecture("class-101", ClassroomLectureIn(
            title="Lecture 1",
            videoUrl="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            durationSeconds=3600,
            completionThreshold=80,
        ), student)
    assert exc_info.value.status_code == 403

    # Teacher creates lecture
    lecture = main.create_classroom_lecture("class-101", ClassroomLectureIn(
        title="Lecture 1 — Microservices Intro",
        description="Introduction to principles",
        videoUrl="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        durationSeconds=3600,
        completionThreshold=80,
    ), teacher)
    assert lecture["title"] == "Lecture 1 — Microservices Intro"
    assert lecture["platform"] == "youtube"
    assert lecture["durationSeconds"] == 3600
    assert lecture["completionThreshold"] == 80
    assert lecture["trackingSupported"] is True

    # Student from classroom can list lectures
    lectures = main.list_classroom_lectures("class-101", student)
    assert len(lectures) == 1
    assert lectures[0]["title"] == "Lecture 1 — Microservices Intro"
    assert lectures[0]["progress"]["status"] == "not_started"
    assert lectures[0]["progress"]["watchPercent"] == 0.0

    # User not enrolled cannot list
    with pytest.raises(HTTPException) as exc_info:
        main.list_classroom_lectures("class-101", stranger)
    assert exc_info.value.status_code == 403


def test_lecture_progress_tracking_and_thresholds():
    setup_test_db()
    teacher = {"id": "teacher-1", "role": "FACULTY", "name": "Prof. Smith"}
    student1 = {"id": "student-1", "role": "STUDENT", "name": "Alice Johnson"}
    student2 = {"id": "student-2", "role": "STUDENT", "name": "Bob Lee"}

    lecture = main.create_classroom_lecture("class-101", ClassroomLectureIn(
        title="Lecture 1 — Microservices Intro",
        videoUrl="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        durationSeconds=3600,  # 60 minutes
        completionThreshold=75,  # 75% threshold
    ), teacher)
    lec_id = lecture["id"]

    # Student 1 watches 1800s out of 3600s (50%) -> incomplete at 75% threshold
    p1 = main.record_lecture_progress("class-101", lec_id, ClassroomLectureProgressIn(
        watchedSeconds=1800,
        lastPositionSeconds=1800,
        totalDurationSeconds=3600,
    ), student1)
    assert p1["watchPercent"] == 50.0
    assert p1["completed"] is False
    assert p1["status"] == "in_progress"

    # Student 1 returns and watches up to 2700s out of 3600s (75%) -> completed!
    p2 = main.record_lecture_progress("class-101", lec_id, ClassroomLectureProgressIn(
        watchedSeconds=2700,
        lastPositionSeconds=2700,
        totalDurationSeconds=3600,
    ), student1)
    assert p2["watchPercent"] == 75.0
    assert p2["completed"] is True
    assert p2["status"] == "completed"

    # Student 2 watches only 360s (10%)
    p3 = main.record_lecture_progress("class-101", lec_id, ClassroomLectureProgressIn(
        watchedSeconds=360,
        lastPositionSeconds=360,
        totalDurationSeconds=3600,
    ), student2)
    assert p3["watchPercent"] == 10.0
    assert p3["completed"] is False
    assert p3["status"] == "in_progress"

    # Check teacher analytics
    analytics = main.get_classroom_lecture_analytics("class-101", teacher)
    assert analytics["totalStudents"] == 2
    assert len(analytics["lectures"]) == 1
    lec_stat = analytics["lectures"][0]
    assert lec_stat["totalEnrolled"] == 2
    assert lec_stat["completedCount"] == 1  # Alice
    assert lec_stat["inProgressCount"] == 1  # Bob
    assert lec_stat["notStartedCount"] == 0
    # Average watch percent: (75 + 10) / 2 = 42.5%
    assert lec_stat["averageWatchPercent"] == 42.5

    # If teacher changes threshold to 90%, Alice (at 75%) becomes incomplete
    main.update_classroom_lecture("class-101", lec_id, ClassroomLectureUpdateIn(
        completionThreshold=90
    ), teacher)
    updated_analytics = main.get_classroom_lecture_analytics("class-101", teacher)
    assert updated_analytics["lectures"][0]["completedCount"] == 0
    assert updated_analytics["lectures"][0]["inProgressCount"] == 2


def test_study_materials_crud():
    setup_test_db()
    teacher = {"id": "teacher-1", "role": "FACULTY", "name": "Prof. Smith"}
    student = {"id": "student-1", "role": "STUDENT", "name": "Alice Johnson"}

    # Mock an uploaded file
    class FakeUploadFile:
        def __init__(self, filename, content_type, data):
            self.filename = filename
            self.content_type = content_type
            import io
            self.file = io.BytesIO(data)

    fake_file = FakeUploadFile("notes.pdf", "application/pdf", b"%PDF-1.4 sample content")
    material = main.upload_classroom_material(
        "class-101",
        title="Chapter 1 Notes",
        description="Core reading",
        file=fake_file,
        user=teacher,
    )
    assert material["title"] == "Chapter 1 Notes"
    assert material["filename"] == "notes.pdf"
    assert material["fileSize"] > 0
    assert material["uploadedByName"] == "Prof. Smith"

    # Student can list materials
    materials = main.list_classroom_materials("class-101", student)
    assert len(materials) == 1
    assert materials[0]["title"] == "Chapter 1 Notes"

    # Teacher can update material metadata
    updated = main.update_classroom_material(
        "class-101",
        material["id"],
        ClassroomMaterialUpdateIn(title="Chapter 1 Revised Notes", description="Updated reading"),
        teacher,
    )
    assert updated["title"] == "Chapter 1 Revised Notes"

    # Student cannot delete material
    with pytest.raises(HTTPException) as exc_info:
        main.delete_classroom_material("class-101", material["id"], student)
    assert exc_info.value.status_code == 403

    # Teacher deletes material
    res = main.delete_classroom_material("class-101", material["id"], teacher)
    assert res["deleted"] is True
    assert len(main.list_classroom_materials("class-101", student)) == 0
