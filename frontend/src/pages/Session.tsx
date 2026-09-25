import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getSession } from "../lib/api";
import { validateLesson } from "../lib/validate";
import Lesson from "../components/Lesson";
import { ErrorState, LoadingState } from "../components/States";

export default function Session() {
  const { id = "" } = useParams();
  const [s, setS] = useState<any>(null),
    [err, setErr] = useState("");
  const load = () => {
    setErr("");
    setS(null);
    getSession(id)
      .then(setS)
      .catch((e) => setErr(e.message));
  };
  useEffect(load, [id]);
  if (err) return <ErrorState message={err} onRetry={load} />;
  if (!s) return <LoadingState />;
  const lesson = validateLesson(s.learningContent);
  if (!lesson)
    return (
      <ErrorState message="This saved session has an unexpected format." />
    );
  return (
    <Lesson
      lesson={lesson}
      sessionId={s.id}
      initialAnswers={s.evaluation?.completed ? s.answers : undefined}
    />
  );
}
