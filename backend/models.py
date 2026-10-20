from datetime import datetime
from typing import List, Literal, Dict, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field, model_validator


class Section(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    examples: List[str] = []


class Explanation(BaseModel):
    overview: str = Field(min_length=1)
    sections: List[Section] = Field(min_length=1)
    keyTakeaways: List[str] = Field(min_length=1)
    commonMistakes: List[str] = []


class ContentBlock(BaseModel):
    kind: Literal["card", "chart", "checklist"]
    title: str = Field(min_length=1)
    body: Optional[str] = None
    items: List[str] = []
    labels: List[str] = []
    values: List[float] = []


class Flashcard(BaseModel):
    id: str
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class QuizQuestion(BaseModel):
    id: str
    question: str = Field(min_length=1)
    options: List[str] = Field(min_length=2)
    correctAnswer: str
    explanation: str = Field(min_length=1)
    conceptIds: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_answer(self):
        if len(set(self.options)) != len(self.options):
            raise ValueError("duplicate options")
        if self.correctAnswer not in self.options:
            raise ValueError("correctAnswer must match exactly one option")
        return self


class Lesson(BaseModel):
    topic: str = Field(min_length=1)
    explanation: Explanation
    flashcards: List[Flashcard] = Field(min_length=1)
    quiz: List[QuizQuestion] = Field(min_length=1)
    blocks: List[ContentBlock] = []


class LearnIn(BaseModel):
    content: str = Field(min_length=3, max_length=20000)
    difficulty: Literal["beginner", "intermediate", "advanced"] = "beginner"
    provider: Literal["groq", "gemini", "openrouter"] = "groq"
    model: str = "qwen/qwen3.8-27b"
    classroomId: Optional[str] = None
    curriculumTopicId: Optional[str] = None
    curriculumConceptId: Optional[str] = None

    @model_validator(mode="after")
    def classroom_context_pair(self):
        if bool(self.classroomId) != bool(self.curriculumTopicId):
            raise ValueError("classroomId and curriculumTopicId must be provided together")
        if self.curriculumConceptId and not self.classroomId:
            raise ValueError("curriculumConceptId requires classroom context")
        return self


class DocumentLearningRequest(BaseModel):
    difficulty: Literal["beginner", "intermediate", "advanced"] = "beginner"
    provider: Literal["groq", "gemini", "openrouter"] = "groq"
    model: str = "qwen/qwen3.8-27b"
    instructions: str = ""


class CompleteIn(BaseModel):
    correct: Optional[int] = Field(default=None, ge=0)
    incorrect: Optional[int] = Field(default=None, ge=0)
    total: Optional[int] = Field(default=None, gt=0)
    cardsReviewed: int = Field(default=0, ge=0)
    answers: Dict[str, str] = {}

    @model_validator(mode="after")
    def check_total(self):
        if self.correct is not None and self.incorrect is not None and self.total is not None and self.correct + self.incorrect != self.total:
            raise ValueError("correct + incorrect must equal total")
        return self


class RefineIn(BaseModel):
    prompt: str = Field(min_length=3, max_length=1000)


class GoogleAuthIn(BaseModel):
    credential: str = Field(min_length=20)


class ClassroomCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=200)
    section: str = Field(min_length=1, max_length=50)
    semester: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)


class ClassroomJoinIn(BaseModel):
    joinCode: str = Field(min_length=3, max_length=20)


class UserRoleUpdateIn(BaseModel):
    role: str = Field(min_length=3, max_length=20)


class CurriculumModuleIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    position: int = Field(default=0, ge=0)


class CurriculumGenerateIn(BaseModel):
    prompt: str = Field(min_length=10, max_length=20000)
    provider: Literal["groq", "gemini", "openrouter"] = "groq"
    model: str = "qwen/qwen3.8-27b"


class CurriculumConceptIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    prerequisites: List[str] = Field(default_factory=list)


class CurriculumMaterialIn(BaseModel):
    kind: Literal["note", "link"]
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(default="", max_length=20000)
    url: Optional[str] = None

    @model_validator(mode="after")
    def validate_link(self):
        if self.kind == "link":
            parsed = urlparse(self.url or "")
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("link materials require an http or https URL")
        return self


class CurriculumTopicIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=3000)
    learningObjectives: List[str] = Field(default_factory=list, max_length=30)
    prerequisites: List[str] = Field(default_factory=list)
    concepts: List[CurriculumConceptIn] = Field(default_factory=list, max_length=50)
    materials: List[CurriculumMaterialIn] = Field(default_factory=list, max_length=30)


class ClassroomAssessmentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["assignment", "quiz", "test", "practice", "curiosity"]
    instructions: str = Field(default="", max_length=10000)
    topicId: Optional[str] = None
    conceptIds: List[str] = Field(default_factory=list, max_length=50)
    dueAt: Optional[datetime] = None
    maxMarks: float = Field(gt=0, le=10000)
    rubric: str = Field(default="", max_length=10000)
    expectedAnswer: str = Field(default="", max_length=10000)
    published: bool = False


class ClassroomSubmissionIn(BaseModel):
    answer: str = Field(min_length=1, max_length=50000)


class ClassroomGradeIn(BaseModel):
    score: float = Field(ge=0)
    feedback: str = Field(default="", max_length=10000)
    release: bool = False


class ClassroomPostIn(BaseModel):
    kind: Literal["announcement", "discussion"]
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=12000)


class ClassroomReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ClassroomTutorMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    topicId: Optional[str] = None
    conceptName: Optional[str] = Field(default=None, max_length=160)
    provider: Literal["groq", "gemini", "openrouter"] = "groq"
    model: str = "qwen/qwen3.8-27b"
