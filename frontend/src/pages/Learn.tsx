import { useEffect, useRef, useState } from "react";
import { ArrowUp, BookOpen, Search, FileText, Plus, X } from "lucide-react";
import { learnStream, ApiError, MSG, learnDocument } from "../lib/api";
import { validateLesson } from "../lib/validate";
import type { Lesson as L } from "../types";
import Lesson from "../components/Lesson";
import { ErrorState, LoadingState } from "../components/States";

type S =
  | { s: "idle" }
  | { s: "loading"; stage: string }
  | { s: "error"; msg: string }
  | { s: "success"; id: string; lesson: L; source?: "topic" | "document"; document?: { title?: string; filename?: string } };

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
  const [documentFile, setDocumentFile] = useState<File | null>(null);
  const [providerModel, setProviderModel] = useState(PROVIDERS[0].value);
  const documentInput = useRef<HTMLInputElement>(null);
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
    if (!documentFile) {
      if (text.trim().length < 3) return;
      const id = ++reqId.current;
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
        if (id !== reqId.current) return;
        const lesson = validateLesson(r.learningContent);
        if (!lesson) throw new ApiError("bad_schema", MSG.bad_schema);
        setState({ s: "success", id: r.sessionId, lesson, source: "topic" });
      } catch (e) {
        if (id !== reqId.current || (e as ApiError).code === "cancelled") return;
        setState({ s: "error", msg: (e as Error).message });
      }
      return;
    }

    const id = ++reqId.current;
    const selected =
      PROVIDERS.find((option) => option.value === providerModel) ?? PROVIDERS[0];
    setState({ s: "loading", stage: "uploading" });
    try {
      const result = await learnDocument(documentFile, {
        difficulty: difficulty as "beginner" | "intermediate" | "advanced",
        provider: selected.provider as "groq" | "gemini" | "openrouter",
        model: selected.model,
        instructions: text.trim(),
      });
      if (id !== reqId.current) return;
      const lesson = validateLesson(result.learningContent);
      if (!lesson) throw new ApiError("bad_schema", MSG.bad_schema);
      setState({
        s: "success",
        id: result.sessionId,
        lesson,
        source: "document",
        document: result.document,
      });
    } catch (e) {
      if (id !== reqId.current) return;
      setState({ s: "error", msg: (e as Error).message });
    }
  }

  const allowedTypes = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/markdown",
  ];

  const handleDocumentFile = (file: File | null) => {
    if (!file) {
      setDocumentFile(null);
      return;
    }
    const ext = file.name.split(".").pop()?.toLowerCase();
    const ok =
      ["pdf", "docx", "txt", "md", "markdown", "pptx"].includes(String(ext ?? "")) ||
      allowedTypes.includes(file.type);
    if (!ok) {
      setState({ s: "error", msg: "Unsupported file type. Please upload a PDF, DOCX, TXT, Markdown, or PPTX document." });
      return;
    }
    setDocumentFile(file);
    setState({ s: "idle" });
  };

  const rateLimitError =
    state.s === "error" && /rate limit|rate limiting|quota|usage limit/i.test(state.msg);

  return (
    <>
      <section className="learn-search">
        <p className="learn-kicker">Search</p>
        <h1>What do you want to know?</h1>

        <input
          ref={documentInput}
          type="file"
          accept=".pdf,.docx,.txt,.md,.markdown,.pptx"
          hidden
          onChange={(event) => {
            handleDocumentFile(event.target.files?.[0] ?? null);
            event.target.value = "";
          }}
        />

        <div className="learn-composer">
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={3}
            aria-label="Topic, question, or document instructions"
            placeholder="Ask anything..."
          />

          {documentFile && (
            <div className="learn-file-attachment">
              <FileText size={14} />
              <span title={documentFile.name}>{documentFile.name}</span>
              <button
                type="button"
                onClick={() => handleDocumentFile(null)}
                aria-label="Remove attached document"
              >
                <X size={14} />
              </button>
            </div>
          )}

          <div className="learn-composer-tools">
            <button
              type="button"
              className="learn-add-button"
              onClick={() => documentInput.current?.click()}
              aria-label="Add a document"
              title="Add a document"
            >
              <Plus size={19} />
            </button>
            <label className="provider-select">
              Model
              <select
                value={providerModel}
                onChange={(event) => setProviderModel(event.target.value)}
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
              disabled={state.s === "loading" || (documentFile ? false : text.trim().length < 3)}
              aria-label={documentFile ? "Learn from attached document" : "Start learning"}
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
        <ErrorState
          message={state.msg}
          title={rateLimitError ? "Unable to generate explanation" : undefined}
          description={
            rateLimitError
              ? "The AI provider is temporarily unavailable or your account may have reached its usage limit."
              : undefined
          }
          onRetry={generate}
          onDismiss={() => setState({ s: "idle" })}
        />
      )}
      {state.s === "success" && (
        <Lesson
          key={state.id}
          lesson={state.lesson}
          sessionId={state.id}
          source={state.source}
          documentMeta={state.document}
        />
      )}
    </>
  );
}
