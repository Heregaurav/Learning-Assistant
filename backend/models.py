from typing import List, Literal, Dict
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


class LearnIn(BaseModel):
    content: str = Field(min_length=3, max_length=20000)
    difficulty: Literal["beginner", "intermediate", "advanced"] = "beginner"
    provider: Literal["groq", "gemini", "openrouter"] = "groq"
    model: str = "qwen/qwen3.8-27b"


class CompleteIn(BaseModel):
    correct: int = Field(ge=0)
    incorrect: int = Field(ge=0)
    total: int = Field(gt=0)
    cardsReviewed: int = Field(default=0, ge=0)
    answers: Dict[str, str] = {}

    @model_validator(mode="after")
    def check_total(self):
        if self.correct + self.incorrect != self.total:
            raise ValueError("correct + incorrect must equal total")
        return self


class GoogleAuthIn(BaseModel):
    credential: str = Field(min_length=20)
