import { useMemo, useState } from "react";
import type { Lesson as L } from "../types";
import { completeSession } from "../lib/api";

type Props = {
  lesson: L;
  sessionId: string;
  initialAnswers?: Record<string, string>;
};
const TABS = ["Explanation", "Flashcards", "Quiz"] as const;

export default function Lesson({ lesson, sessionId, initialAnswers }: Props) {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Explanation");
  const [viewed, setViewed] = useState<Set<string>>(new Set());
  const e = lesson.explanation;
  return (
    <article>
      <header className="hero">
        <h1>{lesson.topic}</h1>
        <div className="chips">
          {e.sections.map((s) => (
            <span key={s.title} className="chip">
              {s.title}
            </span>
          ))}
        </div>
        <p className="lead">{e.overview}</p>
      </header>
      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </nav>
      {tab === "Explanation" && <Explanation e={e} />}
      {tab === "Flashcards" && (
        <Cards
          cards={lesson.flashcards}
          viewed={viewed}
          setViewed={setViewed}
        />
      )}
      {tab === "Quiz" && (
        <Quiz
          lesson={lesson}
          sessionId={sessionId}
          initial={initialAnswers}
          cards={viewed.size}
        />
      )}
    </article>
  );
}

function Explanation({ e }: { e: L["explanation"] }) {
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
    </>
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
