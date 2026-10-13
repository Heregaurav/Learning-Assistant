import { lazy, Suspense, useEffect, useState } from "react";
import { Link } from "react-router-dom";
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
  }, [classroomId, canEdit, user.id]);

  useEffect(() => {
    const refreshGraph = () => setGraphRevision((revision) => revision + 1);
    window.addEventListener(CLASSROOM_PROGRESS_UPDATED, refreshGraph);
    return () => window.removeEventListener(CLASSROOM_PROGRESS_UPDATED, refreshGraph);
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

  return (
    <section className="mt-8 rounded-2xl border border-primary/20 bg-black/90 p-5 md:p-7">
      <p className="text-xs uppercase tracking-[0.18em] text-primary/70">Learning evidence</p>
      <h2 className="mt-1 text-xl font-semibold">{canEdit ? "Class analytics" : "My progress"}</h2>
      {error && <p role="alert" className="mt-4 rounded-lg border border-red-400/40 bg-red-950/40 p-3 text-sm text-red-100">{error}</p>}
      {loading ? <p className="py-6 text-sm text-primary/70">Calculating progress from recorded evidence…</p> : canEdit ? (
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
      ) : progress && <>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <Metric label="Course mastery" value={progress.mastery.score === null ? "Unknown" : `${progress.mastery.score}% · ${progress.mastery.state}`} />
          <Metric label="Curriculum coverage" value={`${progress.coverage.percent}% · ${progress.coverage.coveredTopics}/${progress.coverage.totalTopics} topics`} />
        </div>
        {progress.recommendations.length > 0 && <div className="mt-5"><h3 className="text-sm font-medium">Recommended next steps</h3><ul className="mt-2 grid gap-2 sm:grid-cols-2">{progress.recommendations.map((item) => <li key={`${item.kind}-${item.topicId}`}><Link className="text-sm text-primary hover:underline" to={`/?classroomId=${encodeURIComponent(classroomId)}&topicId=${encodeURIComponent(item.topicId)}`}>{item.title} →</Link></li>)}</ul></div>}
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          {progress.modules.map((module) => <article key={module.id} className="border-t border-primary/20 pt-3"><h3 className="font-medium">{module.title}</h3><ul className="mt-2 grid gap-2">{module.topics.map((topic) => <li key={topic.id} className="flex justify-between gap-3 text-sm"><Link className="text-primary hover:underline" to={`/?classroomId=${encodeURIComponent(classroomId)}&topicId=${encodeURIComponent(topic.id)}`}>{topic.title}</Link><span className="text-xs text-primary/70">{topic.coverage} · {topic.mastery.score === null ? "Unknown" : `${topic.mastery.score}% ${topic.mastery.state}`}</span></li>)}</ul></article>)}
        </div>
      </>}

      <div className="mt-8 border-t border-primary/15 pt-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><p className="text-xs uppercase tracking-[0.15em] text-primary/65">Curriculum relationships and evidence</p><h3 className="mt-1 text-lg font-medium">Knowledge graph</h3></div>
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
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="border-l-2 border-primary/40 py-2 pl-3"><p className="text-xs uppercase tracking-wide text-primary/65">{label}</p><p className="mt-1 text-xl font-semibold">{value}</p></div>;
}
