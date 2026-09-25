import { useEffect, useRef, useState } from "react";
import { ArrowUp, BookOpen, Search } from "lucide-react";
import { learnStream, ApiError, MSG } from "../lib/api";
import { validateLesson } from "../lib/validate";
import type { Lesson as L } from "../types";
import Lesson from "../components/Lesson";
import { ErrorState, LoadingState } from "../components/States";

type S =
  | { s: "idle" }
  | { s: "loading"; stage: string }
  | { s: "error"; msg: string }
  | { s: "success"; id: string; lesson: L };

const PROVIDERS = [
  {
    value: "groq:qwen/qwen3.8-27b",
    label: "Groq · Qwen 3.8 27B",
    provider: "groq",
    model: "qwen/qwen3.8-27b",
  },
  {
    value: "gemini:gemini-flash-lite-latest",
    label: "Gemini · Flash Lite",
    provider: "gemini",
    model: "gemini-flash-lite-latest",
  },
];
const ACTIVE_LESSON_KEY = "curiosity.active-lesson";

export default function Learn() {
  const [text, setText] = useState(""),
    [difficulty, setDifficulty] = useState("beginner");
  const [providerModel, setProviderModel] = useState(PROVIDERS[0].value);
  const [state, setState] = useState<S>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(ACTIVE_LESSON_KEY) ?? "null");
      const lesson = validateLesson(saved?.lesson);
      return lesson && typeof saved?.id === "string"
        ? { s: "success", id: saved.id, lesson }
        : { s: "idle" };
    } catch {
      return { s: "idle" };
    }
  });
  const reqId = useRef(0),
    ctl = useRef<AbortController | null>(null);

  useEffect(() => {
    if (state.s === "success") {
      localStorage.setItem(
        ACTIVE_LESSON_KEY,
        JSON.stringify({ id: state.id, lesson: state.lesson }),
      );
    }
  }, [state]);

  async function generate() {
    if (text.trim().length < 3) return;
    const id = ++reqId.current; // stale-response guard
    ctl.current?.abort();
    ctl.current = new AbortController();
    setState({ s: "loading", stage: "understanding" });
    try {
      const selected =
        PROVIDERS.find((option) => option.value === providerModel) ??
        PROVIDERS[0];
      const r = await learnStream(
        text,
        difficulty,
        selected.provider,
        selected.model,
        ctl.current.signal,
        (stage) => {
          if (id === reqId.current) setState({ s: "loading", stage });
        },
      );
      if (id !== reqId.current) return; // a newer request has started; drop this one
      const lesson = validateLesson(r.learningContent); // only parsed + validated data reaches the UI
      if (!lesson) throw new ApiError("bad_schema", MSG.bad_schema);
      setState({ s: "success", id: r.sessionId, lesson });
    } catch (e) {
      if (id !== reqId.current || (e as ApiError).code === "cancelled") return;
      setState({ s: "error", msg: (e as Error).message });
    }
  }

  return (
    <>
      <section className="learn-search">
        <p className="learn-kicker">Search</p>
        <h1>What do you want to know?</h1>
        <div className="learn-composer">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            aria-label="Topic or notes"
            placeholder="Ask anything..."
          />

          <div className="learn-composer-tools">

            <label className="provider-select">
              Model
              <select
                value={providerModel}
                onChange={(e) => setProviderModel(e.target.value)}
                disabled={state.s === "loading"}
              >
                {PROVIDERS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="learn-submit"
              onClick={generate}
              disabled={state.s === "loading" || text.trim().length < 3}
              aria-label="Start learning"
            >
              <ArrowUp size={18} />
            </button>
          </div>
        </div>
        <div className="learn-difficulty seg" role="radiogroup" aria-label="Difficulty">
          {["beginner", "intermediate", "advanced"].map((d) => (
            <button
              key={d}
              role="radio"
              aria-checked={difficulty === d}
              onClick={() => setDifficulty(d)}
            >
              {d}
            </button>
          ))}
        </div>
        <div className="learn-suggestions">
          <button
            className="learn-suggestion learn-suggestion-primary"
            onClick={() => setText("Explain a topic from trusted sources")}
          >
            <strong>
              <Search size={16} /> Search any Topic 
            </strong>
            <span>Get a clear, structured explanation of any topic.</span>
          </button>
          <button
            className="learn-suggestion"
            onClick={() => setText("Turn my notes into a study lesson")}
          >
            <strong>
              <BookOpen size={16} /> Turn notes into a lesson
            </strong>
            <span>Build explanations, flashcards, and a quiz.</span>
          </button>
        </div>
      </section>
      {state.s === "loading" && <LoadingState stage={state.stage} />}
      {state.s === "error" && (
        <ErrorState message={state.msg} onRetry={generate} />
      )}
      {state.s === "success" && (
        <Lesson key={state.id} lesson={state.lesson} sessionId={state.id} />
      )}
    </>
  );
}
