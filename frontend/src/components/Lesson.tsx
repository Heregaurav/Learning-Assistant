import { useMemo, useState } from "react";
import type { ContentBlock, Lesson as L } from "../types";
import { completeSession, refineSession } from "../lib/api";
import { validateLesson } from "../lib/validate";

type Props = {
  lesson: L;
  sessionId: string;
  initialAnswers?: Record<string, string>;
};
const TABS = ["Explanation", "Flashcards", "Quiz"] as const;

export default function Lesson({ lesson, sessionId, initialAnswers }: Props) {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Explanation");
  const [viewed, setViewed] = useState<Set<string>>(new Set());
  const [currentLesson, setCurrentLesson] = useState(lesson);
  const [refinement, setRefinement] = useState("");
  const [refining, setRefining] = useState(false);
  const [refineError, setRefineError] = useState("");
  const e = currentLesson.explanation;
  const refine = async () => {
    if (refinement.trim().length < 3 || refining) return;
    setRefining(true);
    setRefineError("");
    try {
      const result = await refineSession(sessionId, refinement.trim());
      const next = validateLesson(result.learningContent);
      if (!next) throw new Error("The refined lesson had an unexpected format.");
      setCurrentLesson(next);
      localStorage.setItem(
        "curiosity.active-lesson",
        JSON.stringify({ id: sessionId, lesson: next }),
      );
      setRefinement("");
    } catch (error) {
      setRefineError((error as Error).message);
    } finally {
      setRefining(false);
    }
  };
  return (
    <article>
      <header className="hero">
        <h1>{currentLesson.topic}</h1>
        <div className="chips">
          {e.sections.map((s) => (
            <span key={s.title} className="chip">
              {s.title}
            </span>
          ))}
        </div>
        <p className="lead">{e.overview}</p>
        <form
          className="refine-form"
          onSubmit={(event) => {
            event.preventDefault();
            void refine();
          }}
        >
          <input
            value={refinement}
            onChange={(event) => setRefinement(event.target.value)}
            placeholder="Refine this lesson, e.g. make it simpler"
            aria-label="Refine this lesson"
            disabled={refining}
          />
          <button className="btn" disabled={refining || refinement.trim().length < 3}>
            {refining ? "Refining..." : "Refine"}
          </button>
        </form>
        {refineError && <p className="err">{refineError}</p>}
      </header>
      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            onKeyDown={(event) => {
              if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
              event.preventDefault();
              const index = TABS.indexOf(t);
              const next = event.key === "ArrowRight"
                ? (index + 1) % TABS.length
                : (index - 1 + TABS.length) % TABS.length;
              setTab(TABS[next]);
              document.querySelector<HTMLButtonElement>(
                `[role="tab"][data-tab="${TABS[next]}"]`,
              )?.focus();
            }}
            data-tab={t}
          >
            {t}
          </button>
        ))}
      </nav>
      {tab === "Explanation" && <Explanation e={e} blocks={currentLesson.blocks} />}
      {tab === "Flashcards" && (
        <Cards
          cards={currentLesson.flashcards}
          viewed={viewed}
          setViewed={setViewed}
        />
      )}
      {tab === "Quiz" && (
        <Quiz
          lesson={currentLesson}
          sessionId={sessionId}
          initial={initialAnswers}
          cards={viewed.size}
        />
      )}
    </article>
  );
}

function Explanation({ e, blocks }: { e: L["explanation"]; blocks: ContentBlock[] }) {
  return (
    <>
      <div className="list">
        {e.sections.map((s, i) => (
          <details key={s.title} className="row" open={i === 0}>
            <summary>
              <b>{i + 1}</b>
              <span>{s.title}</span>
            </summary>
            <p>{s.content}</p>
            {s.examples.map((x) => (
              <blockquote key={x}>{x}</blockquote>
            ))}
          </details>
        ))}
      </div>
      <div className="grid2">
        <section className="panel">
          <h3>Key takeaways</h3>
          <ul>
            {e.keyTakeaways.map((k) => (
              <li key={k}>{k}</li>
            ))}
          </ul>
        </section>
        {e.commonMistakes.length > 0 && (
          <section className="panel">
            <h3>Common mistakes</h3>
            <ul>
              {e.commonMistakes.map((k) => (
                <li key={k}>{k}</li>
              ))}
            </ul>
          </section>
        )}
      </div>
      {blocks.length > 0 && (
        <div className="content-blocks" aria-label="Study aids">
          {blocks.map((block, index) => (
            <BlockView key={`${block.kind}-${index}`} block={block} />
          ))}
        </div>
      )}
    </>
  );
}

