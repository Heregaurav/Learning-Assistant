import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getSessions, retestTopic } from "../lib/api";
import { EmptyState, ErrorState, LoadingState } from "../components/States";

export default function History() {
  const [rows, setRows] = useState<any[] | null>(null),
    [err, setErr] = useState(""),
    [q, setQ] = useState(""),
    [retesting, setRetesting] = useState<string | null>(null);
  const navigate = useNavigate();
  const isGuest = localStorage.getItem("curiosity.guest-id") !== null;
  const load = () => {
    setErr("");
    setRows(null);
    getSessions()
      .then(setRows)
      .catch((e) => {
        if (isGuest) {
          setRows([]);
        } else {
          setErr(e.message);
        }
      });
  };
  useEffect(load, []);
  const startRetest = async (topicId: string) => {
    setRetesting(topicId);
    try {
      const result = await retestTopic(topicId);
      navigate(`/session/${result.sessionId}`);
    } catch (e) {
      if ((e as { code?: string }).code === "retest_limit") {
        load();
      } else {
        setErr((e as Error).message);
      }
    } finally {
      setRetesting(null);
    }
  };
  if (err) return <ErrorState message={err} onRetry={load} />;
  if (!rows) return <LoadingState />;
  const shown = rows.filter((r) =>
    r.topic.toLowerCase().includes(q.toLowerCase()),
  );
  return (
    <>
      <header className="hero intro">
        <h1>Study history</h1>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search topics"
          aria-label="Search topics"
        />
      </header>
      {rows.length === 0 ? (
        <EmptyState
          title="No study sessions yet."
          hint="Start learning to build your history."
        />
      ) : (
        <div className="list">
          {shown.map((r) => (
            <div key={r.id} className="history-row">
              <Link to={`/session/${r.id}`} className="row link">
                <span>
                  <b>{r.topic}</b>
                  <small>
                    {new Date(r.createdAt).toLocaleDateString()} · {r.difficulty}
                  </small>
                </span>
                <span className="score-pill">
                  {r.evaluation?.completed
                    ? `${r.evaluation.score}%`
                    : "Not finished"}
                </span>
              </Link>
              <button
                className="retest-btn history-retest"
                onClick={() => startRetest(r.topicId)}
                disabled={retesting === r.topicId || r.retestsUsed >= 3}
              >
                {retesting === r.topicId
                  ? "Generating..."
                  : r.retestsUsed >= 3
                    ? "Retests used"
                    : "Retest"}
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
