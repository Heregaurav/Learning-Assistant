import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ArrowRight, ArrowUp, BookOpen, CheckCircle2, Clock3, RotateCcw, Search, FileText, Plus, Sparkles, X } from "lucide-react";
import { completeAdaptiveRevision, createAdaptiveRetest, generateAdaptiveRevision, getClassroomCurriculum, getClassroomTopicSessions, getSession, learnStream, ApiError, MSG, learnDocument } from "../lib/api";
import { validateLesson } from "../lib/validate";
import type { AdaptiveRevisionTask, AdaptivePathItem, ClassroomTopicSession, Lesson as L, Lesson as LessonData } from "../types";
import Lesson from "../components/Lesson";
import { ErrorState, LoadingState } from "../components/States";

type S =
  | { s: "idle" }
  | { s: "loading"; stage: string }
  | { s: "error"; msg: string }
  | { s: "success"; id: string; lesson: L; source?: "topic" | "document"; document?: { title?: string; filename?: string }; initialAnswers?: Record<string, string> };

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

type LearnProps = {
  classroomId?: string;
  curriculumTopicId?: string;
  classroomOnly?: boolean;
  revisionTasks?: AdaptiveRevisionTask[];
  revisionHistory?: AdaptiveRevisionTask[];
  topicStatus?: AdaptivePathItem["status"];
};

