import json, os, re
from dotenv import load_dotenv
from openai import OpenAI, APITimeoutError, APIConnectionError
from pydantic import ValidationError
from models import Lesson

load_dotenv()


class LLMError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


SYSTEM = """You are a careful teacher. Turn the learner's topic or notes into a study lesson.
Return ONLY one valid JSON object. No markdown, no code fences, no extra text.
The output must match this exact structure with no missing keys:
{
  "topic": "string",
  "explanation": {
    "overview": "string",
    "sections": [
      {"title": "string", "content": "string", "examples": ["string"]}
    ],
    "keyTakeaways": ["string"],
    "commonMistakes": ["string"]
  },
  "flashcards": [
    {"id": "string", "question": "string", "answer": "string"}
  ],
  "quiz": [
    {"id": "string", "question": "string", "options": ["string", "string", "string", "string"], "correctAnswer": "string", "explanation": "string"}
  ]
}
Rules:
- use exactly the keys above; do not omit any field
- 3-5 sections, 8 flashcards, 8 quiz questions
- every quiz question must have 4 options and exactly one correct answer copied exactly from options
- each flashcard must include an id
- each quiz question must include id, question, options, correctAnswer, explanation
- explanation.keyTakeaways and explanation.commonMistakes are required arrays
- adapt depth to the requested difficulty
- keep answers faithful to the user's notes; do not invent facts
- every quiz question must be specific to the user's topic or notes, never generic filler
- keep every field concise so the complete response, including all 8 quiz questions, fits within 1000 output tokens
- output valid JSON only, with no commentary or markdown"""

QUIZ_SYSTEM = """Create exactly 8 concise quiz questions from the learner's topic or notes.
Return ONLY one JSON object in this shape:
{"quiz":[{"id":"q-1","question":"...","options":["...","...","...","..."],"correctAnswer":"...","explanation":"..."}]}
Every question must test a different, topic-specific fact or idea from the input.
Use exactly 4 distinct options per question and copy correctAnswer exactly from options.
Keep each explanation short. Do not use generic filler or repeat the topic name as a question.
Return valid JSON only."""

PROVIDERS = {
    "groq": {
        "key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "qwen/qwen3.8-27b",
        "models": {"qwen/qwen3.8-27b", "allam-2-7b", "openai/gpt-oss-20b"},
    },
    "gemini": {
        "key": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.0-flash",
        "models": {"gemini-2.0-flash"},
    },
    "openrouter": {
        "key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "models": {"meta-llama/llama-3.3-70b-instruct:free"},
    },
}

_clients = {}


def client(provider: str) -> OpenAI:
    if provider not in PROVIDERS:
        raise LLMError("llm_failed", "Unsupported LLM provider.")
    if provider not in _clients:
        config = PROVIDERS[provider]
        api_key = os.getenv(config["key"])
        if provider == "groq":
            api_key = api_key or os.getenv("LLM_API_KEY")
        if not api_key:
            raise LLMError("missing_api_key", f"Set {config['key']} in backend/.env to use this provider.")
        base_url = os.getenv("LLM_BASE_URL") if provider == "groq" else config["base_url"]
        headers = {"HTTP-Referer": "http://localhost:5173", "X-Title": "AI Learning Assistant"} if provider == "openrouter" else None
        _clients[provider] = OpenAI(api_key=api_key, base_url=base_url, timeout=60, default_headers=headers)
    return _clients[provider]


def _normalize_section(section, index):
    if not isinstance(section, dict):
        return {"title": f"Section {index + 1}", "content": "Key ideas for this topic.", "examples": []}
    examples = section.get("examples") or []
    if not isinstance(examples, list):
        examples = []
    return {
        "title": str(section.get("title") or f"Section {index + 1}"),
        "content": str(section.get("content") or section.get("overview") or "Key ideas for this topic."),
        "examples": [str(x) for x in examples[:3] if str(x).strip()],
    }


def _normalize_flashcards(cards, topic):
    normalized = []
    if isinstance(cards, list):
        for i, card in enumerate(cards[:8], start=1):
            if isinstance(card, dict):
                question = str(card.get("question") or f"What is an important fact about {topic}?")
                answer = str(card.get("answer") or "This concept helps explain the topic.")
                normalized.append({"id": str(card.get("id") or f"card-{i}"), "question": question, "answer": answer})
    while len(normalized) < 8:
        idx = len(normalized) + 1
        normalized.append({
            "id": f"card-{idx}",
            "question": f"What is a key idea related to {topic}?",
            "answer": "It is an important concept that helps explain the topic in a simple way.",
        })
    return normalized[:8]


def _normalize_quiz(quiz, topic):
    normalized = []
    if isinstance(quiz, list):
        for i, q in enumerate(quiz[:8], start=1):
            if isinstance(q, dict):
                options = q.get("options") or []
                if not isinstance(options, list):
                    options = []
                clean_options = [str(opt) for opt in options if str(opt).strip()]
                while len(clean_options) < 4:
                    clean_options.append(f"Option {len(clean_options) + 1}")
                correct = str(q.get("correctAnswer") or (clean_options[0] if clean_options else "Option 1"))
                if correct not in clean_options:
                    correct = clean_options[0]
                normalized.append({
                    "id": str(q.get("id") or f"q-{i}"),
                    "question": str(q.get("question") or f"Which statement best matches {topic}?"),
                    "options": clean_options[:4],
                    "correctAnswer": correct,
                    "explanation": str(q.get("explanation") or "This answer is correct because it matches the core idea."),
                })
    return normalized[:8]


