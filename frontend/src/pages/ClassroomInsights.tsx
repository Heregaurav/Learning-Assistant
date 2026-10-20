import { lazy, Suspense, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, ArrowRight, CheckCircle2, Clock3 } from "lucide-react";
import { CLASSROOM_PROGRESS_UPDATED, getClassroomAnalytics, getClassroomGraph, getClassroomProgress } from "../lib/api";
import type { Role } from "../types";

const ClassroomKnowledgeGraph = lazy(() => import("../components/ClassroomKnowledgeGraph"));

type Props = {
  classroomId: string;
  canEdit: boolean;
  user: { id: string; role?: Role };
};

type Progress = Awaited<ReturnType<typeof getClassroomProgress>>;
type Analytics = Awaited<ReturnType<typeof getClassroomAnalytics>>;
type Graph = Awaited<ReturnType<typeof getClassroomGraph>>;

export default function ClassroomInsights({ classroomId, canEdit, user }: Props) {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);
  const [graphStudentId, setGraphStudentId] = useState("");
  const [graphRevision, setGraphRevision] = useState(0);
  const [progressRevision, setProgressRevision] = useState(0);
  const [progressView, setProgressView] = useState<"modules" | "graph">("modules");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const load = async () => {
      try {
        if (canEdit) {
          const result = await getClassroomAnalytics(classroomId);
          if (cancelled) return;
          setAnalytics(result);
          setGraphStudentId((current) => current || result.students[0]?.studentId || "");
        } else {
          const result = await getClassroomProgress(classroomId);
          if (cancelled) return;
          setProgress(result);
          setGraphStudentId(user.id);
        }
      } catch (reason) {
        if (!cancelled) setError((reason as Error).message || "Unable to load learning analytics.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => { cancelled = true; };
  }, [classroomId, canEdit, user.id, progressRevision]);

  useEffect(() => {
    const refreshProgress = () => {
      setProgressRevision((revision) => revision + 1);
      setGraphRevision((revision) => revision + 1);
    };
    window.addEventListener(CLASSROOM_PROGRESS_UPDATED, refreshProgress);
    return () => window.removeEventListener(CLASSROOM_PROGRESS_UPDATED, refreshProgress);
  }, []);

  useEffect(() => {
    if (!graphStudentId) {
      setGraph(null);
      setGraphLoading(false);
      return;
    }
    let cancelled = false;
    setGraphLoading(true);
    getClassroomGraph(classroomId, canEdit ? graphStudentId : undefined)
      .then((result) => {
        if (!cancelled) {
          setGraph(result);
          setSelectedNodeId((current) => result.nodes.some((node) => node.id === current) ? current : result.nodes[0]?.id ?? "");
        }
      })
      .catch((reason) => {
        if (!cancelled) setError((reason as Error).message || "Unable to load the knowledge graph.");
      })
      .finally(() => {
        if (!cancelled) setGraphLoading(false);
      });
    return () => { cancelled = true; };
  }, [classroomId, graphStudentId, canEdit, graphRevision]);

  const selectedNode = graph?.nodes.find((node) => node.id === selectedNodeId);
  const edgesForSelected = graph?.edges.filter((edge) => edge.source === selectedNodeId || edge.target === selectedNodeId) ?? [];
  const weakTopics = progress?.learningPath.items.filter((item) =>
    item.status === "revision_needed" || item.status === "practice" || item.status === "locked",
  ) ?? [];
  const readyRevisionCount = progress?.revisionTasks.filter((task) => task.generationStatus === "ready" && task.revisionContent).length ?? 0;
  return (
    <section className="mt-8 border border-primary/20 bg-black/90 p-5 md:p-7">
      {progressView === "modules" && <>
        <p className="text-xs uppercase tracking-[0.18em] text-primary/70">Learning evidence</p>
        <h2 className="mt-1 text-xl font-semibold">{canEdit ? "Class analytics" : "My progress"}</h2>
      </>}
      {error && <p role="alert" className="mt-4 rounded-lg border border-red-400/40 bg-red-950/40 p-3 text-sm text-red-100">{error}</p>}
      <div className="mt-5 flex w-fit max-w-full border-b border-primary/20" role="tablist" aria-label="Progress views">
        <button type="button" role="tab" aria-selected={progressView === "modules"} onClick={() => setProgressView("modules")} className={`border-b-2 px-4 py-3 text-sm transition-colors ${progressView === "modules" ? "border-primary text-primary" : "border-transparent text-primary/60 hover:text-primary/85"}`}>
          {canEdit ? "Class analytics" : "Module progress"}
        </button>
        <button type="button" role="tab" aria-selected={progressView === "graph"} onClick={() => setProgressView("graph")} className={`border-b-2 px-4 py-3 text-sm transition-colors ${progressView === "graph" ? "border-primary text-primary" : "border-transparent text-primary/60 hover:text-primary/85"}`}>
          Learning graph
        </button>
      </div>
      {loading ? <p className="py-6 text-sm text-primary/70">{progressView === "graph" ? "Loading learning graph…" : "Calculating progress from recorded evidence…"}</p> : canEdit ? (progressView === "modules" ? (
        analytics && <>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <Metric label="Enrolled students" value={analytics.enrolledStudents} />
            <Metric label="Students with evidence" value={analytics.studentsWithEvidence} />
            <Metric label="Average mastery" value={analytics.averageMastery === null ? "Unknown" : `${analytics.averageMastery}%`} />
          </div>
          <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_1fr]">
            <div>
              <h3 className="text-sm font-medium">Student profiles</h3>
              {analytics.students.length === 0 ? <p className="mt-3 text-sm text-primary/70">No students have joined this classroom.</p> : (
                <div className="mt-2 divide-y divide-primary/15 border-y border-primary/15">
                  {analytics.students.map((student) => (
                    <button key={student.studentId} onClick={() => setGraphStudentId(student.studentId)} className={`grid w-full grid-cols-[1fr_auto] gap-2 py-3 text-left hover:bg-white/5 ${graphStudentId === student.studentId ? "text-primary" : ""}`}>
                      <span className="truncate text-sm">{student.name}</span>
                      <span className="text-xs">{student.mastery.score === null ? "No evidence" : `${student.mastery.score}% ${student.mastery.state}`} · {student.coverage.percent}% coverage{student.attention ? " · Needs attention" : ""}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div>
              <h3 className="text-sm font-medium">Topic performance</h3>
              {analytics.topics.length === 0 ? <p className="mt-3 text-sm text-primary/70">No assessment evidence yet.</p> : (
                <ul className="mt-2 divide-y divide-primary/15 border-y border-primary/15">
                  {analytics.topics.map((topic) => <li key={topic.topicId} className="flex justify-between gap-3 py-3 text-sm"><span>{topic.title}</span><span>{topic.averageMastery}% · {topic.evidenceCount} evidence</span></li>)}
                </ul>
              )}
            </div>
          </div>
        </>
      ) : null) : progress && progressView === "modules" && <>
        <div className="mt-5 grid gap-5 border-y border-primary/20 py-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <div>
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <div>
                <p className="text-[10px] uppercase tracking-[0.16em] text-primary/65">Curriculum progress</p>
                <p className="mt-1 text-2xl font-semibold text-[#f2efe8]">{progress.learningPath.progress.percent}% <span className="text-sm font-normal text-[#c9c4b5]">complete</span></p>
              </div>
              <p className="text-sm text-[#c9c4b5]">{progress.learningPath.progress.completed} of {progress.learningPath.progress.total} topics mastered</p>
            </div>
            <div className="mt-3 h-2 overflow-hidden bg-white/10" role="progressbar" aria-label="Curriculum completion" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.learningPath.progress.percent}>
              <div className="h-full bg-primary transition-[width] duration-500" style={{ width: `${progress.learningPath.progress.percent}%` }} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-x-8 gap-y-3 border-l border-primary/15 pl-4 sm:grid-cols-3 lg:min-w-[390px]">
            <MiniMetric label="Mastery" value={progress.mastery.score === null ? "—" : `${progress.mastery.score}%`} />
            <MiniMetric label="Topics studied" value={`${progress.coverage.coveredTopics}/${progress.coverage.totalTopics}`} />
            <MiniMetric label="Ready revisions" value={readyRevisionCount} />
          </div>
        </div>
        <section className="mt-6 border-t border-primary/20 pt-5" aria-labelledby="module-progress-heading">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[10px] uppercase tracking-[0.16em] text-primary/65">Course breakdown</p>
              <h3 id="module-progress-heading" className="mt-1 text-lg font-semibold">Progress by module</h3>
            </div>
            <p className="text-xs text-primary/65">Mastery is counted only with sufficient assessment evidence</p>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {progress.modules.map((module) => {
              const mastered = module.topics.filter((topic) =>
                progress.learningPath.items.find((item) => item.topicId === topic.id)?.status === "completed",
              ).length;
              const total = module.topics.length;
              const percent = total ? Math.round(mastered / total * 100) : 0;
              const studied = module.topics.filter((topic) => topic.coverage === "covered").length;
              return <article key={module.id} className="border-t border-primary/25 pt-4">
                <div className="flex items-start justify-between gap-3">
                  <h4 className="min-w-0 font-medium text-[#f2efe8]">{module.title}</h4>
                  <span className="shrink-0 text-xs text-primary/75">{mastered}/{total} mastered</span>
                </div>
                <div className="mt-3 h-2.5 overflow-hidden bg-white/10" role="progressbar" aria-label={`${module.title} mastery progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
                  <div className="h-full bg-primary transition-[width] duration-500" style={{ width: `${percent}%` }} />
                </div>
                <p className="mt-2 text-[11px] text-[#b9b4a7]">{studied} of {total} topics studied · {percent}% mastery completion</p>
                <ul className="mt-3 divide-y divide-primary/10 border-y border-primary/10">
                  {module.topics.map((topic) => {
                    const pathItem = progress.learningPath.items.find((item) => item.topicId === topic.id);
                    const statusLabel = pathItem?.status === "revision_needed" ? "Revise" : pathItem?.status === "practice" ? "Practice" : pathItem?.status === "locked" ? "Locked" : pathItem?.status === "completed" ? "Mastered" : "Available";
                    const statusTone = pathItem?.status === "revision_needed" ? "text-amber-100" : pathItem?.status === "locked" ? "text-slate-300" : pathItem?.status === "completed" ? "text-emerald-200" : "text-primary/75";
                    return <li key={topic.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2.5 text-sm">
                      <Link className="min-w-0 flex-1 text-primary hover:underline" to={`/?classroomId=${encodeURIComponent(classroomId)}&topicId=${encodeURIComponent(topic.id)}`}>{topic.title}</Link>
                      <span className="flex shrink-0 items-center gap-3 text-[11px]">
                        <span className="text-[#c9c4b5]">{topic.coverage === "covered" ? "Studied" : "Not started"}</span>
                        <span className={statusTone}>{statusLabel}</span>
                        <span className="min-w-14 text-right text-primary/70">{topic.mastery.score === null ? "No score" : `${topic.mastery.score}%`}</span>
                      </span>
                    </li>;
                  })}
                </ul>
              </article>;
            })}
          </div>
        </section>
        <section className="mt-6 border-t border-primary/20 pt-5" aria-labelledby="weak-topics-heading">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[10px] uppercase tracking-[0.16em] text-amber-200/75">Your next focus</p>
              <h3 id="weak-topics-heading" className="mt-1 text-lg font-semibold">Topics needing attention</h3>
            </div>
            <span className="text-xs text-primary/65">{weakTopics.length} topics</span>
          </div>
          {weakTopics.length === 0 ? (
            <div className="mt-3 flex items-center gap-2 border-y border-emerald-300/20 py-4 text-sm text-emerald-100/85">
              <CheckCircle2 size={17} /> No topics currently need revision. Keep building evidence through practice.
            </div>
          ) : (
            <ul className="mt-3 divide-y divide-primary/15 border-y border-primary/15">
              {weakTopics.map((item) => {
                const task = progress.revisionTasks.find((candidate) => candidate.topicId === item.topicId && candidate.status !== "mastered");
                const locked = item.status === "locked";
                return <li key={item.topicId} className="grid gap-3 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className="font-medium text-[#f2efe8]">{item.title}</h4>
                      <span className={`inline-flex items-center gap-1 border px-2 py-0.5 text-[10px] uppercase tracking-wide ${locked ? "border-slate-400/25 text-slate-300" : "border-amber-300/30 text-amber-100"}`}>
                        {locked ? <Clock3 size={11} /> : <AlertTriangle size={11} />}
                        {locked ? "Locked" : item.status === "practice" ? "More evidence needed" : "Revision needed"}
                      </span>
                    </div>
                    <p className="mt-1 text-sm leading-relaxed text-[#c9c4b5]">{item.reason}</p>
                    <p className="mt-1 text-xs text-primary/65">
                      {item.mastery.score === null ? "Mastery not established" : `Latest topic score ${item.mastery.score}%`}
                      {task?.conceptIds.length ? ` · Focus: ${task.conceptIds.join(", ")}` : ""}
                    </p>
                  </div>
                  {!locked && <Link to={`/?classroomId=${encodeURIComponent(classroomId)}&topicId=${encodeURIComponent(item.topicId)}`} className="inline-flex min-h-10 items-center justify-center gap-2 border border-primary/35 px-3 text-sm text-primary hover:bg-primary/10">Open topic<ArrowRight size={14} /></Link>}
                </li>;
              })}
            </ul>
          )}
        </section>

      </>}

      {!loading && progressView === "graph" && (canEdit ? analytics : progress) && <section className="mt-5" aria-labelledby="learning-graph-heading">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><p className="text-[10px] uppercase tracking-[0.16em] text-primary/65">Curriculum relationships and evidence</p><h3 id="learning-graph-heading" className="mt-1 text-xl font-semibold">Learning graph</h3><p className="mt-1 text-sm text-[#c9c4b5]">Explore how studied topics, concepts, prerequisites, and evidence connect.</p></div>
          {canEdit && analytics && <label className="flex items-center gap-2 text-xs text-primary/75">Student<select value={graphStudentId} onChange={(event) => setGraphStudentId(event.target.value)} className="max-w-[220px] rounded-md border border-primary/25 bg-black/40 px-2 py-2 text-sm text-[#E1E0CC]">{analytics.students.map((student) => <option key={student.studentId} value={student.studentId}>{student.name}</option>)}</select></label>}
        </div>
        {graphLoading && (!graph || graph.nodes.length === 0) ? <p className="py-5 text-sm text-primary/70">Loading the knowledge graph…</p> : !graph || graph.nodes.length === 0 ? <p className="py-5 text-sm text-primary/70">Completed or mastered topics will appear here as students progress through the curriculum.</p> : (
          <>
          {graphLoading && <p aria-live="polite" className="mb-2 text-xs text-primary/55">Updating graph…</p>}
          <Suspense fallback={<p className="py-4 text-sm text-primary/70">Loading 3D graph…</p>}>
            <ClassroomKnowledgeGraph graph={graph} selectedNodeId={selectedNodeId} onSelect={setSelectedNodeId} />
          </Suspense>
          <div className="mt-3 grid gap-4 md:grid-cols-[1fr_280px]">
            <ul className="hidden gap-2 md:grid md:grid-cols-2">
              {graph.nodes.map((node) => <li key={node.id}><button onClick={() => setSelectedNodeId(node.id)} className={`w-full border-l-2 px-3 py-3 text-left ${selectedNodeId === node.id ? "border-primary bg-primary/10" : "border-primary/25 bg-black/20"}`}><span className="block text-[10px] uppercase tracking-wide text-primary/65">{node.kind} · {node.started && !node.completed ? "started" : node.coverage}</span><span className="mt-1 block text-sm">{node.label}</span><span className="mt-1 block text-xs text-primary/75">{node.mastery.score === null ? (node.started ? "Started · no assessment evidence" : "No assessment evidence") : `${node.mastery.score}% · ${node.mastery.state} · ${node.mastery.confidence} confidence`}</span></button></li>)}
            </ul>
            <aside className="border-t border-primary/20 pt-3 md:border-l md:border-t-0 md:pl-4">
              {selectedNode ? <><p className="text-xs uppercase text-primary/65">Selected {selectedNode.kind}</p><h4 className="mt-1 font-medium">{selectedNode.label}</h4><p className="mt-1 text-xs text-primary/65">{selectedNode.moduleName}</p><p className="mt-2 text-sm text-[#D7D1B5]">{selectedNode.completed ? "Completed" : selectedNode.started ? "Started" : "Not started"} · {selectedNode.mastered ? "Mastered" : selectedNode.mastery.score === null ? "No assessment evidence" : `${selectedNode.mastery.score}% · ${selectedNode.mastery.state}`}</p><p className="mt-1 text-xs text-primary/60">Supporting evidence: {selectedNode.mastery.evidenceCount}</p><ul className="mt-2 grid gap-1 text-xs text-primary/70">{selectedNode.mastery.evidenceIds.map((id) => <li key={id}>{id}</li>)}</ul><p className="mt-3 text-xs text-primary/70">Relationships: {edgesForSelected.map((edge) => `${edge.kind} (${edge.source} → ${edge.target})`).join("; ") || "None"}</p></> : <p className="text-sm text-primary/70">Select a node to inspect its evidence.</p>}
            </aside>
          </div>
          </>
        )}
      </section>}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="border-l-2 border-primary/40 py-2 pl-3"><p className="text-xs uppercase tracking-wide text-primary/65">{label}</p><p className="mt-1 text-xl font-semibold">{value}</p></div>;
}

function MiniMetric({ label, value }: { label: string; value: string | number }) {
  return <div><p className="text-[10px] uppercase tracking-wide text-primary/60">{label}</p><p className="mt-1 text-sm font-semibold text-[#f2efe8]">{value}</p></div>;
}
