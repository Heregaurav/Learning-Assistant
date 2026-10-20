import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Check, LoaderCircle, Plus, Undo2, X } from "lucide-react";
import { createClassroom, getClassrooms, joinClassroom, undoDeleteClassroom } from "../lib/api";
import type { Classroom, Role } from "../types";

type Props = {
  user: { id: string; name: string; email: string; role?: Role; isGuest?: boolean } | null;
  onRequireSignIn: () => void;
};

export default function ClassroomsPage({ user, onRequireSignIn }: Props) {
  const location = useLocation();
  const navigate = useNavigate();
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [form, setForm] = useState({
    name: "",
    subject: "",
    section: "",
    semester: "",
    description: "",
  });
  const [joinCode, setJoinCode] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [deletedClassroom, setDeletedClassroom] = useState<{ id: string; name: string; undoToken: string; undoSeconds: number } | null>(null);
  const [undoingDelete, setUndoingDelete] = useState(false);
  const [undoError, setUndoError] = useState("");
  const undoTimerRef = useRef<number | undefined>(undefined);

  const canManageClassrooms = Boolean(user);

  const loadClassrooms = async () => {
    try {
      const data = await getClassrooms();
      setClassrooms(data);
    } catch (err) {
      if ((err as { code?: string }).code === "auth_required") {
        onRequireSignIn();
        return;
      }
      setError((err as Error).message || "Unable to load classrooms.");
    }
  };

  useEffect(() => {
    if (user) void loadClassrooms();
  }, [user]);

  useEffect(() => {
    const pending = (location.state as { deletedClassroom?: typeof deletedClassroom } | null)?.deletedClassroom;
    if (!pending) return;
    setDeletedClassroom(pending);
    setUndoError("");
    if (undoTimerRef.current !== undefined) window.clearTimeout(undoTimerRef.current);
    navigate(location.pathname, { replace: true, state: null });
    undoTimerRef.current = window.setTimeout(() => setDeletedClassroom((current) => current?.undoToken === pending.undoToken ? null : current), pending.undoSeconds * 1000);
  }, [location.key, location.pathname, location.state, navigate]);

  useEffect(() => () => {
    if (undoTimerRef.current !== undefined) window.clearTimeout(undoTimerRef.current);
  }, []);

  const undoClassroomDelete = async () => {
    if (!deletedClassroom || undoingDelete) return;
    setUndoingDelete(true);
    setUndoError("");
    try {
      await undoDeleteClassroom(deletedClassroom.id, deletedClassroom.undoToken);
      if (undoTimerRef.current !== undefined) window.clearTimeout(undoTimerRef.current);
      setDeletedClassroom(null);
      setSuccess(`${deletedClassroom.name} restored.`);
      await loadClassrooms();
    } catch (reason) {
      setError((reason as Error).message || "Undo period has ended.");
      setDeletedClassroom(null);
      await loadClassrooms();
    } finally {
      setUndoingDelete(false);
    }
  };

  const handleCreate = async () => {
    if (!user) {
      setError("Sign in or enter guest mode to create a classroom.");
      return;
    }
    try {
      const created = await createClassroom(form);
      setSuccess(`Classroom created: ${created.name} (join code: ${created.joinCode})`);
      setForm({ name: "", subject: "", section: "", semester: "", description: "" });
      setShowCreateForm(false);
      await loadClassrooms();
    } catch (err) {
      setError((err as Error).message || "Unable to create classroom.");
    }
  };

  const handleJoin = async () => {
    if (!user || user.isGuest) {
      setError("Guest mode cannot join classrooms.");
      return;
    }
    try {
      const result = await joinClassroom(joinCode.trim());
      setSuccess(`Joined ${result.name}.`);
      setJoinCode("");
      await loadClassrooms();
    } catch (err) {
      setError((err as Error).message || "Unable to join classroom.");
    }
  };

  if (!user) return <div className="state"><p>Sign in to view classrooms.</p></div>;

  return (
    <section className="classrooms-page max-w-6xl mx-auto px-4 py-8 text-[#E1E0CC]">
      <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-primary">Classrooms</p>
          <h1 className="mt-2 text-3xl font-semibold">Course spaces</h1>
        </div>
        <div className="flex w-full max-w-md flex-col gap-2 rounded-xl border border-primary/20 bg-black/30 p-3">
          <label className="text-xs uppercase tracking-[0.15em] text-primary/80">Join with code</label>
          <div className="flex gap-2">
            <input
              value={joinCode}
              onChange={(e) => setJoinCode(e.target.value)}
              placeholder="ABC123"
              className="w-full rounded-lg border border-primary/20 bg-black/50 px-3 py-2 text-sm text-[#E1E0CC]"
            />
            <button
              onClick={handleJoin}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-black"
            >
              Join
            </button>
          </div>
        </div>
      </div>

      {error && <div className="mt-4 rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-200">{error}</div>}
      {success && <div className="mt-4 rounded-lg border border-emerald-500/50 bg-emerald-500/10 p-3 text-sm text-emerald-200">{success}</div>}

      {deletedClassroom && <div className="classroom-undo-toast" role="status" aria-live="polite">
        <span className="classroom-undo-toast-icon"><Check size={16} /></span>
        <div className="classroom-undo-toast-copy"><strong>{deletedClassroom.name} deleted</strong><span>{undoError || "You can undo this for a few seconds."}</span></div>
        <button type="button" disabled={undoingDelete} onClick={() => void undoClassroomDelete()} className="classroom-undo-button">
          {undoingDelete ? <LoaderCircle size={15} className="animate-spin" /> : <Undo2 size={15} />}
          {undoingDelete ? "Restoring…" : "Undo"}
        </button>
        <button type="button" onClick={() => setDeletedClassroom(null)} className="classroom-undo-dismiss" aria-label="Dismiss undo notification"><X size={16} /></button>
      </div>}

      {canManageClassrooms && (
        <div className="mt-8">
          {!showCreateForm ? (
            <button
              type="button"
              onClick={() => setShowCreateForm(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-black"
            >
              <Plus size={17} /> Create classroom
            </button>
          ) : (
            <div className="rounded-2xl border border-primary/20 bg-black/25 p-5">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-xl font-semibold">Create classroom</h2>
                <button
                  type="button"
                  onClick={() => setShowCreateForm(false)}
                  className="rounded-md p-2 text-primary/80 hover:bg-primary/10 hover:text-primary"
                  aria-label="Close create classroom form"
                  title="Close"
                >
                  <X size={18} />
                </button>
              </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Course name" className="rounded-lg border border-primary/20 bg-black/50 px-3 py-2 text-sm" />
            <input value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} placeholder="Subject" className="rounded-lg border border-primary/20 bg-black/50 px-3 py-2 text-sm" />
            <input value={form.section} onChange={(e) => setForm({ ...form, section: e.target.value })} placeholder="Section" className="rounded-lg border border-primary/20 bg-black/50 px-3 py-2 text-sm" />
            <input value={form.semester} onChange={(e) => setForm({ ...form, semester: e.target.value })} placeholder="Semester" className="rounded-lg border border-primary/20 bg-black/50 px-3 py-2 text-sm" />
            <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Description" className="md:col-span-2 min-h-[80px] rounded-lg border border-primary/20 bg-black/50 px-3 py-2 text-sm" />
          </div>
              <button onClick={handleCreate} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 font-medium text-black">
                <Plus size={16} /> Create classroom
              </button>
            </div>
          )}
        </div>
      )}

      <div className="mt-8 grid gap-4 md:grid-cols-2">
        {classrooms.length === 0 ? (
          <div className="md:col-span-2 rounded-xl border border-dashed border-primary/30 bg-black/20 p-6 text-sm text-primary/70">
            No classrooms yet. Create one or use a join code to get started.
          </div>
        ) : (
          classrooms.map((classroom) => (
            <article key={classroom.id} className="rounded-2xl border border-primary/20 bg-black/25 p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-primary/80">{classroom.subject}</p>
                  <h3 className="mt-2 text-2xl font-semibold">
                    <Link to={`/classrooms/${encodeURIComponent(classroom.id)}`} className="hover:text-primary">{classroom.name}</Link>
                  </h3>
                </div>
                <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-1 text-xs text-primary">{classroom.status ?? "active"}</span>
              </div>
              <p className="mt-3 text-sm text-[#D7D1B5]">{classroom.description || "No description provided."}</p>
              <div className="mt-4 flex flex-wrap gap-3 text-xs text-primary/80">
                <span>Section: {classroom.section}</span>
                <span>Semester: {classroom.semester}</span>
                <span>Members: {classroom.memberCount ?? 0}</span>
              </div>
              <Link to={`/classrooms/${encodeURIComponent(classroom.id)}`} className="mt-4 inline-flex items-center gap-2 text-sm text-primary hover:underline">
                Open classroom <span aria-hidden="true">→</span>
              </Link>
              {classroom.joinCode && (
                <div className="mt-4 rounded-lg bg-black/40 px-3 py-2 text-xs text-primary/80">
                  Join code: <strong>{classroom.joinCode}</strong>
                </div>
              )}
            </article>
          ))
        )}
      </div>
    </section>
  );
}
