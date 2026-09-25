import { useRef, useState } from "react";
import { learn, ApiError, MSG } from "../lib/api";
import { validateLesson } from "../lib/validate";
import type { Lesson as L } from "../types";
import Lesson from "../components/Lesson";
import { ErrorState, LoadingState } from "../components/States";

type S =
  | { s: "idle" }
  | { s: "loading" }
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

export default function Learn() {
  const [text, setText] = useState(""),
    [difficulty, setDifficulty] = useState("beginner");
  const [providerModel, setProviderModel] = useState(PROVIDERS[0].value);
  const [state, setState] = useState<S>({ s: "idle" });
  const reqId = useRef(0),
    ctl = useRef<AbortController | null>(null);

  async function generate() {
    if (text.trim().length < 3) return;
    const id = ++reqId.current; // stale-response guard
    ctl.current?.abort();
    ctl.current = new AbortController();
    setState({ s: "loading" });
    try {
      const selected =
        PROVIDERS.find((option) => option.value === providerModel) ??
        PROVIDERS[0];
      const r = await learn(
        text,
        difficulty,
        selected.provider,
        selected.model,
        ctl.current.signal,
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
      <section className="hero intro">
        <h1>What do you want to learn?</h1>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          aria-label="Topic or notes"
          placeholder="Enter a topic or paste your notes. For example: Teach me binary search trees"
        />
        <div className="actions">
          <div className="seg" role="radiogroup" aria-label="Difficulty">
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
            className="btn"
            onClick={generate}
            disabled={state.s === "loading" || text.trim().length < 3}
          >
            Start learning
          </button>
        </div>
      </section>
      {state.s === "loading" && <LoadingState />}
      {state.s === "error" && (
        <ErrorState message={state.msg} onRetry={generate} />
      )}
      {state.s === "success" && (
        <Lesson key={state.id} lesson={state.lesson} sessionId={state.id} />
      )}
    </>
  );
}