export default function Learn({
  classroomId: embeddedClassroomId,
  curriculumTopicId: embeddedTopicId,
  classroomOnly = false,
  revisionTasks = [],
  revisionHistory = [],
  topicStatus,
}: LearnProps = {}) {
  const [searchParams] = useSearchParams();
  const classroomId = embeddedClassroomId ?? searchParams.get("classroomId");
  const curriculumTopicId = embeddedTopicId ?? searchParams.get("topicId");
  const classroomContext = classroomId && curriculumTopicId
    ? { classroomId, curriculumTopicId }
    : undefined;
  const [classroomTopicTitle, setClassroomTopicTitle] = useState("");
  const [topicSessions, setTopicSessions] = useState<ClassroomTopicSession[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyBusyId, setHistoryBusyId] = useState("");
  const [revisionExpanded, setRevisionExpanded] = useState(false);
  const [revisionError, setRevisionError] = useState("");
  const [revisionBusyId, setRevisionBusyId] = useState("");
  const [revisionOverrides, setRevisionOverrides] = useState<Record<string, AdaptiveRevisionTask>>({});
  const [revisionAttempt, setRevisionAttempt] = useState<{ taskId: string; sessionId: string; lesson: LessonData } | null>(null);
  const [text, setText] = useState(""),
    [difficulty, setDifficulty] = useState("beginner");
  const [documentFile, setDocumentFile] = useState<File | null>(null);
  const [providerModel, setProviderModel] = useState(PROVIDERS[0].value);
  const documentInput = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<S>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(ACTIVE_LESSON_KEY) ?? "null");
      const lesson = validateLesson(saved?.lesson);
      return lesson && typeof saved?.id === "string" && !classroomId
        ? { s: "success", id: saved.id, lesson }
        : { s: "idle" };
    } catch {
      return { s: "idle" };
    }
  });
  const reqId = useRef(0),
    ctl = useRef<AbortController | null>(null);
  const topicRevisionTasks = [...new Map(
    [...revisionHistory, ...revisionTasks]
      .filter((task) => task.topicId === curriculumTopicId)
      .map((task) => [task.id, revisionOverrides[task.id] ?? task]),
  ).values()];
  const activeRevisionTasks = topicRevisionTasks.filter((task) => task.status !== "mastered");
  const masteredRevisionTasks = topicRevisionTasks.filter((task) => task.status === "mastered" && task.revisionContent);

  useEffect(() => {
    setRevisionExpanded(false);
    setRevisionError("");
    setRevisionBusyId("");
    setRevisionOverrides({});
    setRevisionAttempt(null);
  }, [classroomId, curriculumTopicId]);

  const prepareRevision = async (task: AdaptiveRevisionTask) => {
    if (!classroomId) return;
    setRevisionBusyId(task.id);
    setRevisionError("");
    try {
      const prepared = task.revisionContent && task.generationStatus === "ready"
        ? task
        : await generateAdaptiveRevision(classroomId, task.id);
      setRevisionOverrides((current) => ({ ...current, [task.id]: prepared }));
    } catch (reason) {
      setRevisionError((reason as Error).message || "Unable to prepare revision materials.");
    } finally {
      setRevisionBusyId("");
    }
  };

  const completeRevision = async (task: AdaptiveRevisionTask) => {
    if (!classroomId) return;
    setRevisionBusyId(task.id);
    setRevisionError("");
    try {
      const completed = await completeAdaptiveRevision(classroomId, task.id);
      setRevisionOverrides((current) => ({ ...current, [task.id]: completed }));
    } catch (reason) {
      setRevisionError((reason as Error).message || "Unable to record revision completion.");
    } finally {
      setRevisionBusyId("");
    }
  };

  const startRetest = async (task: AdaptiveRevisionTask) => {
    if (!classroomId) return;
    setRevisionBusyId(task.id);
    setRevisionError("");
    try {
      const attempt = await createAdaptiveRetest(classroomId, task.id);
      setRevisionAttempt({ taskId: task.id, sessionId: attempt.sessionId, lesson: attempt.learningContent });
    } catch (reason) {
      setRevisionError((reason as Error).message || "Unable to start the revision retest.");
    } finally {
      setRevisionBusyId("");
    }
  };

  useEffect(() => {
    if (!classroomId || !curriculumTopicId) return;
    let cancelled = false;
    setState({ s: "idle" });
    setTopicSessions([]);
    setHistoryError("");
    setHistoryLoading(true);
    getClassroomCurriculum(classroomId)
      .then((curriculum) => {
        const topic = curriculum.modules
          .flatMap((module) => module.topics)
          .find((item) => item.id === curriculumTopicId);
        if (!topic) throw new Error("This topic is not part of the published classroom curriculum.");
        if (cancelled) return;
        setClassroomTopicTitle(topic.title);
        setText(topic.title);
      })
      .catch((reason) => {
        if (!cancelled) setState({ s: "error", msg: (reason as Error).message });
      });
    getClassroomTopicSessions(classroomId, curriculumTopicId)
      .then((sessions) => { if (!cancelled) setTopicSessions(sessions); })
      .catch((reason) => { if (!cancelled) setHistoryError((reason as Error).message || "Unable to load topic history."); })
      .finally(() => { if (!cancelled) setHistoryLoading(false); });
    return () => {
      cancelled = true;
    };
  }, [classroomId, curriculumTopicId]);

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
          classroomContext,
        );
        if (id !== reqId.current) return;
        const lesson = validateLesson(r.learningContent);
        if (!lesson) throw new ApiError("bad_schema", MSG.bad_schema);
        setState({ s: "success", id: r.sessionId, lesson, source: "topic" });
        if (classroomId && curriculumTopicId) {
          void getClassroomTopicSessions(classroomId, curriculumTopicId).then(setTopicSessions).catch(() => undefined);
        }
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

  async function reopenTopicSession(session: ClassroomTopicSession) {
    setHistoryBusyId(session.id);
    setHistoryError("");
    try {
      const saved = await getSession(session.id);
      const lesson = validateLesson(saved.learningContent);
      if (!lesson) throw new ApiError("bad_schema", MSG.bad_schema);
      setText(session.search);
      setDocumentFile(null);
      setState({
        s: "success",
        id: saved.id,
        lesson,
        source: "topic",
        initialAnswers: saved.evaluation?.completed ? saved.answers : undefined,
      });
    } catch (reason) {
      setHistoryError((reason as Error).message || "Unable to reopen this saved lesson.");
    } finally {
      setHistoryBusyId("");
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
        <p className="learn-kicker">{classroomTopicTitle ? "Classroom curriculum" : "Search"}</p>
        <h1>{classroomOnly ? "What do you want to understand?" : "What do you want to know?"}</h1>
        {classroomTopicTitle && <p className="mb-4 text-sm text-primary/80">Learning the published classroom topic: {classroomTopicTitle}</p>}
        {classroomOnly && classroomTopicTitle && (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-y border-primary/15 py-3">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide">
              {topicStatus === "completed" ? <><CheckCircle2 size={15} className="text-emerald-200" /><span className="text-emerald-100">Mastered</span></> : topicStatus === "revision_needed" ? <><RotateCcw size={14} className="text-amber-200" /><span className="text-amber-100">Revision needed</span></> : topicStatus === "locked" ? <><Clock3 size={14} /><span className="text-primary/70">Locked</span></> : <span className="text-primary/65">{topicStatus === "practice" ? "Practice" : "In progress"}</span>}
            </div>
            {(topicStatus === "completed" || activeRevisionTasks.length > 0 || topicStatus === "revision_needed") && (
              <button
                type="button"
                onClick={() => setRevisionExpanded((current) => !current)}
                aria-expanded={revisionExpanded}
                className="inline-flex min-h-9 items-center gap-2 border border-primary/35 px-3 text-xs text-primary hover:bg-primary/10"
              >
                {topicStatus === "completed" ? "Revise" : revisionExpanded ? "Close revision" : "Revise & test"}
              </button>
            )}
          </div>
        )}

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
            placeholder={classroomOnly ? "Ask about this curriculum topic..." : "Ask anything..."}
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

        {!classroomOnly && (
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
        )}
      </section>
      {classroomOnly && curriculumTopicId && (
        <section className="mt-6 border-y border-primary/20 py-4" aria-labelledby="topic-search-history-heading">
          <div className="flex items-end justify-between gap-3">
            <div>
              <p className="text-[10px] uppercase tracking-[0.16em] text-primary/65">Saved for this topic</p>
              <h2 id="topic-search-history-heading" className="mt-1 text-lg font-semibold">Previous searches</h2>
            </div>
            <span className="text-xs text-primary/60">{topicSessions.length}</span>
          </div>
          {historyError && <p role="alert" className="mt-3 text-sm text-red-200">{historyError}</p>}
          {historyLoading ? <p className="mt-3 text-sm text-primary/65">Loading topic history…</p> : topicSessions.length === 0 ? (
            <p className="mt-3 text-sm text-primary/65">Searches and lessons you create for this topic will be saved here.</p>
          ) : (
            <ul className="mt-3 divide-y divide-primary/10">
              {topicSessions.map((session) => (
                <li key={session.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-[#f2efe8]">{session.search || session.topic}</p>
                    <p className="mt-1 text-xs text-primary/60">{new Date(session.createdAt).toLocaleString()} · {session.difficulty}{session.evaluation.completed && session.evaluation.score !== undefined ? ` · ${session.evaluation.score}%` : " · Not completed"}</p>
                  </div>
                  <button type="button" disabled={historyBusyId === session.id} onClick={() => void reopenTopicSession(session)} className="inline-flex min-h-9 items-center gap-2 border border-primary/30 px-3 text-xs text-primary hover:bg-primary/10 disabled:opacity-50">
                    <RotateCcw size={13} /> {historyBusyId === session.id ? "Opening…" : "Revise"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {classroomOnly && revisionExpanded && (
        <section className="mt-4 border-y border-primary/20 py-4" aria-label={`${classroomTopicTitle} revision materials`}>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[10px] uppercase tracking-[0.16em] text-primary/65">Topic review</p>
              <h2 className="mt-1 text-lg font-semibold">{classroomTopicTitle}</h2>
            </div>
            <button type="button" onClick={() => setRevisionExpanded(false)} className="grid h-9 w-9 place-items-center border border-primary/20 text-primary/75" aria-label="Close revision materials"><X size={16} /></button>
          </div>
          {revisionError && <p role="alert" className="mt-3 border border-red-400/30 bg-red-950/30 p-3 text-sm text-red-100">{revisionError}</p>}
          {topicRevisionTasks.length === 0 ? (
            <p className="mt-3 text-sm text-[#c9c4b5]">There are no previously generated targeted revision materials for this topic yet.</p>
          ) : (
            <div className="mt-3 divide-y divide-primary/15 border-y border-primary/15">
              {topicRevisionTasks.map((task) => {
                const busy = revisionBusyId === task.id;
                const hasMaterials = Boolean(task.revisionContent && task.generationStatus === "ready");
                return (
                  <details key={task.id} className="py-3" open={topicRevisionTasks.length === 1}>
                    <summary className="cursor-pointer list-none">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <span className="text-sm font-medium text-[#f2efe8]">{task.conceptIds.length ? task.conceptIds.join(", ") : "Topic-level review"}</span>
                        <span className="text-xs text-primary/65">{task.status === "mastered" ? "Mastered" : task.status === "revision_complete" || task.status === "retest_available" ? "Ready to test" : hasMaterials ? "Materials ready" : task.generationStatus === "generating" ? "Preparing materials…" : "Materials not prepared"}</span>
                      </div>
                    </summary>
                    {task.weakQuestionTexts.length > 0 && <p className="mt-2 text-xs text-primary/65">Revisit: {task.weakQuestionTexts.join(" · ")}</p>}
                    {hasMaterials ? (
                      <div className="mt-3 border-l-2 border-primary/30 pl-4">
                        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-emerald-200/80"><Sparkles size={13} /> Targeted revision lesson</div>
                        <h3 className="mt-2 font-medium text-[#f2efe8]">{task.revisionContent?.topic}</h3>
                        <p className="mt-2 text-sm leading-relaxed text-[#d7d1b5]">{task.revisionContent?.explanation.overview}</p>
                        <div className="mt-3 grid gap-3 md:grid-cols-2">
                          {task.revisionContent?.explanation.sections.map((section) => <article key={section.title} className="border-l border-primary/25 pl-3"><h4 className="text-sm font-medium text-[#f2efe8]">{section.title}</h4><p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-[#c9c4b5]">{section.content}</p></article>)}
                        </div>
                        {task.revisionContent && task.revisionContent.flashcards.length > 0 && <div className="mt-4"><h4 className="text-xs uppercase tracking-wide text-primary/75">Flashcards</h4><ul className="mt-2 grid gap-2 sm:grid-cols-2">{task.revisionContent.flashcards.map((card) => <li key={card.id} className="border border-primary/15 bg-white/[0.02] p-3 text-sm"><p className="font-medium text-[#f2efe8]">{card.question}</p><p className="mt-1 text-[#c9c4b5]">{card.answer}</p></li>)}</ul></div>}
                        {task.status !== "mastered" && <div className="mt-4 flex flex-wrap gap-2">
                          {task.status !== "revision_complete" && task.status !== "retest_available" && task.status !== "generating_retest" && <button type="button" disabled={busy} onClick={() => void completeRevision(task)} className="min-h-10 bg-primary px-4 text-sm font-medium text-black disabled:opacity-50">{busy ? "Saving…" : "I’ve completed this revision"}</button>}
                          {(task.status === "revision_complete" || task.status === "retest_available") && <button type="button" disabled={busy} onClick={() => void startRetest(task)} className="min-h-10 bg-primary px-4 text-sm font-medium text-black disabled:opacity-50">{busy ? "Preparing retest…" : <>Start fresh retest <ArrowRight size={14} className="ml-2 inline" /></>}</button>}
                          {task.status === "generating_retest" && <span className="self-center text-xs text-primary/65">Preparing retest…</span>}
                        </div>}
                      </div>
                    ) : task.status !== "mastered" ? (
                      <div className="mt-3">
                        <button type="button" disabled={busy || task.generationStatus === "generating"} onClick={() => void prepareRevision(task)} className="inline-flex min-h-9 items-center gap-2 border border-primary/35 px-3 text-xs text-primary disabled:opacity-50">
                          {task.generationStatus === "failed" ? <><RotateCcw size={13} /> Retry revision</> : <><Sparkles size={13} /> {busy ? "Preparing…" : "Prepare targeted revision"}</>}
                        </button>
                        {task.generationError && <p className="mt-2 text-xs text-amber-100">Revision material generation failed. Retry when ready.</p>}
                      </div>
                    ) : <p className="mt-3 text-sm text-[#c9c4b5]">Previously generated revision material is unavailable for this task.</p>}
                    {revisionAttempt?.taskId === task.id && <div className="mt-5 border-t border-primary/15 pt-4"><p className="mb-3 text-xs uppercase tracking-wide text-primary/70">Fresh retest</p><Lesson key={revisionAttempt.sessionId} lesson={revisionAttempt.lesson} sessionId={revisionAttempt.sessionId} quizOnly /></div>}
                  </details>
                );
              })}
            </div>
          )}
        </section>
      )}
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
          initialAnswers={state.initialAnswers}
        />
      )}
    </>
  );
}