function BlockView({ block }: { block: ContentBlock }) {
  if (block.kind === "card")
    return (
      <section className="content-block block-card">
        <span className="block-label">Key idea</span>
        <h3>{block.title}</h3>
        <p>{block.body}</p>
      </section>
    );
  if (block.kind === "checklist")
    return (
      <section className="content-block block-checklist">
        <span className="block-label">Checklist</span>
        <h3>{block.title}</h3>
        <ul>
          {block.items.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </section>
    );
  const maximum = Math.max(...block.values, 1);
  return (
    <section className="content-block block-chart">
      <span className="block-label">Chart</span>
      <h3>{block.title}</h3>
      <div className="chart-bars" role="img" aria-label={block.title}>
        {block.labels.map((label, index) => (
          <div className="chart-bar-item" key={label}>
            <div className="chart-bar-track">
              <span style={{ height: `${(block.values[index] / maximum) * 100}%` }} />
            </div>
            <small>{label}</small>
          </div>
        ))}
      </div>
    </section>
  );
}

function Cards({
  cards,
  viewed,
  setViewed,
}: {
  cards: L["flashcards"];
  viewed: Set<string>;
  setViewed: (s: Set<string>) => void;
}) {
  const [i, setI] = useState(0),
    [flip, setFlip] = useState(false);
  const c = cards[i];
  const go = (n: number) => {
    setFlip(false);
    setI(n);
  };
  const reveal = () => {
    setFlip(!flip);
    if (!flip) setViewed(new Set(viewed).add(c.id));
  };
  return (
    <div>
      <p className="meta">
        Card {i + 1} of {cards.length} · {viewed.size} revealed
      </p>
      <button
        className={`card ${flip ? "flip" : ""}`}
        onClick={reveal}
        aria-label={flip ? "Hide answer" : "Reveal answer"}
      >
        <small>{flip ? "Answer" : "Question"}</small>
        <span>{flip ? c.answer : c.question}</span>
        {!flip && <em>Tap to reveal</em>}
      </button>
      <div className="actions">
        <button
          className="btn ghost"
          disabled={i === 0}
          onClick={() => go(i - 1)}
        >
          Previous
        </button>
        <button
          className="btn"
          disabled={i === cards.length - 1}
          onClick={() => go(i + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}

function Quiz({
  lesson,
  sessionId,
  initial,
  cards,
}: {
  lesson: L;
  sessionId: string;
  initial?: Record<string, string>;
  cards: number;
}) {
  const q = lesson.quiz;
  const [i, setI] = useState(0);
  const [ans, setAns] = useState<Record<string, string>>(initial ?? {});
  const [finished, setFinished] = useState(
    !!initial && Object.keys(initial).length > 0,
  );
  const [save, setSave] = useState<"idle" | "saving" | "saved" | "error">(
    initial ? "saved" : "idle",
  );
  const correct = useMemo(
    () => q.filter((x) => ans[x.id] === x.correctAnswer).length,
    [ans, q],
  );
  const wrong = q.filter((x) => ans[x.id] !== x.correctAnswer);

  async function finish() {
    setFinished(true);
    setSave("saving");
    try {
      await completeSession(sessionId, {
        correct,
        incorrect: q.length - correct,
        total: q.length,
        cardsReviewed: cards,
        answers: ans,
      });
      setSave("saved");
    } catch {
      setSave("error");
    }
  }

  if (finished)
    return (
      <div>
        <section className="panel score">
          <h2>{Math.round((correct / q.length) * 100)}%</h2>
          <p>
            {correct} of {q.length} correct
          </p>
          {save === "saving" && <p className="meta">Saving progress…</p>}
          {save === "error" && (
            <p className="meta err">
              Progress not saved.{" "}
              <button className="link" onClick={finish}>
                Retry
              </button>
            </p>
          )}
          {save === "saved" && <p className="meta">Progress saved.</p>}
        </section>
        {wrong.length > 0 && <h3>Questions to review</h3>}
        {wrong.map((x) => (
          <section className="panel" key={x.id}>
            <b>{x.question}</b>
            <p>Your answer: {ans[x.id] ?? "not answered"}</p>
            <p>Correct answer: {x.correctAnswer}</p>
            <p className="meta">{x.explanation}</p>
          </section>
        ))}
      </div>
    );

  const cur = q[i],
    picked = ans[cur.id],
    done = picked !== undefined;
  return (
    <div>
      <p className="meta">
        Question {i + 1} of {q.length}
      </p>
      <h3 className="qtext">{cur.question}</h3>
      <div className="opts" role="radiogroup">
        {cur.options.map((o) => (
          <button
            key={o}
            role="radio"
            aria-checked={picked === o}
            disabled={done}
            className={`opt ${done && o === cur.correctAnswer ? "ok" : ""} ${done && picked === o && o !== cur.correctAnswer ? "no" : ""}`}
            onClick={() => setAns({ ...ans, [cur.id]: o })}
          >
            {o}
          </button>
        ))}
      </div>
      {done && (
        <p className="panel">
          <b>{picked === cur.correctAnswer ? "Correct." : "Not quite."}</b>{" "}
          {cur.explanation}
        </p>
      )}
      <div className="actions">
        {i < q.length - 1 ? (
          <button className="btn" disabled={!done} onClick={() => setI(i + 1)}>
            Next question
          </button>
        ) : (
          <button className="btn" disabled={!done} onClick={finish}>
            Finish session
          </button>
        )}
      </div>
    </div>
  );
}
