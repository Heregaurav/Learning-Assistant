from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="Learner")
    email: Mapped[str] = mapped_column(Text, default="")
    picture: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[str] = mapped_column(String(20), default="STUDENT", index=True)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    createdAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("id", "userId", name="uq_topics_id_user"),
        CheckConstraint('"retestsUsed" >= 0', name="ck_topics_retests_nonnegative"),
        Index("ix_topics_user_last_studied", "userId", "lastStudied"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    userId: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, default="")
    firstStudied: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lastStudied: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str] = mapped_column(Text, default="")
    keyConcepts: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    retestsUsed: Mapped[int] = mapped_column(Integer, default=0)


class LearningSession(Base):
    __tablename__ = "learning_sessions"
    __table_args__ = (
        UniqueConstraint("id", "userId", name="uq_learning_session_id_user"),
        ForeignKeyConstraint(["curriculumTopicId", "classroomId"], ["curriculum_topics.id", "curriculum_topics.classroomId"], ondelete='SET NULL ("curriculumTopicId")', name="fk_learning_session_curriculum_topic_class"),
        ForeignKeyConstraint(["curriculumModuleId", "classroomId"], ["curriculum_modules.id", "curriculum_modules.classroomId"], ondelete='SET NULL ("curriculumModuleId")', name="fk_learning_session_curriculum_module_class"),
        Index("ix_learning_sessions_user_created", "userId", "createdAt"),
        Index("ix_learning_sessions_user_adaptive_task", "userId", "adaptiveTaskId"),
        Index("ix_learning_sessions_class_topic_created", "classroomId", "curriculumTopicId", "createdAt"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    userId: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    topicId: Mapped[str | None] = mapped_column(String(255))
    topic: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str | None] = mapped_column(String(40))
    difficulty: Mapped[str] = mapped_column(String(40), default="beginner")
    provider: Mapped[str] = mapped_column(String(80), default="groq")
    model: Mapped[str] = mapped_column(Text, default="")
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    learningContent: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evaluation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    questionResults: Mapped[list[Any] | None] = mapped_column(JSONB)
    conceptResults: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cardsReviewed: Mapped[int] = mapped_column(Integer, default=0)
    createdAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classroomId: Mapped[str | None] = mapped_column(ForeignKey("classrooms.id", ondelete="SET NULL"))
    curriculumTopicId: Mapped[str | None] = mapped_column(String(255))
    curriculumModuleId: Mapped[str | None] = mapped_column(String(255))
    concepts: Mapped[list[Any] | None] = mapped_column(JSONB)
    classroomSearch: Mapped[str | None] = mapped_column(Text)
    document: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    orchestrationStatus: Mapped[str | None] = mapped_column(String(40))
    orchestratedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    adaptiveTaskId: Mapped[str | None] = mapped_column(String(255))
    adaptiveAttempt: Mapped[int | None] = mapped_column(Integer)


class TopicSession(Base):
    __tablename__ = "topic_sessions"
    __table_args__ = (
        ForeignKeyConstraint(["topicId", "userId"], ["topics.id", "topics.userId"], ondelete="CASCADE", name="fk_topic_session_topic_owner"),
        ForeignKeyConstraint(["sessionId", "userId"], ["learning_sessions.id", "learning_sessions.userId"], ondelete="CASCADE", name="fk_topic_session_session_owner"),
    )

    topicId: Mapped[str] = mapped_column(String(255), primary_key=True)
    sessionId: Mapped[str] = mapped_column(String(255), primary_key=True)
    userId: Mapped[str] = mapped_column(String(255), nullable=False)


class Classroom(Base):
    __tablename__ = "classrooms"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    section: Mapped[str] = mapped_column(Text, default="")
    semester: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    ownerId: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    facultyIds: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    joinCode: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active")
    curriculumStatus: Mapped[str] = mapped_column(String(40), default="draft")
    curriculumVersion: Mapped[int] = mapped_column(Integer, default=0)
    createdAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletionState: Mapped[str | None] = mapped_column(String(40), index=True)
    deletionToken: Mapped[str | None] = mapped_column(String(64))
    deleteUntil: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClassroomMember(Base):
    __tablename__ = "classroom_members"
    __table_args__ = (
        UniqueConstraint("classroomId", "userId", name="uq_classroom_member"),
        Index("ix_classroom_members_user_classroom", "userId", "classroomId"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    classroomId: Mapped[str] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)
    userId: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="STUDENT")
    joinedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CurriculumModule(Base):
    __tablename__ = "curriculum_modules"
    __table_args__ = (
        UniqueConstraint("id", "classroomId", name="uq_module_id_classroom"),
        Index("ix_modules_classroom_position", "classroomId", "position"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    classroomId: Mapped[str] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    createdAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CurriculumTopic(Base):
    __tablename__ = "curriculum_topics"
    __table_args__ = (
        ForeignKeyConstraint(["moduleId", "classroomId"], ["curriculum_modules.id", "curriculum_modules.classroomId"], ondelete="CASCADE", name="fk_curriculum_topic_module_class"),
        UniqueConstraint("id", "classroomId", name="uq_curriculum_topic_id_class"),
        Index("ix_topics_class_module_position", "classroomId", "moduleId", "position"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    classroomId: Mapped[str] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)
    moduleId: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    learningObjectives: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    prerequisiteRefs: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    concepts: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    materials: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    position: Mapped[int] = mapped_column(Integer, default=0)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    createdAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TopicPrerequisite(Base):
    __tablename__ = "topic_prerequisites"
    __table_args__ = (
        ForeignKeyConstraint(["topicId", "classroomId"], ["curriculum_topics.id", "curriculum_topics.classroomId"], ondelete="CASCADE", name="fk_prerequisite_topic_class"),
        ForeignKeyConstraint(["prerequisiteId", "classroomId"], ["curriculum_topics.id", "curriculum_topics.classroomId"], ondelete="CASCADE", name="fk_prerequisite_target_class"),
    )

    topicId: Mapped[str] = mapped_column(String(255), primary_key=True)
    prerequisiteId: Mapped[str] = mapped_column(String(255), primary_key=True)
    classroomId: Mapped[str] = mapped_column(String(255), nullable=False)


class ConceptPrerequisite(Base):
    __tablename__ = "concept_prerequisites"
    __table_args__ = (
        ForeignKeyConstraint(["topicId", "classroomId"], ["curriculum_topics.id", "curriculum_topics.classroomId"], ondelete="CASCADE", name="fk_concept_prerequisite_topic_class"),
        Index("ix_concept_prerequisites_class_name", "classroomId", "prerequisiteName"),
    )

    topicId: Mapped[str] = mapped_column(String(255), primary_key=True)
    conceptName: Mapped[str] = mapped_column(String(160), primary_key=True)
    prerequisiteName: Mapped[str] = mapped_column(String(160), primary_key=True)
    classroomId: Mapped[str] = mapped_column(String(255), nullable=False)


class ClassroomAssessment(Base):
    __tablename__ = "classroom_assessments"
    __table_args__ = (
        ForeignKeyConstraint(["topicId", "classroomId"], ["curriculum_topics.id", "curriculum_topics.classroomId"], ondelete='SET NULL ("topicId")', name="fk_assessment_topic_class"),
        UniqueConstraint("id", "classroomId", name="uq_assessment_id_class"),
        CheckConstraint('"maxMarks" > 0', name="ck_assessment_max_marks_positive"),
        Index("ix_assessments_class_created", "classroomId", "createdAt"),
        Index("ix_assessments_class_due", "classroomId", "dueAt"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    classroomId: Mapped[str] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(40), default="assignment")
    instructions: Mapped[str] = mapped_column(Text, default="")
    topicId: Mapped[str | None] = mapped_column(String(255))
    conceptIds: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    dueAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    maxMarks: Mapped[float] = mapped_column(Float, nullable=False)
    rubric: Mapped[str] = mapped_column(Text, default="")
    expectedAnswer: Mapped[str] = mapped_column(Text, default="")
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    createdBy: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    createdAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClassroomSubmission(Base):
    __tablename__ = "classroom_submissions"
    __table_args__ = (
        ForeignKeyConstraint(["assessmentId", "classroomId"], ["classroom_assessments.id", "classroom_assessments.classroomId"], ondelete="CASCADE", name="fk_submission_assessment_class"),
        UniqueConstraint("assessmentId", "studentId", name="uq_submission_student_assessment"),
        Index("ix_submissions_class_student_time", "classroomId", "studentId", "submittedAt"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    classroomId: Mapped[str] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)
    assessmentId: Mapped[str] = mapped_column(String(255), nullable=False)
    studentId: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    answer: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="submitted")
    evaluationStatus: Mapped[str] = mapped_column(String(40), default="pending")
    submittedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[float | None] = mapped_column(Float)
    feedback: Mapped[str | None] = mapped_column(Text)
    released: Mapped[bool] = mapped_column(Boolean, default=False)
    gradedBy: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    gradedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aiEvaluation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    aiEvaluatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClassroomPost(Base):
    __tablename__ = "classroom_posts"
    __table_args__ = (
        UniqueConstraint("id", "classroomId", name="uq_post_id_class"),
        Index("ix_posts_class_created", "classroomId", "createdAt"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    classroomId: Mapped[str] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), default="discussion")
    title: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    authorId: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    createdAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClassroomReply(Base):
    __tablename__ = "classroom_replies"
    __table_args__ = (
        ForeignKeyConstraint(["postId", "classroomId"], ["classroom_posts.id", "classroom_posts.classroomId"], ondelete="CASCADE", name="fk_reply_post_class"),
        Index("ix_replies_class_post_created", "classroomId", "postId", "createdAt"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    classroomId: Mapped[str] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)
    postId: Mapped[str] = mapped_column(String(255), nullable=False)
    authorId: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    createdAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningEvent(Base):
    __tablename__ = "learning_events"
    __table_args__ = (
        Index("ix_events_class_student_occurred", "classroomId", "userId", "occurredAt"),
        Index("ix_events_class_topic", "classroomId", "topicId"),
        ForeignKeyConstraint(["topicId", "classroomId"], ["curriculum_topics.id", "curriculum_topics.classroomId"], ondelete='SET NULL ("topicId")', name="fk_event_topic_class"),
        ForeignKeyConstraint(["moduleId", "classroomId"], ["curriculum_modules.id", "curriculum_modules.classroomId"], ondelete='SET NULL ("moduleId")', name="fk_event_module_class"),
        CheckConstraint('"score" IS NULL OR "maxScore" IS NULL OR "maxScore" > 0', name="ck_events_max_score_positive"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    userId: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    classroomId: Mapped[str] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)
    moduleId: Mapped[str | None] = mapped_column(String(255))
    topicId: Mapped[str | None] = mapped_column(String(255))
    concepts: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    conceptResults: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    questionResults: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    mappingStatus: Mapped[str | None] = mapped_column(String(40))
    activityType: Mapped[str | None] = mapped_column(String(80))
    evidenceType: Mapped[str | None] = mapped_column(String(40))
    sourceSubmissionId: Mapped[str | None] = mapped_column(String(255))
    sourceSessionId: Mapped[str | None] = mapped_column(String(255))
    score: Mapped[float | None] = mapped_column(Float)
    maxScore: Mapped[float | None] = mapped_column(Float)
    masteryScore: Mapped[float | None] = mapped_column(Float)
    coverage: Mapped[bool] = mapped_column(Boolean, default=False)
    total: Mapped[int] = mapped_column(Integer, default=0)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    incorrect: Mapped[int] = mapped_column(Integer, default=0)
    unanswered: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    evaluationStatus: Mapped[str | None] = mapped_column(String(40))
    occurredAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    createdAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningPath(Base):
    __tablename__ = "learning_paths"
    __table_args__ = (UniqueConstraint("classroomId", "userId", name="uq_learning_path_class_user"),)

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    classroomId: Mapped[str] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)
    userId: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    path: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdaptiveTask(Base):
    __tablename__ = "adaptive_tasks"
    __table_args__ = (
        ForeignKeyConstraint(["topicId", "classroomId"], ["curriculum_topics.id", "curriculum_topics.classroomId"], ondelete='SET NULL ("topicId")', name="fk_adaptive_topic_class"),
        Index("ix_adaptive_student_topic_status", "classroomId", "userId", "topicId", "status"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    classroomId: Mapped[str] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)
    userId: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    topicId: Mapped[str | None] = mapped_column(String(255))
    moduleId: Mapped[str | None] = mapped_column(String(255))
    conceptIds: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    weakQuestionIds: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    weakQuestionTexts: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    mappingStatus: Mapped[str | None] = mapped_column(String(40))
    sourceSessionId: Mapped[str | None] = mapped_column(String(255))
    sourceEventId: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    generationStatus: Mapped[str | None] = mapped_column(String(40))
    generationToken: Mapped[str | None] = mapped_column(String(64))
    generationStartedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generationError: Mapped[str | None] = mapped_column(String(100))
    revisionContent: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    difficulty: Mapped[str | None] = mapped_column(String(40))
    provider: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(Text)
    attemptHistory: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    masteredAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lastRetestScore: Mapped[float | None] = mapped_column(Float)
    revisionCompletedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retestGenerationStartedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retestGenerationAttempt: Mapped[int | None] = mapped_column(Integer)
    retestGenerationError: Mapped[str | None] = mapped_column(String(100))
    retestAttempt: Mapped[int] = mapped_column(Integer, default=0)
    currentSessionId: Mapped[str | None] = mapped_column(String(255))
    createdAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))