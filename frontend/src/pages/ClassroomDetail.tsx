import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, ArrowRight, BookOpen, Check, LoaderCircle, Menu, Pencil, Plus, Trash2, X } from "lucide-react";
import {
  createCurriculumModule,
  createCurriculumTopic,
  applyClassroomCurriculumDraft,
  CLASSROOM_PROGRESS_UPDATED,
  deleteClassroom,
  deleteCurriculumModule,
  deleteCurriculumTopic,
  getClassroomCurriculum,
  getClassroomProgress,
  generateClassroomCurriculum,
  publishClassroomCurriculum,
  updateClassroom,
} from "../lib/api";
import ClassworkPanel from "./ClassworkPanel";
import ClassroomInsights from "./ClassroomInsights";
import ClassroomStream from "./ClassroomStream";
import ClassroomLectures from "./ClassroomLectures";
import Learn from "./Learn";
import { SkeletonClassroom } from "../components/Skeletons";
import type { ClassroomCurriculum, ClassroomProgress, CurriculumTopic, Role } from "../types";

type Props = {
  user: { id: string; role?: Role } | null;
};

type CurriculumDeleteTarget = { kind: "module" | "topic"; id: string; name: string };

export default function ClassroomDetail({ user }: Props) {
  const { classroomId = "" } = useParams();
  const navigate = useNavigate();
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
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [mobileOutlineOpen, setMobileOutlineOpen] = useState(false);
  const [progress, setProgress] = useState<ClassroomProgress | null>(null);
  const [selectedTopicId, setSelectedTopicId] = useState("");
  const [expandedModules, setExpandedModules] = useState<Record<string, boolean>>({});
  const [publishing, setPublishing] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deletingClassroom, setDeletingClassroom] = useState(false);
  const [curriculumDeleteTarget, setCurriculumDeleteTarget] = useState<CurriculumDeleteTarget | null>(null);
  const [curriculumDeletePending, setCurriculumDeletePending] = useState(false);
  const [curriculumDeleteStarted, setCurriculumDeleteStarted] = useState(false);
  const [curriculumDeleteFeedback, setCurriculumDeleteFeedback] = useState<{ kind: "success" | "error" | "info"; message: string } | null>(null);
  const [editingClassroom, setEditingClassroom] = useState(false);
  const [savingClassroom, setSavingClassroom] = useState(false);
  const [classroomForm, setClassroomForm] = useState({ name: "", subject: "", section: "", semester: "", description: "" });
  const cancelDeleteRef = useRef<HTMLButtonElement>(null);
  const cancelCurriculumDeleteRef = useRef<HTMLButtonElement>(null);
  const curriculumDeleteTimerRef = useRef<number | null>(null);
  const curriculumDeleteFeedbackTimerRef = useRef<number | null>(null);
  const curriculumDeleteBusyRef = useRef(false);
  const curriculumDeleteStartedRef = useRef(false);
  const [curriculumPrompt, setCurriculumPrompt] = useState("");
  const [draft, setDraft] = useState<{ modules: { title: string; description?: string; topics: Omit<CurriculumTopic, "id">[] }[] } | null>(null);
  const [generating, setGenerating] = useState(false);
  const [applyingDraft, setApplyingDraft] = useState(false);
  const applyingDraftRef = useRef(false);

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
        { id: "lectures", label: "Lectures" },
        { id: "stream", label: "Stream" },
        { id: "people", label: "People" },
        { id: "analytics", label: "Analytics" },
      ]
    : [
        { id: "learn", label: "Learn" },
        { id: "classwork", label: "Classwork" },
        { id: "lectures", label: "Lectures" },
        { id: "stream", label: "Stream" },
        { id: "people", label: "People" },
        { id: "progress", label: "My progress" },
      ];

  useEffect(() => {
    setActiveTab(canEdit ? "overview" : "learn");
  }, [canEdit]);

  useEffect(() => {
    if (!mobileNavOpen && !mobileOutlineOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileNavOpen(false);
        setMobileOutlineOpen(false);
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [mobileNavOpen, mobileOutlineOpen]);

  useEffect(() => {
    if (!showDeleteConfirm) return;
    cancelDeleteRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !deletingClassroom) setShowDeleteConfirm(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [showDeleteConfirm, deletingClassroom]);

  useEffect(() => {
    if (!curriculumDeleteTarget || curriculumDeletePending) return;
    cancelCurriculumDeleteRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !curriculumDeletePending) setCurriculumDeleteTarget(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [curriculumDeleteTarget, curriculumDeletePending]);

  useEffect(() => {
    setCurriculumDeleteTarget(null);
    setCurriculumDeletePending(false);
    setCurriculumDeleteStarted(false);
    setCurriculumDeleteFeedback(null);
    curriculumDeleteBusyRef.current = false;
    curriculumDeleteStartedRef.current = false;
    return () => {
      if (curriculumDeleteTimerRef.current !== null) window.clearTimeout(curriculumDeleteTimerRef.current);
      if (curriculumDeleteFeedbackTimerRef.current !== null) window.clearTimeout(curriculumDeleteFeedbackTimerRef.current);
    };
  }, [classroomId]);

  const refresh = async ({ silent = false }: { silent?: boolean } = {}) => {
    if (!silent) setLoading(true);
    setError("");
    try {
      setData(await getClassroomCurriculum(classroomId));
    } catch (reason) {
      setError((reason as Error).message || "Unable to load this classroom.");
    } finally {
      if (!silent) setLoading(false);
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
    let cancelled = false;
    const loadProgress = () => getClassroomProgress(classroomId)
      .then((nextProgress) => {
        if (cancelled) return;
        setProgress(nextProgress);
        setSelectedTopicId((current) => current || nextProgress.learningPath.recommendation?.topicId || "");
      })
      .catch(() => { if (!cancelled) setProgress(null); });
    void loadProgress();
    window.addEventListener(CLASSROOM_PROGRESS_UPDATED, loadProgress);
    return () => {
      cancelled = true;
      window.removeEventListener(CLASSROOM_PROGRESS_UPDATED, loadProgress);
    };
  }, [classroomId, user?.id, canEdit]);

  useEffect(() => {
    if (!data || data.modules.length === 0) return;
    setExpandedModules((current) => {
      const next: Record<string, boolean> = { ...current };
      for (const module of data.modules) {
        if (!(module.id in next)) {
          next[module.id] = true;
        }
      }
      if (!selectedTopicId) {
        next[data.modules[0].id] = true;
      }
      return next;
    });
  }, [data, selectedTopicId]);

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
      await refresh({ silent: true });
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
      await refresh({ silent: true });
    } catch (reason) {
      setError((reason as Error).message || "Unable to create topic.");
    }
  };

  const removeClassroom = async () => {
    if (!canDelete || deletingClassroom) return;
    setDeletingClassroom(true);
    setError("");
    try {
      const result = await deleteClassroom(classroomId);
      navigate("/classrooms", {
        state: {
          deletedClassroom: {
            id: result.id,
            name: data?.classroom.name ?? "Classroom",
            undoToken: result.undoToken,
            undoSeconds: result.undoSeconds,
          },
        },
      });
    } catch (reason) {
      setError((reason as Error).message || "Unable to delete this classroom.");
      setShowDeleteConfirm(false);
    } finally {
      setDeletingClassroom(false);
    }
  };

  const openClassroomEditor = () => {
    if (!data) return;
    setClassroomForm({
      name: data.classroom.name,
      subject: data.classroom.subject,
      section: data.classroom.section,
      semester: data.classroom.semester,
      description: data.classroom.description ?? "",
    });
    setEditingClassroom(true);
    setError("");
  };

  const saveClassroomDetails = async (event: FormEvent) => {
    event.preventDefault();
    if (!canEdit || savingClassroom) return;
    setSavingClassroom(true);
    setError("");
    setNotice("");
    try {
      await updateClassroom(classroomId, classroomForm);
      setEditingClassroom(false);
      setNotice("Classroom details updated.");
      await refresh({ silent: true });
    } catch (reason) {
      setError((reason as Error).message || "Unable to update classroom details.");
    } finally {
      setSavingClassroom(false);
    }
  };

  const publishCurriculum = async () => {
    setPublishing(true);
    setError("");
    try {
      await publishClassroomCurriculum(classroomId);
      setNotice("Curriculum published. Students can now begin their learning paths.");
      await refresh({ silent: true });
    } catch (reason) {
      setError((reason as Error).message || "Unable to publish curriculum.");
    } finally {
      setPublishing(false);
    }
  };

  const generateDraft = async () => {
    setGenerating(true);
    setError("");
    try {
      setDraft(await generateClassroomCurriculum(classroomId, { prompt: curriculumPrompt }));
    } catch (reason) {
      setError((reason as Error).message || "Unable to generate curriculum draft.");
    } finally {
      setGenerating(false);
    }
  };

  const addDraftToCurriculum = async () => {
    if (!draft || applyingDraftRef.current) return;
    applyingDraftRef.current = true;
    setApplyingDraft(true);
    try {
      setError("");
      const updatedCurriculum = await applyClassroomCurriculumDraft(classroomId, {
        modules: draft.modules.map((module) => ({
          title: module.title,
          description: module.description ?? "",
          topics: module.topics.map((topic) => ({
            ...topic,
            description: topic.description ?? "",
            learningObjectives: topic.learningObjectives ?? [],
            prerequisites: topic.prerequisites ?? [],
            concepts: topic.concepts ?? [],
            materials: topic.materials ?? [],
          })),
        })),
      });
      setData(updatedCurriculum);
      setDraft(null);
      setNotice("AI draft added as editable curriculum content. Review it before publishing.");
    } catch (reason) {
      setError((reason as Error).message || "Unable to add curriculum draft.");
    } finally {
      applyingDraftRef.current = false;
      setApplyingDraft(false);
    }
  };

  const showCurriculumDeleteFeedback = (kind: "success" | "error" | "info", message: string) => {
    if (curriculumDeleteFeedbackTimerRef.current !== null) window.clearTimeout(curriculumDeleteFeedbackTimerRef.current);
    setCurriculumDeleteFeedback({ kind, message });
    curriculumDeleteFeedbackTimerRef.current = window.setTimeout(() => {
      setCurriculumDeleteFeedback(null);
      curriculumDeleteFeedbackTimerRef.current = null;
    }, 4500);
  };

  const finishCurriculumDelete = async (target: CurriculumDeleteTarget) => {
    curriculumDeleteStartedRef.current = true;
    setCurriculumDeleteStarted(true);
    curriculumDeleteTimerRef.current = null;
    try {
      if (target.kind === "module") {
        await deleteCurriculumModule(classroomId, target.id);
        const deletedModule = data?.modules.find((module) => module.id === target.id);
        if (deletedModule?.topics.some((topic) => topic.id === selectedTopicId)) setSelectedTopicId("");
        setExpandedModules((current) => {
          const next = { ...current };
          delete next[target.id];
          return next;
        });
        setData((current) => current ? { ...current, modules: current.modules.filter((module) => module.id !== target.id) } : current);
      } else {
        await deleteCurriculumTopic(classroomId, target.id);
        if (selectedTopicId === target.id) setSelectedTopicId("");
        setData((current) => current ? {
          ...current,
          modules: current.modules.map((module) => ({
            ...module,
            topics: module.topics.filter((topic) => topic.id !== target.id),
          })),
        } : current);
      }
      setCurriculumDeleteTarget(null);
      showCurriculumDeleteFeedback("success", `${target.kind === "module" ? "Module" : "Topic"} deleted.`);
    } catch (reason) {
      setCurriculumDeleteTarget(null);
      showCurriculumDeleteFeedback("error", (reason as Error).message || `Unable to delete this ${target.kind}.`);
    } finally {
      curriculumDeleteBusyRef.current = false;
      curriculumDeleteStartedRef.current = false;
      setCurriculumDeletePending(false);
      setCurriculumDeleteStarted(false);
    }
  };

  const confirmCurriculumDelete = () => {
    const target = curriculumDeleteTarget;
    if (!target || curriculumDeleteBusyRef.current) return;
    curriculumDeleteBusyRef.current = true;
    curriculumDeleteStartedRef.current = false;
    setError("");
    setCurriculumDeleteFeedback(null);
    setCurriculumDeletePending(true);
    setCurriculumDeleteStarted(false);
    curriculumDeleteTimerRef.current = window.setTimeout(() => {
      void finishCurriculumDelete(target);
    }, 4500);
  };

  const undoCurriculumDelete = () => {
    if (!curriculumDeleteBusyRef.current || curriculumDeleteStartedRef.current) return;
    if (curriculumDeleteTimerRef.current !== null) window.clearTimeout(curriculumDeleteTimerRef.current);
    curriculumDeleteTimerRef.current = null;
    curriculumDeleteBusyRef.current = false;
    setCurriculumDeletePending(false);
    setCurriculumDeleteStarted(false);
    setCurriculumDeleteTarget(null);
    showCurriculumDeleteFeedback("info", "Deletion cancelled.");
  };

  if (loading) return <div className="classroom-page w-full min-h-screen px-3 pb-8 pt-4 md:px-5" aria-busy="true" aria-label="Loading classroom"><p className="sr-only" role="status">Loading classroom…</p><SkeletonClassroom /></div>;
  if (error && !data) return <div className="state"><p>{error}</p><Link to="/classrooms">Back to classrooms</Link></div>;
  if (!data) return null;

  return (
    <section className="classroom-page w-full min-h-screen px-3 pb-8 pt-4 text-[#E1E0CC] md:px-5">
      <div className="mx-auto max-w-[1600px]">
        <Link to="/classrooms" className="text-sm text-primary hover:underline">← Classrooms</Link>
      <header className="mt-5 flex flex-wrap items-start justify-between gap-5 border-b border-primary/20 pb-6">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-primary/80">
            {data.classroom.subject} · {data.classroom.section} · {data.classroom.semester}
          </p>
          <h1 className="mt-2 text-3xl font-semibold">{data.classroom.name}</h1>
          <p className="mt-2 max-w-3xl text-sm text-[#D7D1B5]">{data.classroom.description || "No course description provided."}</p>
        </div>
        {(canEdit || canDelete) && <div className="flex flex-wrap gap-2">
          {canEdit && <button type="button" onClick={openClassroomEditor} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-primary/35 bg-black/25 px-4 py-2 text-sm font-medium text-primary hover:bg-primary/10"><Pencil size={16} /> Edit details</button>}
          {canDelete && <button type="button" onClick={() => setShowDeleteConfirm(true)} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-red-500 bg-red-700 px-4 py-2 text-sm font-semibold text-white shadow-md shadow-red-950/30 hover:bg-red-800"><Trash2 size={16} /> Delete classroom</button>}
        </div>}
      </header>

      {editingClassroom && canEdit && <form onSubmit={(event) => void saveClassroomDetails(event)} className="classroom-edit-form mt-5 rounded-xl border border-primary/25 bg-black/65 p-4 md:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><p className="text-xs uppercase tracking-[0.15em] text-primary/80">Classroom settings</p><h2 className="mt-1 text-xl font-semibold">Edit details</h2></div>
          <button type="button" onClick={() => setEditingClassroom(false)} disabled={savingClassroom} className="grid h-10 w-10 place-items-center rounded-lg border border-primary/25 text-primary hover:bg-primary/10 disabled:opacity-50" aria-label="Cancel editing"><X size={18} /></button>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1.5 text-sm">Classroom name<input required maxLength={200} value={classroomForm.name} onChange={(event) => setClassroomForm((form) => ({ ...form, name: event.target.value }))} /></label>
          <label className="grid gap-1.5 text-sm">Subject<input required maxLength={200} value={classroomForm.subject} onChange={(event) => setClassroomForm((form) => ({ ...form, subject: event.target.value }))} /></label>
          <label className="grid gap-1.5 text-sm">Section<input required maxLength={50} value={classroomForm.section} onChange={(event) => setClassroomForm((form) => ({ ...form, section: event.target.value }))} /></label>
          <label className="grid gap-1.5 text-sm">Semester<input required maxLength={80} value={classroomForm.semester} onChange={(event) => setClassroomForm((form) => ({ ...form, semester: event.target.value }))} /></label>
          <label className="grid gap-1.5 text-sm sm:col-span-2">Description<textarea maxLength={2000} rows={3} value={classroomForm.description} onChange={(event) => setClassroomForm((form) => ({ ...form, description: event.target.value }))} /></label>
        </div>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <button type="button" disabled={savingClassroom} onClick={() => setEditingClassroom(false)} className="min-h-11 rounded-lg border border-primary/30 px-4 py-2 text-sm hover:bg-white/5 disabled:opacity-50">Cancel</button>
          <button type="submit" disabled={savingClassroom} className="min-h-11 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-black disabled:opacity-60">{savingClassroom ? "Saving…" : "Save changes"}</button>
        </div>
      </form>}

      <button
        type="button"
        className="mt-3 inline-flex min-h-11 items-center gap-2 border border-primary/25 bg-black/80 px-3 text-sm text-[#E1E0CC] md:hidden"
        onClick={() => setMobileNavOpen(true)}
        aria-expanded={mobileNavOpen}
        aria-controls="classroom-mobile-navigation"
      >
        <Menu size={18} /> Sections
      </button>

      <nav aria-label="Classroom sections" role="tablist" className="sticky top-0 z-20 mt-3 hidden gap-1 overflow-x-auto border-b border-primary/20 bg-black/90 py-1 backdrop-blur md:flex">
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

      {mobileNavOpen && (
        <div className="fixed inset-0 z-50 md:hidden" id="classroom-mobile-navigation">
          <button
            type="button"
            className="absolute inset-0 h-full w-full bg-black/70"
            onClick={() => setMobileNavOpen(false)}
            aria-label="Close classroom sections"
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-label="Classroom sections"
            className="absolute inset-y-0 left-0 flex w-[min(86vw,340px)] flex-col border-r border-primary/25 bg-[#080d12] text-[#E1E0CC] shadow-2xl"
          >
            <div className="flex items-start justify-between gap-3 border-b border-primary/20 p-5">
              <div className="min-w-0">
                <p className="text-[10px] uppercase tracking-[0.16em] text-primary/70">Classroom</p>
                <h2 className="mt-1 truncate text-base font-semibold">{data.classroom.name}</h2>
              </div>
              <button
                type="button"
                className="grid h-9 w-9 shrink-0 place-items-center border border-primary/20 text-primary"
                onClick={() => setMobileNavOpen(false)}
                aria-label="Close classroom sections"
              >
                <X size={18} />
              </button>
            </div>
            <nav aria-label="Classroom sections" role="tablist" className="grid gap-1 overflow-y-auto p-3">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab.id}
                  onClick={() => {
                    setActiveTab(tab.id);
                    setMobileNavOpen(false);
                    setMobileOutlineOpen(false);
                  }}
                  className={`min-h-12 border-l-2 px-4 text-left text-sm transition-colors ${activeTab === tab.id ? "border-primary bg-primary/10 text-primary" : "border-transparent text-[#D7D1B5] hover:bg-white/5"}`}
                >
                  {tab.label}
                </button>
              ))}
            </nav>
          </aside>
        </div>
      )}

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
        <>
        <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-b border-primary/20 pb-4">
          <p className="text-sm text-primary/75">Status: <strong>{data.status ?? "draft"}</strong> · version {data.version ?? 0}</p>
          <button type="button" onClick={() => void publishCurriculum()} disabled={publishing || data.modules.length === 0 || !data.modules.some((module) => module.topics.length > 0)} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-black disabled:cursor-not-allowed disabled:opacity-40">
            {publishing ? "Publishing…" : "Publish curriculum"}
          </button>
        </div>
        <div className="mt-4 grid gap-3 border-b border-primary/20 pb-4">
          <label className="grid gap-1 text-xs text-primary/75">Generate curriculum draft with AI
            <textarea value={curriculumPrompt} onChange={(event) => setCurriculumPrompt(event.target.value)} placeholder="Paste syllabus, course goals, or curriculum notes" className="min-h-24 rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
          </label>
          <button type="button" onClick={() => void generateDraft()} disabled={generating || curriculumPrompt.trim().length < 10} className="w-fit rounded-lg border border-primary/40 px-4 py-2 text-sm text-primary disabled:opacity-40">{generating ? "Generating draft…" : "Generate draft"}</button>
          {draft && <div className="border-l-2 border-primary/40 pl-4 text-sm"><p className="font-medium">Draft preview: {draft.modules.length} modules</p><ul className="mt-2 grid gap-1 text-primary/75">{draft.modules.map((module) => <li key={module.title}>{module.title} · {module.topics.length} topics</li>)}</ul><button type="button" onClick={() => void addDraftToCurriculum()} disabled={applyingDraft} aria-busy={applyingDraft} className="mt-3 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-black disabled:cursor-wait disabled:opacity-60">{applyingDraft ? "Adding draft…" : "Add draft for review"}</button></div>}
        </div>
        <form onSubmit={submitModule} className="mt-4 grid gap-3 border-b border-primary/20 pb-6 md:grid-cols-[1fr_2fr_auto] md:items-end">
          <label className="grid gap-1 text-xs text-primary/80">New module
            <input required value={moduleTitle} onChange={(event) => setModuleTitle(event.target.value)} placeholder="e.g. Relational Design" className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#E1E0CC]" />
          </label>
          <label className="grid gap-1 text-xs text-primary/80">Description
            <input value={moduleDescription} onChange={(event) => setModuleDescription(event.target.value)} placeholder="Optional overview" className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#E1E0CC]" />
          </label>
          <button className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-black"><Plus size={16} /> Add module</button>
        </form>
        </>
      )}

      {activeTab === "learn" && progress && (
        <section className="mt-6 rounded-none  border border-primary/20 bg-black/90 p-5 shadow-[0_0_0_1px_rgba(166,196,255,0.04)]">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-[11px] uppercase tracking-[0.18em] text-primary/70">Your adaptive path</p>
              <h2 className="mt-2 text-[1.65rem] font-semibold leading-tight text-[#f2efe8]">
                {progress.learningPath.progress.completed} of {progress.learningPath.progress.total} topics confirmed
              </h2>
              <p className="mt-1 text-sm text-[#d7d1b5]">
                {progress.learningPath.progress.percent}% complete · mastery {progress.mastery.score ?? "not measured"}
              </p>
            </div>
            {progress.learningPath.recommendation && (
              <Link
                to={`/?classroomId=${encodeURIComponent(classroomId)}&topicId=${encodeURIComponent(progress.learningPath.recommendation.topicId)}`}
                className="max-w-sm  border border-primary/30 bg-[#0d161f] px-4 py-3 text-left text-sm text-primary transition-colors hover:border-primary/60 hover:bg-primary/5"
              >
                <span className="block text-[10px] uppercase tracking-[0.14em] text-primary/70">Next action</span>
                <strong className="mt-2 block text-base font-medium text-[#f2efe8]">
                  {progress.learningPath.recommendation.nextAction}: {progress.learningPath.recommendation.title}
                </strong>
                <span className="mt-1 block text-xs leading-relaxed text-[#d7d1b5]">
                  {progress.learningPath.recommendation.reason}
                </span>
              </Link>
            )}
          </div>
        </section>
      )}

      {activeTab === "learn" && data.modules.length > 0 && (
        <>
        <button
          type="button"
          className="mt-5 inline-flex min-h-11 items-center gap-2 border border-primary/25 bg-[#030303] px-3 text-sm text-[#E1E0CC] xl:hidden"
          onClick={() => setMobileOutlineOpen(true)}
          aria-expanded={mobileOutlineOpen}
          aria-controls="classroom-course-outline"
        >
          <Menu size={18} /> Course modules
        </button>
        <section className="mt-3 grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
          {mobileOutlineOpen && (
            <button
              type="button"
              className="fixed inset-0 z-40 bg-black/70 xl:hidden"
              onClick={() => setMobileOutlineOpen(false)}
              aria-label="Close course modules"
            />
          )}
          <aside id="classroom-course-outline" className={`fixed inset-y-0 left-0 z-50 h-dvh w-[min(88vw,420px)] overflow-y-auto border-r border-primary/25 bg-[#030303] p-3 shadow-2xl transition-transform duration-200 xl:static xl:z-auto xl:h-auto xl:w-auto xl:translate-x-0 xl:overflow-visible xl:shadow-none xl:min-h-[560px] ${mobileOutlineOpen ? "translate-x-0" : "-translate-x-full"}`}>
            <div className="mb-3 flex items-center justify-between px-2 pt-1">
              <div>
                <p className="text-[11px] uppercase tracking-[0.18em] text-primary/70">Course outline</p>
                <span className="text-[10px] uppercase tracking-[0.12em] text-primary/60">{data.modules.length} modules</span>
              </div>
              <button type="button" className="grid h-9 w-9 place-items-center border border-primary/20 text-primary xl:hidden" onClick={() => setMobileOutlineOpen(false)} aria-label="Close course modules">
                <X size={18} />
              </button>
            </div>

            <div className="space-y-2">
              {data.modules.map((module, moduleIndex) => {
                const isExpanded = expandedModules[module.id] ?? true;
                return (
                  <div
                    key={module.id}
                    className="rounded-none border border-primary/10 bg-[#0d141d] overflow-hidden"
                  >
                    <button
                      type="button"
                      onClick={() => setExpandedModules((current) => ({ ...current, [module.id]: !isExpanded }))}
                      className="flex w-full items-center justify-between gap-3 px-3 py-3 text-left transition-colors hover:bg-primary/5"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-primary/60">Module {String(moduleIndex + 1).padStart(2, "0")}</p>
                        <p className="mt-1 truncate text-sm font-medium text-[#F2EFE8]">{module.title}</p>
                      </div>
                      <span className={`text-primary/70 transition-transform ${isExpanded ? "rotate-180" : ""}`}>
                        ▾
                      </span>
                    </button>

                    {isExpanded && (
                      <div className="border-t border-primary/10 bg-[#1d1e20] px-2 pb-2 pt-2">
                        {module.topics.length === 0 ? (
                          <p className="px-2 py-2 text-xs text-primary/60">No topics in this module yet.</p>
                        ) : (
                          <div className="space-y-1.5">
                            {module.topics.map((topic) => {
                              const isSelected = selectedTopicId === topic.id;
                              return (
                                <button
                                  key={topic.id}
                                  type="button"
                                  onClick={() => {
                                    setSelectedTopicId(topic.id);
                                    setMobileOutlineOpen(false);
                                  }}
                                  className={`flex w-full items-center justify-between gap-3 rounded-none border px-2.5 py-2 text-left transition-colors ${
                                    isSelected
                                      ? "border-primary/50 bg-primary/10 text-[#f2efe8]"
                                      : "border-transparent bg-transparent text-[#d7d1b5] hover:border-primary/15 hover:bg-primary/5"
                                  }`}
                                >
                                  <span className="min-w-0 flex-1 text-sm leading-relaxed">{topic.title}</span>
                                  <span className="shrink-0 text-[9px] uppercase tracking-[0.12em] text-primary/60">{topic.title ? "topic" : ""}</span>
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </aside>

<div className="min-w-0 w-full">
            {activeTab === "learn" && !selectedTopicId && (
              <section className="rounded-2xl border border-primary/20 bg-black/20 p-5 md:p-7">
                <p className="text-xs uppercase tracking-[0.18em] text-primary/70">Curriculum agent</p>
                <h2 className="mt-1 text-3xl font-semibold leading-tight md:text-4xl">Your teacher&apos;s curriculum will unlock this tutor</h2>
                <p className="mt-2 max-w-3xl text-sm text-[#D7D1B5] md:text-base">
                  Add or publish a curriculum topic first. The classroom agent stays focused on the approved learning path and does not operate as a general chatbot.
                </p>
              </section>
            )}

            {activeTab === "learn" && selectedTopicId && (
              <section className="rounded-2xl border border-primary/20 bg-[#030303] p-2 md:p-3 xl:min-h-[560px]">
                <Learn
                  classroomId={classroomId}
                  curriculumTopicId={selectedTopicId}
                  classroomOnly
                  revisionTasks={progress?.revisionTasks ?? []}
                  revisionHistory={progress?.revisionHistory ?? []}
                  topicStatus={progress?.learningPath.items.find((item) => item.topicId === selectedTopicId)?.status}
                />
              </section>
            )}
          </div>
        </section>
        </>
      )}

      {activeTab === "learn" && data.modules.length === 0 && !selectedTopicId && (
        <section className="mt-7 border border-primary/20 bg-black/20 p-5">
          <p className="text-xs uppercase tracking-[0.18em] text-primary/70">Curriculum agent</p>
          <h2 className="mt-1 text-xl font-semibold">Your teacher&apos;s curriculum will unlock this tutor</h2>
          <p className="mt-2 text-sm text-[#D7D1B5]">
            Add or publish a curriculum topic first. The classroom agent stays focused on the approved learning path and does not operate as a general chatbot.
          </p>
        </section>
      )}

      {activeTab === "curriculum" && <section className="mt-7 rounded-none border border-primary/25 bg-black/95 p-5 text-[#f2efe8] md:p-7">
        <div className="flex items-end justify-between gap-4 border-b border-primary/20 pb-3">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-primary/90">Course outline</p>
            <h2 className="mt-1 text-xl font-semibold">Curriculum</h2>
          </div>
          <span className="text-xs text-primary/90">{data.modules.length} modules</span>
        </div>
        {data.modules.length === 0 ? (
          <p className="py-8 text-sm text-[#dedbc8]">No curriculum modules have been published yet.</p>
        ) : (
          <div className="divide-y divide-primary/25">
            {data.modules.map((module, moduleIndex) => (
              <article key={module.id} className="py-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-medium text-primary/85">MODULE {String(moduleIndex + 1).padStart(2, "0")}</p>
                    <h3 className="mt-1 text-xl font-medium">{module.title}</h3>
                    {module.description && <p className="mt-1 text-sm text-[#e5e2d6]">{module.description}</p>}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-primary/85">{module.topics.length} topics</span>
                    {canEdit && (
                      <button type="button" onClick={() => setCurriculumDeleteTarget({ kind: "module", id: module.id, name: module.title })} className="inline-flex items-center gap-1 rounded-md border border-red-400/40 px-2 py-1 text-xs text-red-200 hover:bg-red-950/40" aria-label={`Delete module ${module.title}`}>
                        <Trash2 size={14} /> Delete
                      </button>
                    )}
                  </div>
                </div>

                <div className="mt-4 grid gap-3">
                  {module.topics.map((topic) => (
                    <section key={topic.id} className="border-l-2 border-primary/40 pl-4 py-1">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <h4 className="font-medium">{topic.title}</h4>
                          {topic.description && <p className="mt-1 text-sm text-[#e5e2d6]">{topic.description}</p>}
                        </div>
                        <div className="flex items-center gap-2">
                          <Link
                            to={`/?classroomId=${encodeURIComponent(classroomId)}&topicId=${encodeURIComponent(topic.id)}`}
                            className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-primary/30 px-3 py-2 text-sm text-primary hover:bg-primary/10"
                          >
                            <BookOpen size={15} /> Learn with Curiosity <ArrowRight size={14} />
                          </Link>
                          {canEdit && (
                            <button type="button" onClick={() => setCurriculumDeleteTarget({ kind: "topic", id: topic.id, name: topic.title })} className="inline-flex items-center gap-1 rounded-lg border border-red-400/40 px-2 py-2 text-xs text-red-200 hover:bg-red-950/40" aria-label={`Delete topic ${topic.title}`}>
                              <Trash2 size={14} /> Delete
                            </button>
                          )}
                        </div>
                      </div>
                      {topic.learningObjectives.length > 0 && (
                        <div className="mt-3 text-sm"><p className="text-xs uppercase tracking-wide text-primary/90">Learning objectives</p><ul className="mt-1 list-disc pl-5 text-[#e5e2d6]">{topic.learningObjectives.map((item) => <li key={item}>{item}</li>)}</ul></div>
                      )}
                      {topic.concepts.length > 0 && <p className="mt-2 text-xs text-primary/90">Concepts: {topic.concepts.map((concept) => concept.name).join(", ")}</p>}
                      {topic.materials.map((material, index) => (
                        <div key={`${topic.id}-material-${index}`} className="mt-2 text-sm text-[#e5e2d6]">
                          {material.kind === "link" && material.url ? <a className="text-primary underline" href={material.url} target="_blank" rel="noreferrer">{material.title}</a> : <p><span className="text-primary/90">{material.title}: </span>{material.content}</p>}
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
      </section>}
      {activeTab === "classwork" && user && <ClassworkPanel classroomId={classroomId} canEdit={canEdit} />}
      {activeTab === "lectures" && user && <ClassroomLectures classroomId={classroomId} canEdit={canEdit} user={user} />}
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
      </div>
      {showDeleteConfirm && (
        <div className="classroom-delete-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget && !deletingClassroom) setShowDeleteConfirm(false); }}>
          <section
            className="classroom-delete-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-classroom-title"
            aria-describedby="delete-classroom-description"
          >
            <div className="classroom-delete-icon" aria-hidden="true"><AlertTriangle size={22} /></div>
            <p className="classroom-delete-eyebrow">Permanent action</p>
            <h2 id="delete-classroom-title">Delete {data.classroom.name}?</h2>
            <p id="delete-classroom-description">
              This will permanently remove the classroom, curriculum, classwork, submissions, and learning history. This action cannot be undone.
            </p>
            {error && <p className="classroom-delete-error" role="alert">{error}</p>}
            <div className="classroom-delete-actions">
              <button ref={cancelDeleteRef} type="button" disabled={deletingClassroom} onClick={() => setShowDeleteConfirm(false)}>
                Cancel
              </button>
              <button type="button" className="classroom-delete-confirm" disabled={deletingClassroom} onClick={() => void removeClassroom()}>
                <Trash2 size={16} /> {deletingClassroom ? "Deleting classroom…" : "Delete classroom"}
              </button>
            </div>
          </section>
        </div>
      )}
      {curriculumDeleteTarget && (
        <div
          className="classroom-delete-overlay"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !curriculumDeletePending) setCurriculumDeleteTarget(null);
          }}
        >
          <section
            className="classroom-delete-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-curriculum-item-title"
            aria-describedby="delete-curriculum-item-description"
            aria-busy={curriculumDeletePending}
          >
            <div className="classroom-delete-icon" aria-hidden="true"><Trash2 size={20} /></div>
            <p className="classroom-delete-eyebrow">{curriculumDeleteTarget.kind === "module" ? "Delete module" : "Delete topic"}</p>
            <h2 id="delete-curriculum-item-title">{curriculumDeleteTarget.name}</h2>
            <p id="delete-curriculum-item-description">
              {curriculumDeleteTarget.kind === "module"
                ? "This removes the module and its topics from the curriculum. You can undo before deletion completes."
                : "This removes the topic from the curriculum. You can undo before deletion completes."}
            </p>
            {curriculumDeletePending && <p className="curriculum-delete-pending" role="status">{curriculumDeleteStarted ? "Finishing deletion…" : "Deleting in a few seconds. Undo from the notification if you change your mind."}</p>}
            <div className="classroom-delete-actions">
              <button
                ref={cancelCurriculumDeleteRef}
                type="button"
                disabled={curriculumDeleteStarted}
                onClick={() => curriculumDeletePending ? undoCurriculumDelete() : setCurriculumDeleteTarget(null)}
              >
                {curriculumDeletePending ? "Undo" : "Cancel"}
              </button>
              <button type="button" className="classroom-delete-confirm" disabled={curriculumDeletePending} onClick={confirmCurriculumDelete}>
                {curriculumDeletePending ? <LoaderCircle size={16} className="curriculum-delete-spinner" aria-hidden="true" /> : <Trash2 size={16} aria-hidden="true" />}
                {curriculumDeletePending ? "Deleting…" : "Delete"}
              </button>
            </div>
          </section>
        </div>
      )}
      {curriculumDeletePending && !curriculumDeleteStarted && curriculumDeleteTarget && (
        <div className="classroom-undo-toast curriculum-undo-toast" role="status" aria-live="polite">
          <span className="classroom-undo-toast-icon curriculum-undo-icon"><Trash2 size={15} aria-hidden="true" /></span>
          <div className="classroom-undo-toast-copy">
            <strong>{curriculumDeleteTarget.name} will be deleted</strong>
            <span>Undo within 4.5 seconds</span>
          </div>
          <button type="button" className="classroom-undo-button" onClick={undoCurriculumDelete}>Undo</button>
        </div>
      )}
      {curriculumDeleteFeedback && (
        <div className={`classroom-undo-toast curriculum-delete-feedback curriculum-delete-feedback-${curriculumDeleteFeedback.kind}`} role={curriculumDeleteFeedback.kind === "error" ? "alert" : "status"} aria-live="polite">
          <span className="classroom-undo-toast-icon">
            {curriculumDeleteFeedback.kind === "success" ? <Check size={15} aria-hidden="true" /> : curriculumDeleteFeedback.kind === "error" ? <AlertTriangle size={15} aria-hidden="true" /> : <X size={15} aria-hidden="true" />}
          </span>
          <div className="classroom-undo-toast-copy"><strong>{curriculumDeleteFeedback.message}</strong></div>
          <button type="button" className="classroom-undo-dismiss" onClick={() => setCurriculumDeleteFeedback(null)} aria-label="Dismiss notification"><X size={16} /></button>
        </div>
      )}
    </section>
  );
}
