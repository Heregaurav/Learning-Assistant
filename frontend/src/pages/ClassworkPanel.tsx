import { FormEvent, useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import {
  createClassroomAssessment,
  evaluateClassroomSubmission,
  getClassroomAssessments,
  getClassroomSubmissions,
  gradeClassroomSubmission,
  submitClassroomAssessment,
} from "../lib/api";
import type { ClassroomAssessment, ClassroomSubmission } from "../types";

type Props = {
  classroomId: string;
  canEdit: boolean;
};

const emptySubmissionMap: Record<string, ClassroomSubmission[]> = {};

export default function ClassworkPanel({ classroomId, canEdit }: Props) {
  const [assessments, setAssessments] = useState<ClassroomAssessment[]>([]);
  const [submissions, setSubmissions] = useState(emptySubmissionMap);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<ClassroomAssessment["kind"]>("assignment");
  const [instructions, setInstructions] = useState("");
  const [maxMarks, setMaxMarks] = useState(100);
  const [rubric, setRubric] = useState("");
  const [expectedAnswer, setExpectedAnswer] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [published, setPublished] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [showCreateForm, setShowCreateForm] = useState(false);

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const rows = await getClassroomAssessments(classroomId);
      setAssessments(rows);
      const pairs = await Promise.all(
        rows.map(async (assessment) => [
          assessment.id,
          await getClassroomSubmissions(classroomId, assessment.id),
        ] as const),
      );
      setSubmissions(Object.fromEntries(pairs));
    } catch (reason) {
      setError((reason as Error).message || "Unable to load classwork.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, [classroomId]);

  const createAssessment = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      await createClassroomAssessment(classroomId, {
        title: title.trim(),
        kind,
        instructions: instructions.trim(),
        topicId: null,
        conceptIds: [],
        dueAt: dueAt ? new Date(dueAt).toISOString() : null,
        maxMarks,
        rubric: rubric.trim(),
        expectedAnswer: expectedAnswer.trim(),
        published,
      });
      setTitle("");
      setInstructions("");
      setRubric("");
      setExpectedAnswer("");
      setDueAt("");
      setPublished(false);
      setShowCreateForm(false);
      setNotice("Classwork saved.");
      await refresh();
    } catch (reason) {
      setError((reason as Error).message || "Unable to save classwork.");
    }
  };

  const submitAnswer = async (assessmentId: string) => {
    setError("");
    setNotice("");
    try {
      await submitClassroomAssessment(classroomId, assessmentId, answers[assessmentId] ?? "");
      setNotice("Your submission was saved.");
      await refresh();
    } catch (reason) {
      setError((reason as Error).message || "Unable to submit this work.");
    }
  };

  const saveGrade = async (
    assessmentId: string,
    submission: ClassroomSubmission,
    score: number,
    feedback: string,
    release: boolean,
  ) => {
    setError("");
    try {
      await gradeClassroomSubmission(classroomId, assessmentId, submission.id, { score, feedback, release });
      setNotice(release ? "Grade and feedback released." : "Grade saved privately.");
      await refresh();
    } catch (reason) {
      setError((reason as Error).message || "Unable to save grade.");
    }
  };

  const evaluateSubmission = async (assessmentId: string, submissionId: string) => {
    setError("");
    setNotice("");
    try {
      await evaluateClassroomSubmission(classroomId, assessmentId, submissionId);
      setNotice("AI evaluation saved as a faculty review draft.");
      await refresh();
    } catch (reason) {
      setError((reason as Error).message || "AI evaluation failed. The original submission is unchanged.");
    }
  };

  return (
    <section className="mt-12 border-t border-primary/20 pt-7">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-primary/70">Assessments</p>
          <h2 className="mt-1 text-xl font-semibold">Classwork</h2>
        </div>
        <span className="text-xs text-primary/70">{assessments.length} items</span>
      </div>
      {error && <p role="alert" className="mt-4 rounded-lg border border-red-400/40 bg-red-950/40 p-3 text-sm text-red-100">{error}</p>}
      {notice && <p role="status" className="mt-4 text-sm text-emerald-200">{notice}</p>}

      {canEdit && (
        <div className="mt-5 border-b border-primary/20 pb-6">
          {!showCreateForm ? (
            <button
              type="button"
              onClick={() => setShowCreateForm(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-black"
            >
              <Plus size={17} /> Create assignment
            </button>
          ) : (
            <form onSubmit={createAssessment} className="grid gap-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-medium">Create assignment</h3>
                <button
                  type="button"
                  onClick={() => setShowCreateForm(false)}
                  className="rounded-md p-2 text-primary/80 hover:bg-primary/10 hover:text-primary"
                  aria-label="Close create assignment form"
                  title="Close"
                >
                  <X size={18} />
                </button>
              </div>
          <div className="grid gap-3 md:grid-cols-2">
            <input required value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Title" className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
            <select value={kind} onChange={(event) => setKind(event.target.value as ClassroomAssessment["kind"])} className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm">
              <option value="assignment">Assignment</option><option value="quiz">Quiz</option><option value="test">Test</option><option value="practice">Practice</option><option value="curiosity">Curiosity activity</option>
            </select>
            <textarea value={instructions} onChange={(event) => setInstructions(event.target.value)} placeholder="Instructions" className="min-h-20 rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
            <textarea value={rubric} onChange={(event) => setRubric(event.target.value)} placeholder="Rubric or grading guidance" className="min-h-20 rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
            <textarea value={expectedAnswer} onChange={(event) => setExpectedAnswer(event.target.value)} placeholder="Expected answer (private to faculty)" className="min-h-20 rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-1 text-xs text-primary/75">Maximum marks<input type="number" min="1" max="10000" required value={maxMarks} onChange={(event) => setMaxMarks(Number(event.target.value))} className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#E1E0CC]" /></label>
              <label className="grid gap-1 text-xs text-primary/75">Due date<input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#E1E0CC]" /></label>
            </div>
          </div>
              <button
                type="button"
                role="switch"
                aria-checked={published}
                onClick={() => setPublished((current) => !current)}
                className={`flex w-fit items-center gap-3 rounded-lg border px-3 py-2 text-sm ${published ? "border-emerald-300/60 bg-emerald-300/10 text-emerald-100" : "border-primary/25 text-[#D7D1B5]"}`}
              >
                <span className={`h-4 w-7 rounded-full p-0.5 transition-colors ${published ? "bg-emerald-300" : "bg-primary/30"}`}>
                  <span className={`block h-3 w-3 rounded-full bg-black transition-transform ${published ? "translate-x-3" : "translate-x-0"}`} />
                </span>
                {published ? "Published for students" : "Save as draft"}
              </button>
              <button className="inline-flex w-fit items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-black">
                <Plus size={16} /> {published ? "Create and publish" : "Save draft"}
              </button>
            </form>
          )}
        </div>
      )}

      {loading ? <p className="py-6 text-sm text-primary/70">Loading classwork…</p> : assessments.length === 0 ? (
        <p className="py-6 text-sm text-primary/70">No classwork has been published.</p>
      ) : (
        <div className="divide-y divide-primary/15">
          {assessments.map((assessment) => (
            <article key={assessment.id} className="py-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-wide text-primary/70">{assessment.kind} · {assessment.maxMarks} marks · {assessment.published ? "Published" : "Draft"}</p>
                  <h3 className="mt-1 text-lg font-medium">{assessment.title}</h3>
                  {assessment.instructions && <p className="mt-2 whitespace-pre-wrap text-sm text-[#D7D1B5]">{assessment.instructions}</p>}
                  {assessment.dueAt && <p className="mt-2 text-xs text-primary/70">Due {new Date(assessment.dueAt).toLocaleString()}</p>}
                </div>
              </div>
              {!canEdit && assessment.published && (
                <StudentSubmission
                  answer={answers[assessment.id] ?? ""}
                  onAnswer={(value) => setAnswers((current) => ({ ...current, [assessment.id]: value }))}
                  submission={submissions[assessment.id]?.[0]}
                  onSubmit={() => void submitAnswer(assessment.id)}
                />
              )}
              {canEdit && (submissions[assessment.id] ?? []).map((submission) => (
                <FacultySubmission
                  key={submission.id}
                  submission={submission}
                  maxMarks={assessment.maxMarks}
                  onGrade={(score, feedback, release) => void saveGrade(assessment.id, submission, score, feedback, release)}
                  onEvaluate={() => void evaluateSubmission(assessment.id, submission.id)}
                />
              ))}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function StudentSubmission({
  answer,
  onAnswer,
  submission,
  onSubmit,
}: {
  answer: string;
  onAnswer: (value: string) => void;
  submission?: ClassroomSubmission;
  onSubmit: () => void;
}) {
  if (submission) {
    return (
      <div className="mt-4 border-l-2 border-primary/30 pl-3 text-sm">
        <p>Submission: {submission.status}</p>
        {submission.released && <p className="mt-1">Score: {submission.score} · {submission.feedback}</p>}
      </div>
    );
  }
  return (
    <div className="mt-4 grid gap-2">
      <textarea value={answer} onChange={(event) => onAnswer(event.target.value)} placeholder="Write your response" className="min-h-24 rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
      <button onClick={onSubmit} disabled={!answer.trim()} className="justify-self-start rounded-lg bg-primary px-4 py-2 text-sm font-medium text-black disabled:opacity-50">Submit work</button>
    </div>
  );
}

function FacultySubmission({
  submission,
  maxMarks,
  onGrade,
  onEvaluate,
}: {
  submission: ClassroomSubmission;
  maxMarks: number;
  onGrade: (score: number, feedback: string, release: boolean) => void;
  onEvaluate: () => void;
}) {
  const [score, setScore] = useState(submission.score ?? 0);
  const [feedback, setFeedback] = useState(submission.feedback ?? "");
  const [release, setRelease] = useState(Boolean(submission.released));
  return (
    <div className="mt-4 grid gap-2 border-l-2 border-primary/30 pl-3">
      <p className="text-xs text-primary/70">Student {submission.studentId} · {submission.status}</p>
      <p className="whitespace-pre-wrap text-sm text-[#D7D1B5]">{submission.answer}</p>
      {submission.aiEvaluation && (
        <div className="rounded-md border border-primary/20 bg-black/25 p-3 text-sm">
          <p className="font-medium">AI review draft · {submission.aiEvaluation.score}/{maxMarks}</p>
          <p className="mt-1 text-[#D7D1B5]">{submission.aiEvaluation.feedback}</p>
          <p className="mt-2 text-xs text-primary/75">Concept scores: {Object.entries(submission.aiEvaluation.conceptScores).map(([name, score]) => `${name} ${score}%`).join(" · ") || "No concept scores"}</p>
          {submission.aiEvaluation.misconceptions.length > 0 && <p className="mt-1 text-xs text-amber-200">Review: {submission.aiEvaluation.misconceptions.join("; ")}</p>}
        </div>
      )}
      <button onClick={onEvaluate} className="justify-self-start rounded-lg border border-primary/30 px-3 py-2 text-xs text-primary">Evaluate with AI</button>
      <div className="grid gap-2 sm:grid-cols-[120px_1fr_auto] sm:items-end">
        <label className="grid gap-1 text-xs text-primary/75">Score / {maxMarks}<input type="number" min="0" max={maxMarks} value={score} onChange={(event) => setScore(Number(event.target.value))} className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#E1E0CC]" /></label>
        <textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="Feedback" className="min-h-16 rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={release} onChange={(event) => setRelease(event.target.checked)} /> Release</label>
      </div>
      <button onClick={() => onGrade(score, feedback, release)} className="justify-self-start rounded-lg border border-primary/30 px-3 py-2 text-xs text-primary">Save grade</button>
    </div>
  );
}
