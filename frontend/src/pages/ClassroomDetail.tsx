import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, BookOpen, Plus, Trash2 } from "lucide-react";
import {
  createCurriculumModule,
  createCurriculumTopic,
  deleteClassroom,
  getClassroomCurriculum,
  getClassroomProgress,
} from "../lib/api";
import ClassworkPanel from "./ClassworkPanel";
import ClassroomInsights from "./ClassroomInsights";
import ClassroomStream from "./ClassroomStream";
import Learn from "./Learn";
import type { ClassroomCurriculum, ClassroomProgress, Role } from "../types";

type Props = {
  user: { id: string; role?: Role } | null;
};

export default function ClassroomDetail({ user }: Props) {
  const { classroomId = "" } = useParams();
  const [data, setData] = useState<ClassroomCurriculum | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [moduleTitle, setModuleTitle] = useState("");
  const [moduleDescription, setModuleDescription] = useState("");
  const [activeModuleId, setActiveModuleId] = useState("");
  const [topicTitle, setTopicTitle] = useState("");
  const [topicDescription, setTopicDescription] = useState("");
  const [objectives, setObjectives] = useState("");
  const [concepts, setConcepts] = useState("");
  const [teacherNotes, setTeacherNotes] = useState("");
  const [materialUrl, setMaterialUrl] = useState("");
  const [activeTab, setActiveTab] = useState("learn");
  const [progress, setProgress] = useState<ClassroomProgress | null>(null);
  const [selectedTopicId, setSelectedTopicId] = useState("");

  const canEdit = Boolean(
    user &&
      (user.role === "ADMIN" || data?.classroom.ownerId === user.id),
  );
  const canDelete = Boolean(user && data?.classroom.ownerId === user.id);
  const tabs = canEdit
    ? [
        { id: "learn", label: "Learn" },
        { id: "overview", label: "Overview" },
        { id: "curriculum", label: "Curriculum" },
        { id: "classwork", label: "Classwork" },
        { id: "stream", label: "Stream" },
        { id: "people", label: "People" },
        { id: "analytics", label: "Analytics" },
      ]
    : [
        { id: "learn", label: "Learn" },
        { id: "classwork", label: "Classwork" },
        { id: "stream", label: "Stream" },
        { id: "people", label: "People" },
        { id: "progress", label: "My progress" },
      ];

  useEffect(() => {
    setActiveTab(canEdit ? "overview" : "learn");
  }, [canEdit]);

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      setData(await getClassroomCurriculum(classroomId));
    } catch (reason) {
      setError((reason as Error).message || "Unable to load this classroom.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, [classroomId]);

  useEffect(() => {
    if (!user) {
      setProgress(null);
      return;
    }
    getClassroomProgress(classroomId)
      .then((nextProgress) => {
        setProgress(nextProgress);
        setSelectedTopicId((current) => current || nextProgress.learningPath.recommendation?.topicId || "");
      })
      .catch(() => setProgress(null));
  }, [classroomId, user?.id, canEdit]);

  const submitModule = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      const module = await createCurriculumModule(classroomId, {
        title: moduleTitle.trim(),
        description: moduleDescription.trim(),
        position: data?.modules.length ?? 0,
      });
      setModuleTitle("");
      setModuleDescription("");
      setActiveModuleId(module.id);
      setNotice("Module added to this classroom.");
      await refresh();
    } catch (reason) {
      setError((reason as Error).message || "Unable to create module.");
    }
  };

  const submitTopic = async (event: FormEvent, moduleId: string) => {
    event.preventDefault();
    setError("");
    setNotice("");
    const conceptItems = concepts
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [name, ...description] = line.split("|");
        return { name: name.trim(), description: description.join("|").trim(), prerequisites: [] };
      });
    const materials = [];
    if (teacherNotes.trim()) {
      materials.push({ kind: "note" as const, title: "Teacher notes", content: teacherNotes.trim() });
    }
    if (materialUrl.trim()) {
      materials.push({ kind: "link" as const, title: "Course link", url: materialUrl.trim() });
    }
    try {
      await createCurriculumTopic(classroomId, moduleId, {
        title: topicTitle.trim(),
        description: topicDescription.trim(),
        learningObjectives: objectives.split("\n").map((line) => line.trim()).filter(Boolean),
        prerequisites: [],
        concepts: conceptItems,
        materials,
      });
      setTopicTitle("");
      setTopicDescription("");
      setObjectives("");
      setConcepts("");
      setTeacherNotes("");
      setMaterialUrl("");
      setNotice("Topic added to the official curriculum.");
      await refresh();
    } catch (reason) {
      setError((reason as Error).message || "Unable to create topic.");
    }
  };

  const removeClassroom = async () => {
    if (!canDelete || !window.confirm("Delete this classroom and all of its curriculum, classwork, submissions, and learning history? This cannot be undone.")) return;
    setError("");
    try {
      await deleteClassroom(classroomId);
      window.location.href = "/classrooms";
    } catch (reason) {
      setError((reason as Error).message || "Unable to delete this classroom.");
    }
  };

  if (loading) return <div className="state"><p>Loading classroom…</p></div>;
  if (error && !data) return <div className="state"><p>{error}</p><Link to="/classrooms">Back to classrooms</Link></div>;
  if (!data) return null;

  return (
    <section className="mx-auto max-w-6xl px-4 py-8 text-[#E1E0CC]">
      <Link to="/classrooms" className="text-sm text-primary hover:underline">← Classrooms</Link>
      <header className="mt-5 flex flex-wrap items-start justify-between gap-5 border-b border-primary/20 pb-6">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-primary/80">
            {data.classroom.subject} · {data.classroom.section} · {data.classroom.semester}
          </p>
          <h1 className="mt-2 text-3xl font-semibold">{data.classroom.name}</h1>
          <p className="mt-2 max-w-3xl text-sm text-[#D7D1B5]">{data.classroom.description || "No course description provided."}</p>
        </div>
        {canDelete && (
          <button
            type="button"
            onClick={() => void removeClassroom()}
            className="inline-flex items-center gap-2 rounded-lg border border-red-400/50 px-3 py-2 text-sm text-red-200 hover:bg-red-950/40"
          >
            <Trash2 size={16} /> Delete classroom
          </button>
        )}
      </header>

      <nav aria-label="Classroom sections" role="tablist" className="sticky top-0 z-20 mt-3 flex gap-1 overflow-x-auto border-b border-primary/20 bg-black/90 py-1 backdrop-blur">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={activeTab === tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`shrink-0 border-b-2 px-4 py-3 text-sm transition-colors ${activeTab === tab.id ? "border-primary text-primary" : "border-transparent text-[#D7D1B5] hover:text-primary"}`}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {error && <div role="alert" className="mt-4 rounded-lg border border-red-400/40 bg-red-950/40 p-3 text-sm text-red-100">{error}</div>}
      {notice && <p role="status" className="mt-4 text-sm text-emerald-200">{notice}</p>}

      {activeTab === "overview" && canEdit && (
        <section className="mt-6 grid gap-4 sm:grid-cols-3">
          <div className="border-l-2 border-primary/40 py-2 pl-3"><p className="text-xs uppercase text-primary/65">Modules</p><p className="mt-1 text-xl font-semibold">{data.modules.length}</p></div>
          <div className="border-l-2 border-primary/40 py-2 pl-3"><p className="text-xs uppercase text-primary/65">Topics</p><p className="mt-1 text-xl font-semibold">{data.modules.reduce((total, module) => total + module.topics.length, 0)}</p></div>
          <div className="border-l-2 border-primary/40 py-2 pl-3"><p className="text-xs uppercase text-primary/65">Join code</p><p className="mt-1 font-mono text-xl font-semibold">{data.classroom.joinCode ?? "Unavailable"}</p></div>
        </section>
      )}

      {activeTab === "curriculum" && canEdit && (
        <form onSubmit={submitModule} className="mt-6 grid gap-3 border-b border-primary/20 pb-6 md:grid-cols-[1fr_2fr_auto] md:items-end">
          <label className="grid gap-1 text-xs text-primary/80">New module
            <input required value={moduleTitle} onChange={(event) => setModuleTitle(event.target.value)} placeholder="e.g. Relational Design" className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#E1E0CC]" />
          </label>
          <label className="grid gap-1 text-xs text-primary/80">Description
            <input value={moduleDescription} onChange={(event) => setModuleDescription(event.target.value)} placeholder="Optional overview" className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#E1E0CC]" />
          </label>
          <button className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-black"><Plus size={16} /> Add module</button>
        </form>
      )}

      {activeTab === "learn" && progress && (
        <section className="mt-6 border border-primary/20 bg-black/20 p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-primary/70">Your adaptive path</p>
              <h2 className="mt-1 text-xl font-semibold">
                {progress.learningPath.progress.completed} of {progress.learningPath.progress.total} topics confirmed
              </h2>
              <p className="mt-1 text-sm text-[#D7D1B5]">
                {progress.learningPath.progress.percent}% complete · mastery {progress.mastery.score ?? "not measured"}
              </p>
            </div>
            {progress.learningPath.recommendation && (
              <Link
                to={`/?classroomId=${encodeURIComponent(classroomId)}&topicId=${encodeURIComponent(progress.learningPath.recommendation.topicId)}`}
                className="max-w-sm border border-primary/40 px-4 py-3 text-sm text-primary hover:bg-primary/10"
              >
                <span className="block text-xs uppercase tracking-wide text-primary/70">Next action</span>
                <strong className="mt-1 block">{progress.learningPath.recommendation.nextAction}: {progress.learningPath.recommendation.title}</strong>
                <span className="mt-1 block text-xs text-[#D7D1B5]">{progress.learningPath.recommendation.reason}</span>
              </Link>
            )}
          </div>
          <div className="mt-5 grid gap-2 md:grid-cols-2">
            {progress.learningPath.items.map((item) => (
              <button
                key={item.topicId}
                type="button"
                onClick={() => setSelectedTopicId(item.topicId)}
                className={`flex items-center justify-between gap-3 border-l-2 px-3 py-2 text-left text-sm hover:bg-primary/10 ${selectedTopicId === item.topicId ? "border-primary bg-primary/10" : "border-primary/30"}`}
              >
                <span>
                  <strong className="block">{item.title}</strong>
                  <span className="text-xs text-[#D7D1B5]">{item.reason}</span>
                </span>
                <span className="shrink-0 text-xs uppercase text-primary/75">{item.status.replace("_", " ")}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {activeTab === "learn" && !selectedTopicId && (
        <section className="mt-7 border border-primary/20 bg-black/20 p-5">
          <p className="text-xs uppercase tracking-[0.18em] text-primary/70">Curriculum agent</p>
          <h2 className="mt-1 text-xl font-semibold">Your teacher&apos;s curriculum will unlock this tutor</h2>
          <p className="mt-2 text-sm text-[#D7D1B5]">
            Add or publish a curriculum topic first. The classroom agent stays focused on the approved learning path and does not operate as a general chatbot.
          </p>
        </section>
      )}

      {activeTab === "learn" && selectedTopicId && (
        <section className="mt-7 border-t border-primary/20 pt-6">
          <Learn
            classroomId={classroomId}
            curriculumTopicId={selectedTopicId}
            classroomOnly
          />
        </section>
      )}

      {(activeTab === "curriculum" || activeTab === "learn") && <div className="mt-7">
        <div className="flex items-end justify-between gap-4 border-b border-primary/20 pb-3">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-primary/70">Course outline</p>
            <h2 className="mt-1 text-xl font-semibold">Curriculum</h2>
          </div>
          <span className="text-xs text-primary/70">{data.modules.length} modules</span>
        </div>
        {data.modules.length === 0 ? (
          <p className="py-8 text-sm text-primary/70">No curriculum modules have been published yet.</p>
        ) : (
          <div className="divide-y divide-primary/15">
            {data.modules.map((module, moduleIndex) => (
              <article key={module.id} className="py-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-xs text-primary/60">MODULE {String(moduleIndex + 1).padStart(2, "0")}</p>
                    <h3 className="mt-1 text-xl font-medium">{module.title}</h3>
                    {module.description && <p className="mt-1 text-sm text-[#D7D1B5]">{module.description}</p>}
                  </div>
                  <span className="text-xs text-primary/65">{module.topics.length} topics</span>
                </div>

                <div className="mt-4 grid gap-3">
                  {module.topics.map((topic) => (
                    <section key={topic.id} className="border-l-2 border-primary/40 pl-4 py-1">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <h4 className="font-medium">{topic.title}</h4>
                          {topic.description && <p className="mt-1 text-sm text-[#D7D1B5]">{topic.description}</p>}
                        </div>
                        <Link
                          to={`/?classroomId=${encodeURIComponent(classroomId)}&topicId=${encodeURIComponent(topic.id)}`}
                          className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-primary/30 px-3 py-2 text-sm text-primary hover:bg-primary/10"
                        >
                          <BookOpen size={15} /> Learn with Curiosity <ArrowRight size={14} />
                        </Link>
                      </div>
                      {topic.learningObjectives.length > 0 && (
                        <div className="mt-3 text-sm"><p className="text-xs uppercase tracking-wide text-primary/65">Learning objectives</p><ul className="mt-1 list-disc pl-5 text-[#D7D1B5]">{topic.learningObjectives.map((item) => <li key={item}>{item}</li>)}</ul></div>
                      )}
                      {topic.concepts.length > 0 && <p className="mt-2 text-xs text-primary/70">Concepts: {topic.concepts.map((concept) => concept.name).join(", ")}</p>}
                      {topic.materials.map((material, index) => (
                        <div key={`${topic.id}-material-${index}`} className="mt-2 text-sm text-[#D7D1B5]">
                          {material.kind === "link" && material.url ? <a className="text-primary underline" href={material.url} target="_blank" rel="noreferrer">{material.title}</a> : <p><span className="text-primary/70">{material.title}: </span>{material.content}</p>}
                        </div>
                      ))}
                    </section>
                  ))}
                </div>

                {canEdit && (
                  <div className="mt-5">
                    <button type="button" onClick={() => setActiveModuleId(activeModuleId === module.id ? "" : module.id)} className="rounded-md border border-primary/25 px-3 py-2 text-xs text-primary hover:bg-primary/10">
                      {activeModuleId === module.id ? "Close topic form" : "Add topic"}
                    </button>
                    {activeModuleId === module.id && (
                      <form onSubmit={(event) => void submitTopic(event, module.id)} className="mt-3 grid gap-3 rounded-lg border border-primary/20 bg-black/20 p-4">
                        <h4 className="text-sm font-medium">Add topic to {module.title}</h4>
                        <div className="grid gap-3 md:grid-cols-2">
                          <input required value={topicTitle} onChange={(event) => setTopicTitle(event.target.value)} placeholder="Topic title" className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
                          <input value={topicDescription} onChange={(event) => setTopicDescription(event.target.value)} placeholder="Description" className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
                          <textarea value={objectives} onChange={(event) => setObjectives(event.target.value)} placeholder="Learning objectives (one per line)" className="min-h-20 rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
                          <textarea value={concepts} onChange={(event) => setConcepts(event.target.value)} placeholder="Concepts (one per line; optional description after |)" className="min-h-20 rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
                          <textarea value={teacherNotes} onChange={(event) => setTeacherNotes(event.target.value)} placeholder="Teacher notes or material text" className="min-h-20 rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
                          <input type="url" value={materialUrl} onChange={(event) => setMaterialUrl(event.target.value)} placeholder="https:// course material link" className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
                        </div>
                        <button className="justify-self-start rounded-lg bg-primary px-4 py-2 text-sm font-medium text-black">Publish topic</button>
                      </form>
                    )}
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </div>}
      {activeTab === "classwork" && user && <ClassworkPanel classroomId={classroomId} canEdit={canEdit} />}
      {activeTab === "stream" && user && <ClassroomStream classroomId={classroomId} canAnnounce={canEdit} />}
      {activeTab === "people" && (
        <section className="mt-6">
          <h2 className="text-xl font-semibold">People</h2>
          <div className="mt-3 divide-y divide-primary/15 border-y border-primary/15">
            {(data.classroom.members ?? []).map((member) => (
              <div key={member.userId} className="flex items-center justify-between gap-3 py-3 text-sm">
                <span className="truncate">{member.name || "Class member"}{member.userId === user?.id ? " · You" : ""}</span>
                <span className="text-xs uppercase text-primary/70">{member.role}</span>
              </div>
            ))}
            {(data.classroom.members ?? []).length === 0 && <p className="py-5 text-sm text-primary/70">No classroom members yet.</p>}
          </div>
        </section>
      )}
      {((activeTab === "progress" && !canEdit) || (activeTab === "analytics" && canEdit)) && user && <ClassroomInsights classroomId={classroomId} canEdit={canEdit} user={user} />}
    </section>
  );
}