def _quiz_needs_generation(quiz) -> bool:
    if not isinstance(quiz, list) or len(quiz) < 8:
        return True
    questions = [str(item.get("question", "")) for item in quiz if isinstance(item, dict)]
    return len(questions) < 8 or all(question.startswith("Which statement best") for question in questions)


def _repair_lesson(data, topic_hint):
    if not isinstance(data, dict):
        raise ValueError("lesson payload is not an object")

    explanation = data.get("explanation") if isinstance(data.get("explanation"), dict) else {}
    sections = explanation.get("sections") if isinstance(explanation.get("sections"), list) else []
    normalized_sections = [_normalize_section(s, i) for i, s in enumerate(sections[:5])]
    if not normalized_sections:
        overview = str(explanation.get("overview") or data.get("overview") or topic_hint)
        normalized_sections = [{"title": "Overview", "content": overview, "examples": []}]

    overview = str(explanation.get("overview") or data.get("overview") or " ".join(s["content"] for s in normalized_sections[:2]))
    key_takeaways = explanation.get("keyTakeaways") if isinstance(explanation.get("keyTakeaways"), list) and explanation.get("keyTakeaways") else [
        s["content"] for s in normalized_sections[:3]
    ]
    common_mistakes = explanation.get("commonMistakes") if isinstance(explanation.get("commonMistakes"), list) else [
        "Confusing the main idea with a detail.",
        "Forgetting to connect the concept to an example.",
    ]

    repaired = {
        "topic": str(data.get("topic") or topic_hint),
        "explanation": {
            "overview": overview,
            "sections": normalized_sections,
            "keyTakeaways": [str(x) for x in key_takeaways[:5] if str(x).strip()],
            "commonMistakes": [str(x) for x in common_mistakes[:5] if str(x).strip()],
        },
        "flashcards": _normalize_flashcards(data.get("flashcards"), str(data.get("topic") or topic_hint)),
        "quiz": _normalize_quiz(data.get("quiz"), str(data.get("topic") or topic_hint)),
    }
    if not repaired["explanation"]["keyTakeaways"]:
        repaired["explanation"]["keyTakeaways"] = ["This lesson covers the core concept clearly."]
    if not repaired["explanation"]["commonMistakes"]:
        repaired["explanation"]["commonMistakes"] = ["Mixing up the main idea with a detail."]
    return repaired


def generate_lesson(content: str, difficulty: str, provider: str = "groq", model: str | None = None) -> Lesson:
    config = PROVIDERS.get(provider)
    model = model or (config["default_model"] if config else None)
    if not config or model not in config["models"]:
        raise LLMError("llm_failed", "Unsupported model for the selected provider.")
    attempts = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Difficulty: {difficulty}\nInput:\n{content}"},
    ]

    def request(messages, max_tokens=1000):
        try:
            return client(provider).chat.completions.create(
                model=model, temperature=0.2,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=messages,
            )
        except APITimeoutError:
            raise LLMError("timeout", "The model took too long to respond.")
        except APIConnectionError:
            raise LLMError("llm_failed", "Could not reach the LLM provider.")
        except Exception:
            raise LLMError("llm_failed", "The LLM provider returned an error.")

    try:
        r = request(attempts)
    except LLMError:
        raise

    raw = (r.choices[0].message.content or "").strip() if r.choices else ""
    if not raw:
        raise LLMError("empty", "The model returned nothing.")
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise LLMError("invalid_json", "The model returned invalid JSON.")

    if _quiz_needs_generation(data.get("quiz")):
        try:
            quiz_response = request([
                {"role": "system", "content": QUIZ_SYSTEM},
                {"role": "user", "content": f"Topic or notes:\n{content}"},
            ])
            quiz_raw = (quiz_response.choices[0].message.content or "").strip() if quiz_response.choices else ""
            quiz_data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", quiz_raw).strip())
            data["quiz"] = quiz_data.get("quiz") if isinstance(quiz_data, dict) else None
        except (json.JSONDecodeError, TypeError, ValueError):
            raise LLMError("bad_schema", "The model did not return topic-specific quiz questions.")

    try:
        payload = _repair_lesson(data, content.strip()[:80])
        return Lesson.model_validate(payload)
    except ValidationError:
        repair = (
            "Return ONLY a corrected JSON object that exactly matches the schema and includes every required field: "
            "topic, explanation.overview, explanation.sections with title/content/examples, explanation.keyTakeaways, "
            "explanation.commonMistakes, flashcards with id/question/answer, quiz with id/question/options/correctAnswer/explanation. "
            "Do not include markdown."
            f"\n\nInput: {content}\nDifficulty: {difficulty}\nPrevious output:\n{raw}"
        )
        try:
            r2 = request([
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": repair},
            ])
            raw2 = (r2.choices[0].message.content or "").strip() if r2.choices else ""
            raw2 = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw2).strip()
            data2 = json.loads(raw2)
            payload2 = _repair_lesson(data2, content.strip()[:80])
            return Lesson.model_validate(payload2)
        except Exception:
            raise LLMError("bad_schema", "The JSON did not match the lesson schema.")
