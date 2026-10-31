import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Copy,
  Eye,
  GraduationCap,
  Info,
  LoaderCircle,
  Mail,
  Plus,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  UserCheck,
  Users,
  X,
} from "lucide-react";
import {
  addClassroomMember,
  getClassroomMembers,
  removeClassroomMember,
  updateClassroomMemberRole,
} from "../lib/api";
import type { Classroom, ClassroomMember, Role } from "../types";
import { SkeletonList } from "./Skeletons";

type Props = {
  classroomId: string;
  classroom: Classroom;
  user: { id: string; role?: Role } | null;
  isOwner: boolean;
  onMembersUpdated?: () => Promise<void> | void;
};

type TabKey = "all" | "students" | "assistants" | "owners" | "requests";
type SortKey = "newest" | "oldest" | "name_asc" | "name_desc" | "role";

function formatDate(iso?: string | null): string {
  if (!iso) return "Recently";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "Recently";
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return "Recently";
  }
}

function getRoleLabel(role?: string): string {
  const norm = (role || "STUDENT").toUpperCase();
  if (norm === "OWNER") return "Classroom Owner";
  if (norm === "ASSISTANT") return "Assistant Teacher";
  return "Student";
}

function getRoleBadgeClasses(role?: string): string {
  const norm = (role || "STUDENT").toUpperCase();
  if (norm === "OWNER") {
    return "bg-amber-500/15 text-amber-300 border-amber-500/30";
  }
  if (norm === "ASSISTANT") {
    return "bg-purple-500/15 text-purple-300 border-purple-500/30";
  }
  return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
}

export default function ClassroomPeople({
  classroomId,
  classroom,
  user,
  isOwner,
  onMembersUpdated,
}: Props) {
  const [members, setMembers] = useState<ClassroomMember[]>(classroom.members || []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Filters & Search
  const [activeTab, setActiveTab] = useState<TabKey>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("ALL");
  const [sortBy, setSortBy] = useState<SortKey>("newest");

  // Add Member Modal
  const [showAddModal, setShowAddModal] = useState(false);
  const [addEmail, setAddEmail] = useState("");
  const [addRole, setAddRole] = useState<"STUDENT" | "ASSISTANT">("STUDENT");
  const [addingMember, setAddingMember] = useState(false);
  const [addError, setAddError] = useState("");

  // Role Change Modal
  const [roleChangeTarget, setRoleChangeTarget] = useState<ClassroomMember | null>(null);
  const [newRoleSelection, setNewRoleSelection] = useState<"STUDENT" | "ASSISTANT" | "OWNER">("STUDENT");
  const [updatingRole, setUpdatingRole] = useState(false);
  const [roleChangeError, setRoleChangeError] = useState("");

  // Remove Member Modal
  const [removeTarget, setRemoveTarget] = useState<ClassroomMember | null>(null);
  const [removingMember, setRemovingMember] = useState(false);
  const [removeError, setRemoveError] = useState("");

  // Member Details Modal
  const [detailMember, setDetailMember] = useState<ClassroomMember | null>(null);

  // Copy feedback
  const [copiedCode, setCopiedCode] = useState(false);
  const copyTimerRef = useRef<number | null>(null);

  const joinCode = classroom.joinCode || "";

  // Refresh members from backend
  const refreshMembers = async (showLoadingState = true) => {
    if (showLoadingState) setLoading(true);
    setError("");
    try {
      const res = await getClassroomMembers(classroomId);
      if (res && Array.isArray(res.members)) {
        setMembers(res.members);
      }
    } catch (err) {
      setError((err as Error).message || "Unable to load classroom members.");
    } finally {
      if (showLoadingState) setLoading(false);
    }
  };

  useEffect(() => {
    void refreshMembers(true);
  }, [classroomId]);

  // Keep in sync with parent classroom data if it updates
  useEffect(() => {
    if (classroom.members && classroom.members.length > 0 && members.length === 0) {
      setMembers(classroom.members);
    }
  }, [classroom.members]);

  const handleCopyCode = async () => {
    if (!joinCode) return;
    try {
      await navigator.clipboard.writeText(joinCode);
      setCopiedCode(true);
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = window.setTimeout(() => setCopiedCode(false), 2000);
    } catch {
      // Fallback
    }
  };

  // Submit Add Member
  const handleAddMember = async (e: React.FormEvent) => {
    e.preventDefault();
    const email = addEmail.trim().toLowerCase();
    if (!email) {
      setAddError("Please enter a valid email address.");
      return;
    }
    setAddingMember(true);
    setAddError("");
    try {
      await addClassroomMember(classroomId, {
        email,
        role: addRole,
      });
      setNotice(`Added ${email} to this classroom as ${getRoleLabel(addRole)}.`);
      setShowAddModal(false);
      setAddEmail("");
      setAddRole("STUDENT");
      await refreshMembers(false);
      if (onMembersUpdated) void onMembersUpdated();
    } catch (err) {
      setAddError((err as Error).message || "Unable to add member.");
    } finally {
      setAddingMember(false);
    }
  };

  // Open Role Change
  const promptRoleChange = (member: ClassroomMember, targetRole: "STUDENT" | "ASSISTANT" | "OWNER") => {
    setRoleChangeTarget(member);
    setNewRoleSelection(targetRole);
    setRoleChangeError("");
  };

  // Submit Role Change
  const handleConfirmRoleChange = async () => {
    if (!roleChangeTarget) return;
    setUpdatingRole(true);
    setRoleChangeError("");
    try {
      await updateClassroomMemberRole(classroomId, roleChangeTarget.userId, newRoleSelection);
      setNotice(`Updated ${roleChangeTarget.name}'s role to ${getRoleLabel(newRoleSelection)}.`);
      setRoleChangeTarget(null);
      await refreshMembers(false);
      if (onMembersUpdated) void onMembersUpdated();
    } catch (err) {
      setRoleChangeError((err as Error).message || "Unable to update member role.");
    } finally {
      setUpdatingRole(false);
    }
  };

  // Submit Remove Member
  const handleConfirmRemoveMember = async () => {
    if (!removeTarget) return;
    setRemovingMember(true);
    setRemoveError("");
    try {
      await removeClassroomMember(classroomId, removeTarget.userId);
      setNotice(`Removed ${removeTarget.name} from this classroom.`);
      setRemoveTarget(null);
      await refreshMembers(false);
      if (onMembersUpdated) void onMembersUpdated();
    } catch (err) {
      setRemoveError((err as Error).message || "Unable to remove member.");
    } finally {
      setRemovingMember(false);
    }
  };

  // Metrics
  const counts = useMemo(() => {
    let owners = 0;
    let assistants = 0;
    let students = 0;
    for (const m of members) {
      const r = (m.role || "STUDENT").toUpperCase();
      if (r === "OWNER") owners++;
      else if (r === "ASSISTANT") assistants++;
      else students++;
    }
    return { total: members.length, owners, assistants, students };
  }, [members]);

  // Filtered & Sorted Members
  const displayedMembers = useMemo(() => {
    return members
      .filter((m) => {
        const r = (m.role || "STUDENT").toUpperCase();
        // Tab filtering
        if (activeTab === "students" && r !== "STUDENT") return false;
        if (activeTab === "assistants" && r !== "ASSISTANT") return false;
        if (activeTab === "owners" && r !== "OWNER") return false;

        // Role select filtering
        if (roleFilter !== "ALL" && r !== roleFilter) return false;

        // Search filtering
        if (searchQuery.trim()) {
          const q = searchQuery.toLowerCase().trim();
          const nameMatch = (m.name || "").toLowerCase().includes(q);
          const emailMatch = (m.email || "").toLowerCase().includes(q);
          if (!nameMatch && !emailMatch) return false;
        }

        return true;
      })
      .sort((a, b) => {
        if (sortBy === "name_asc") {
          return (a.name || "").localeCompare(b.name || "");
        }
        if (sortBy === "name_desc") {
          return (b.name || "").localeCompare(a.name || "");
        }
        if (sortBy === "oldest") {
          return (a.joinedAt || "").localeCompare(b.joinedAt || "");
        }
        if (sortBy === "role") {
          const order: Record<string, number> = { OWNER: 1, ASSISTANT: 2, STUDENT: 3 };
          const ra = order[(a.role || "STUDENT").toUpperCase()] || 4;
          const rb = order[(b.role || "STUDENT").toUpperCase()] || 4;
          return ra - rb;
        }
        // default: newest
        return (b.joinedAt || "").localeCompare(a.joinedAt || "");
      });
  }, [members, activeTab, roleFilter, searchQuery, sortBy]);

  // ==========================================
  // STUDENT / ASSISTANT (READ-ONLY VIEW)
  // ==========================================
  if (!isOwner) {
    const instructors = members.filter((m) => {
      const r = (m.role || "STUDENT").toUpperCase();
      return r === "OWNER" || r === "ASSISTANT";
    });
    const classmates = members.filter((m) => {
      const r = (m.role || "STUDENT").toUpperCase();
      return r !== "OWNER" && r !== "ASSISTANT";
    });

    return (
      <section className="mt-6 text-[#E1E0CC]">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-primary/20 pb-5">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-[#E1E0CC]">Classroom People</h2>
            <p className="mt-1 text-sm text-[#D7D1B5]">
              Members enrolled in {classroom.name || "this classroom"}.
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-full border border-primary/25 bg-black/40 px-4 py-1.5 text-xs text-primary">
            <Users size={14} className="text-primary/80" />
            <span>{members.length} member{members.length === 1 ? "" : "s"}</span>
          </div>
        </div>

        {error && (
          <div role="alert" className="mt-4 rounded-lg border border-red-500/40 bg-red-950/40 p-3.5 text-sm text-red-200">
            {error}
          </div>
        )}

        {loading ? (
          <div className="mt-6" aria-busy="true">
            <SkeletonList count={4} />
          </div>
        ) : (
          <div className="mt-8 space-y-10">
            {/* Instructors Section */}
            <div>
              <div className="flex items-center gap-2 border-b border-primary/20 pb-2.5">
                <ShieldCheck size={18} className="text-amber-300" />
                <h3 className="text-lg font-medium text-amber-200/90">Teachers & Instructors</h3>
                <span className="ml-auto rounded-full bg-amber-500/10 px-2 py-0.5 text-xs text-amber-300">
                  {instructors.length}
                </span>
              </div>
              <div className="mt-3 divide-y divide-primary/10 border-b border-primary/10">
                {instructors.map((member) => (
                  <article
                    key={member.userId}
                    className="flex items-center justify-between gap-4 py-3.5"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      {member.picture ? (
                        <img
                          src={member.picture}
                          alt=""
                          className="h-9 w-9 rounded-full object-cover ring-1 ring-primary/30"
                        />
                      ) : (
                        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-amber-500/20 text-xs font-semibold text-amber-200 ring-1 ring-amber-500/30">
                          {(member.name || "T").charAt(0).toUpperCase()}
                        </div>
                      )}
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="truncate font-medium text-sm text-[#E1E0CC]">{member.name || "Instructor"}</p>
                          {member.userId === user?.id && (
                            <span className="rounded bg-primary/20 px-1.5 py-0.2 text-[10px] font-medium text-primary">You</span>
                          )}
                        </div>
                        <p className="text-xs text-primary/70">{getRoleLabel(member.role)}</p>
                      </div>
                    </div>
                    <span className="text-xs text-[#D7D1B5]/60">Joined {formatDate(member.joinedAt)}</span>
                  </article>
                ))}
              </div>
            </div>

            {/* Students Section */}
            <div>
              <div className="flex items-center gap-2 border-b border-primary/20 pb-2.5">
                <GraduationCap size={18} className="text-emerald-300" />
                <h3 className="text-lg font-medium text-emerald-200/90">Students & Classmates</h3>
                <span className="ml-auto rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300">
                  {classmates.length}
                </span>
              </div>
              {classmates.length === 0 ? (
                <p className="py-6 text-sm text-[#D7D1B5]/70">No other students enrolled yet.</p>
              ) : (
                <div className="mt-3 divide-y divide-primary/10 border-b border-primary/10">
                  {classmates.map((member) => (
                    <article
                      key={member.userId}
                      className="flex items-center justify-between gap-4 py-3.5"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        {member.picture ? (
                          <img
                            src={member.picture}
                            alt=""
                            className="h-9 w-9 rounded-full object-cover ring-1 ring-primary/30"
                          />
                        ) : (
                          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-xs font-semibold text-primary ring-1 ring-primary/20">
                            {(member.name || "S").charAt(0).toUpperCase()}
                          </div>
                        )}
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="truncate font-medium text-sm text-[#E1E0CC]">{member.name || "Student"}</p>
                            {member.userId === user?.id && (
                              <span className="rounded bg-primary/20 px-1.5 py-0.2 text-[10px] font-medium text-primary">You</span>
                            )}
                          </div>
                          <p className="text-xs text-primary/70">{member.email || "Student"}</p>
                        </div>
                      </div>
                      <span className="text-xs text-[#D7D1B5]/60">Joined {formatDate(member.joinedAt)}</span>
                    </article>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </section>
    );
  }

  // ==========================================
  // CLASSROOM OWNER: ENHANCED ADMIN DASHBOARD
  // ==========================================
  return (
    <section className="mt-6 text-[#E1E0CC]">
      {/* Dashboard Top Header */}
      <div className="flex flex-col gap-4 border-b border-primary/20 pb-6 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary/80">Classroom Administration</p>
          <h2 className="mt-1 text-2xl md:text-3xl font-semibold tracking-tight text-[#E1E0CC]">
            People & Permissions
          </h2>
          <p className="mt-1 text-sm text-[#D7D1B5]">
            Manage student enrollments, assistant teachers, classroom-specific roles, and invitations.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-black transition-all hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary/50 shadow-sm"
          >
            <Plus size={16} strokeWidth={2.5} />
            <span>Add Member</span>
          </button>
        </div>
      </div>

      {/* Global Notice / Error Alerts */}
      {error && (
        <div role="alert" className="mt-4 flex items-center justify-between rounded-lg border border-red-500/40 bg-red-950/40 p-3.5 text-sm text-red-200">
          <span>{error}</span>
          <button onClick={() => setError("")} className="text-red-300 hover:text-white" aria-label="Dismiss error">
            <X size={16} />
          </button>
        </div>
      )}

      {notice && (
        <div role="status" className="mt-4 flex items-center justify-between rounded-lg border border-emerald-500/40 bg-emerald-950/30 p-3.5 text-sm text-emerald-200">
          <span className="flex items-center gap-2">
            <Check size={16} className="text-emerald-400" />
            {notice}
          </span>
          <button onClick={() => setNotice("")} className="text-emerald-300 hover:text-white" aria-label="Dismiss notice">
            <X size={16} />
          </button>
        </div>
      )}

      {/* Stats Cards & Join Code Section */}
      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Total Members */}
        <div className="rounded-xl border border-primary/20 bg-black/40 p-4 shadow-sm backdrop-blur-md">
          <div className="flex items-center justify-between text-primary/70">
            <span className="text-xs uppercase tracking-wider font-medium">Total Members</span>
            <Users size={18} className="text-primary" />
          </div>
          <p className="mt-2 text-2xl font-bold text-[#E1E0CC]">{counts.total}</p>
          <span className="mt-1 block text-xs text-[#D7D1B5]/70">In this classroom</span>
        </div>

        {/* Students */}
        <div className="rounded-xl border border-primary/20 bg-black/40 p-4 shadow-sm backdrop-blur-md">
          <div className="flex items-center justify-between text-emerald-400/80">
            <span className="text-xs uppercase tracking-wider font-medium">Students</span>
            <GraduationCap size={18} className="text-emerald-400" />
          </div>
          <p className="mt-2 text-2xl font-bold text-emerald-300">{counts.students}</p>
          <span className="mt-1 block text-xs text-[#D7D1B5]/70">Learners enrolled</span>
        </div>

        {/* Assistant Teachers */}
        <div className="rounded-xl border border-primary/20 bg-black/40 p-4 shadow-sm backdrop-blur-md">
          <div className="flex items-center justify-between text-purple-400/80">
            <span className="text-xs uppercase tracking-wider font-medium">Assistant Teachers</span>
            <ShieldCheck size={18} className="text-purple-400" />
          </div>
          <p className="mt-2 text-2xl font-bold text-purple-300">{counts.assistants}</p>
          <span className="mt-1 block text-xs text-[#D7D1B5]/70">Classroom staff</span>
        </div>

        {/* Join Code Card */}
        <div className="rounded-xl border border-primary/25 bg-primary/10 p-4 shadow-sm">
          <div className="flex items-center justify-between text-primary/90">
            <span className="text-xs uppercase tracking-wider font-semibold">Classroom Code</span>
            <Copy size={16} className="text-primary" />
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span className="font-mono text-2xl font-bold tracking-widest text-primary">
              {joinCode || "------"}
            </span>
            <button
              type="button"
              onClick={handleCopyCode}
              className="inline-flex items-center gap-1.5 rounded-md border border-primary/40 bg-black/50 px-2.5 py-1 text-xs font-medium text-primary hover:bg-black transition-colors"
              title="Copy classroom join code"
            >
              {copiedCode ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
              <span>{copiedCode ? "Copied" : "Copy"}</span>
            </button>
          </div>
          <span className="mt-1 block text-[11px] text-[#D7D1B5]/80">Students join instantly with this code</span>
        </div>
      </div>

      {/* Tabs Navigation */}
      <div className="mt-8 flex flex-wrap items-center gap-2 border-b border-primary/20">
        <button
          type="button"
          onClick={() => setActiveTab("all")}
          className={`flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
            activeTab === "all"
              ? "border-primary text-primary"
              : "border-transparent text-[#D7D1B5] hover:text-white"
          }`}
        >
          <span>All Members</span>
          <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-primary/80">{counts.total}</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("students")}
          className={`flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
            activeTab === "students"
              ? "border-emerald-400 text-emerald-300"
              : "border-transparent text-[#D7D1B5] hover:text-white"
          }`}
        >
          <span>Students</span>
          <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300">{counts.students}</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("assistants")}
          className={`flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
            activeTab === "assistants"
              ? "border-purple-400 text-purple-300"
              : "border-transparent text-[#D7D1B5] hover:text-white"
          }`}
        >
          <span>Assistant Teachers</span>
          <span className="rounded-full bg-purple-500/15 px-2 py-0.5 text-xs text-purple-300">{counts.assistants}</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("owners")}
          className={`flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
            activeTab === "owners"
              ? "border-amber-400 text-amber-300"
              : "border-transparent text-[#D7D1B5] hover:text-white"
          }`}
        >
          <span>Owners</span>
          <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-300">{counts.owners}</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("requests")}
          className={`flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
            activeTab === "requests"
              ? "border-primary text-primary"
              : "border-transparent text-[#D7D1B5] hover:text-white"
          }`}
        >
          <span>Join Requests</span>
          <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-primary/70">0</span>
        </button>
      </div>

      {/* Tab: Join Requests Information View */}
      {activeTab === "requests" ? (
        <div className="mt-8 rounded-xl border border-primary/20 bg-black/40 p-8 text-center backdrop-blur-md">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 text-primary">
            <UserCheck size={28} />
          </div>
          <h3 className="mt-4 text-lg font-semibold text-[#E1E0CC]">No Pending Requests</h3>
          <p className="mx-auto mt-2 max-w-lg text-sm text-[#D7D1B5]">
            Curiosity classrooms use instant enrollment codes. When learners or assistants enter join code{" "}
            <span className="font-mono font-semibold text-primary">{joinCode}</span>, they are immediately enrolled into this classroom without waiting for manual approval.
          </p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
            <button
              type="button"
              onClick={handleCopyCode}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-primary/90"
            >
              {copiedCode ? <Check size={16} /> : <Copy size={16} />}
              <span>{copiedCode ? "Join Code Copied!" : "Copy Classroom Code"}</span>
            </button>
            <button
              type="button"
              onClick={() => setShowAddModal(true)}
              className="inline-flex items-center gap-2 rounded-lg border border-primary/30 bg-black/50 px-4 py-2 text-sm font-medium text-primary hover:bg-black/80 transition-colors"
            >
              <Plus size={16} />
              <span>Directly Add by Email</span>
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* Controls: Search, Filter, Sort */}
          <div className="mt-6 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            {/* Search Input */}
            <div className="relative flex-1 max-w-md">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-primary/60" />
              <input
                type="text"
                placeholder="Search by name or email…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full rounded-lg border border-primary/25 bg-black/40 pl-9 pr-4 py-2 text-sm text-[#E1E0CC] placeholder-primary/40 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-primary/60 hover:text-white"
                  aria-label="Clear search"
                >
                  <X size={14} />
                </button>
              )}
            </div>

            {/* Filter and Sort Selectors */}
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-1.5 text-xs text-[#D7D1B5]">
                <span>Role:</span>
                <select
                  value={roleFilter}
                  onChange={(e) => setRoleFilter(e.target.value)}
                  className="rounded-lg border border-primary/25 bg-black/40 px-3 py-1.5 text-xs text-[#E1E0CC] focus:border-primary focus:outline-none"
                  aria-label="Filter members by role"
                >
                  <option value="ALL">All Roles</option>
                  <option value="OWNER">Classroom Owners</option>
                  <option value="ASSISTANT">Assistant Teachers</option>
                  <option value="STUDENT">Students</option>
                </select>
              </div>

              <div className="flex items-center gap-1.5 text-xs text-[#D7D1B5]">
                <span>Sort:</span>
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as SortKey)}
                  className="rounded-lg border border-primary/25 bg-black/40 px-3 py-1.5 text-xs text-[#E1E0CC] focus:border-primary focus:outline-none"
                  aria-label="Sort members"
                >
                  <option value="newest">Joined (Newest)</option>
                  <option value="oldest">Joined (Oldest)</option>
                  <option value="name_asc">Name (A → Z)</option>
                  <option value="name_desc">Name (Z → A)</option>
                  <option value="role">Role Priority</option>
                </select>
              </div>
            </div>
          </div>

          {/* Members Table */}
          {loading ? (
            <div className="mt-6" aria-busy="true">
              <SkeletonList count={5} />
            </div>
          ) : displayedMembers.length === 0 ? (
            <div className="mt-8 rounded-xl border border-primary/20 bg-black/30 p-10 text-center">
              <Users size={32} className="mx-auto text-primary/40" />
              <h3 className="mt-3 text-base font-medium text-[#E1E0CC]">No members found</h3>
              <p className="mt-1 text-sm text-[#D7D1B5]/70">
                {searchQuery
                  ? `No members match "${searchQuery}". Try a different search.`
                  : "No members in this category yet."}
              </p>
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="mt-4 rounded-md border border-primary/30 px-3 py-1.5 text-xs font-medium text-primary hover:bg-white/10"
                >
                  Reset search
                </button>
              )}
            </div>
          ) : (
            <div className="mt-6 overflow-hidden rounded-xl border border-primary/20 bg-black/40 shadow-sm backdrop-blur-md">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-primary/15 bg-white/[0.02] text-xs font-semibold uppercase tracking-wider text-primary/80">
                    <tr>
                      <th scope="col" className="px-5 py-3.5">Member</th>
                      <th scope="col" className="px-5 py-3.5">Classroom Role</th>
                      <th scope="col" className="px-5 py-3.5 hidden md:table-cell">Account Status</th>
                      <th scope="col" className="px-5 py-3.5 hidden sm:table-cell">Joined Date</th>
                      <th scope="col" className="px-5 py-3.5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-primary/10">
                    {displayedMembers.map((member) => {
                      const isCurrentUser = member.userId === user?.id;
                      const isOwnerRole = (member.role || "").toUpperCase() === "OWNER";
                      const canChangeRole = !(isCurrentUser && isOwnerRole && counts.owners <= 1);
                      const canRemove = !isOwnerRole;

                      return (
                        <tr key={member.userId} className="hover:bg-white/[0.02] transition-colors">
                          {/* Member info */}
                          <td className="px-5 py-4">
                            <div className="flex items-center gap-3">
                              {member.picture ? (
                                <img
                                  src={member.picture}
                                  alt=""
                                  className="h-10 w-10 flex-shrink-0 rounded-full object-cover ring-1 ring-primary/30"
                                />
                              ) : (
                                <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-primary/15 text-sm font-semibold text-primary ring-1 ring-primary/25">
                                  {(member.name || "U").charAt(0).toUpperCase()}
                                </div>
                              )}
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="font-medium text-[#E1E0CC] truncate">{member.name || "Learner"}</span>
                                  {isCurrentUser && (
                                    <span className="rounded bg-primary/20 px-1.5 py-0.2 text-[10px] font-semibold text-primary">
                                      You
                                    </span>
                                  )}
                                  {isOwnerRole && (
                                    <span className="rounded bg-amber-500/20 px-1.5 py-0.2 text-[10px] font-semibold text-amber-300">
                                      Owner
                                    </span>
                                  )}
                                </div>
                                <div className="flex items-center gap-1.5 text-xs text-primary/70 mt-0.5">
                                  <Mail size={12} className="flex-shrink-0 text-primary/50" />
                                  <span className="truncate">{member.email || "No email"}</span>
                                </div>
                              </div>
                            </div>
                          </td>

                          {/* Classroom Role Selector / Display */}
                          <td className="px-5 py-4">
                            <div className="flex items-center gap-2">
                              <select
                                aria-label={`Classroom role for ${member.name}`}
                                value={(member.role || "STUDENT").toUpperCase()}
                                disabled={!canChangeRole}
                                onChange={(e) => {
                                  const targetRole = e.target.value as "STUDENT" | "ASSISTANT" | "OWNER";
                                  promptRoleChange(member, targetRole);
                                }}
                                className={`rounded-lg border px-2.5 py-1.5 text-xs font-medium focus:outline-none focus:ring-1 ${getRoleBadgeClasses(
                                  member.role
                                )} bg-black/60 cursor-pointer disabled:cursor-not-allowed disabled:opacity-70`}
                              >
                                <option value="STUDENT" className="bg-[#18181b] text-emerald-300">
                                  Student
                                </option>
                                <option value="ASSISTANT" className="bg-[#18181b] text-purple-300">
                                  Assistant Teacher
                                </option>
                                <option value="OWNER" className="bg-[#18181b] text-amber-300">
                                  Classroom Owner
                                </option>
                              </select>
                            </div>
                          </td>

                          {/* Account Status */}
                          <td className="px-5 py-4 hidden md:table-cell">
                            <div className="flex items-center gap-1.5 text-xs text-[#D7D1B5]">
                              <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-sm" />
                              <span>{member.status || "Active"}</span>
                            </div>
                          </td>

                          {/* Joined Date */}
                          <td className="px-5 py-4 text-xs text-[#D7D1B5]/80 hidden sm:table-cell">
                            {formatDate(member.joinedAt)}
                          </td>

                          {/* Action Buttons */}
                          <td className="px-5 py-4 text-right">
                            <div className="flex items-center justify-end gap-1.5">
                              {/* View Details */}
                              <button
                                type="button"
                                onClick={() => setDetailMember(member)}
                                className="rounded p-1.5 text-primary/80 hover:bg-white/10 hover:text-white transition-colors"
                                title="View member details"
                                aria-label={`View details for ${member.name}`}
                              >
                                <Eye size={16} />
                              </button>

                              {/* Remove Member */}
                              <button
                                type="button"
                                disabled={!canRemove}
                                onClick={() => {
                                  setRemoveTarget(member);
                                  setRemoveError("");
                                }}
                                className="rounded p-1.5 text-red-300/80 hover:bg-red-950/40 hover:text-red-200 transition-colors disabled:opacity-30 disabled:hover:bg-transparent disabled:cursor-not-allowed"
                                title={
                                  canRemove
                                    ? `Remove ${member.name} from classroom`
                                    : "Classroom owner cannot be removed"
                                }
                                aria-label={`Remove ${member.name} from classroom`}
                              >
                                <Trash2 size={16} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {/* ========================================================= */}
      {/* ADD MEMBER MODAL                                          */}
      {/* ========================================================= */}
      {showAddModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !addingMember) setShowAddModal(false);
          }}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-primary/30 bg-[#161614] p-6 text-[#E1E0CC] shadow-2xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="add-member-title"
          >
            <div className="flex items-center justify-between border-b border-primary/15 pb-4">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/15 text-primary">
                  <Plus size={18} />
                </div>
                <h3 id="add-member-title" className="text-lg font-semibold text-[#E1E0CC]">
                  Add Classroom Member
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                disabled={addingMember}
                className="text-primary/60 hover:text-white"
                aria-label="Close add member dialog"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleAddMember} className="mt-4 space-y-4">
              {addError && (
                <div role="alert" className="rounded-lg border border-red-500/40 bg-red-950/40 p-3 text-xs text-red-200">
                  {addError}
                </div>
              )}

              <div>
                <label htmlFor="add-member-email" className="block text-xs font-medium uppercase text-primary/80">
                  User Email Address
                </label>
                <input
                  id="add-member-email"
                  type="email"
                  required
                  placeholder="e.g. learner@example.com"
                  value={addEmail}
                  onChange={(e) => setAddEmail(e.target.value)}
                  className="mt-1.5 w-full rounded-lg border border-primary/25 bg-black/50 px-3.5 py-2.5 text-sm text-[#E1E0CC] placeholder-primary/40 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>

              <div>
                <label htmlFor="add-member-role" className="block text-xs font-medium uppercase text-primary/80">
                  Assign Classroom Role
                </label>
                <select
                  id="add-member-role"
                  value={addRole}
                  onChange={(e) => setAddRole(e.target.value as "STUDENT" | "ASSISTANT")}
                  className="mt-1.5 w-full rounded-lg border border-primary/25 bg-black/50 px-3.5 py-2.5 text-sm text-[#E1E0CC] focus:border-primary focus:outline-none"
                >
                  <option value="STUDENT">Student (Standard learning access)</option>
                  <option value="ASSISTANT">Assistant Teacher (Course co-management)</option>
                </select>
              </div>

              <div className="rounded-lg border border-primary/15 bg-white/[0.02] p-3 text-xs text-[#D7D1B5]/80">
                <div className="flex items-start gap-2">
                  <Info size={16} className="mt-0.5 flex-shrink-0 text-primary/70" />
                  <p>
                    The user must have an active Curiosity account. Alternatively, they can join independently using this classroom's join code:{" "}
                    <span className="font-mono font-semibold text-primary">{joinCode}</span>.
                  </p>
                </div>
              </div>

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  disabled={addingMember}
                  className="rounded-lg border border-primary/25 px-4 py-2 text-sm text-[#D7D1B5] hover:bg-white/5"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={addingMember}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-black hover:bg-primary/90 disabled:opacity-50"
                >
                  {addingMember && <LoaderCircle size={15} className="animate-spin" />}
                  <span>{addingMember ? "Adding member…" : "Add to Classroom"}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* ROLE CHANGE CONFIRMATION DIALOG                          */}
      {/* ========================================================= */}
      {roleChangeTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !updatingRole) setRoleChangeTarget(null);
          }}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-primary/30 bg-[#161614] p-6 text-[#E1E0CC] shadow-2xl"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="role-change-title"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/20 text-amber-300">
                <Shield size={20} />
              </div>
              <div>
                <h3 id="role-change-title" className="text-lg font-semibold text-[#E1E0CC]">
                  Change Classroom Role
                </h3>
                <p className="text-xs text-primary/70">Modify member permissions</p>
              </div>
            </div>

            <div className="mt-4 space-y-3">
              {roleChangeError && (
                <div role="alert" className="rounded-lg border border-red-500/40 bg-red-950/40 p-3 text-xs text-red-200">
                  {roleChangeError}
                </div>
              )}

              <p className="text-sm text-[#D7D1B5]">
                Are you sure you want to change the classroom role for <strong className="text-white">{roleChangeTarget.name}</strong>?
              </p>

              <div className="rounded-xl border border-primary/20 bg-black/40 p-3.5 space-y-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-[#D7D1B5]/70">Current Role:</span>
                  <span className={`px-2 py-0.5 rounded font-medium border ${getRoleBadgeClasses(roleChangeTarget.role)}`}>
                    {getRoleLabel(roleChangeTarget.role)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[#D7D1B5]/70">New Role:</span>
                  <span className={`px-2 py-0.5 rounded font-medium border ${getRoleBadgeClasses(newRoleSelection)}`}>
                    {getRoleLabel(newRoleSelection)}
                  </span>
                </div>
              </div>

              <p className="text-xs text-[#D7D1B5]/70 italic">
                * Note: This change applies ONLY to this classroom and does not alter their platform-wide Curiosity account role.
              </p>
            </div>

            <div className="mt-6 flex items-center justify-end gap-3 border-t border-primary/15 pt-4">
              <button
                type="button"
                onClick={() => setRoleChangeTarget(null)}
                disabled={updatingRole}
                className="rounded-lg border border-primary/25 px-4 py-2 text-sm text-[#D7D1B5] hover:bg-white/5"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmRoleChange}
                disabled={updatingRole}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-black hover:bg-primary/90 disabled:opacity-50"
              >
                {updatingRole && <LoaderCircle size={15} className="animate-spin" />}
                <span>{updatingRole ? "Saving role…" : "Confirm Role Change"}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* REMOVE MEMBER CONFIRMATION DIALOG                         */}
      {/* ========================================================= */}
      {removeTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !removingMember) setRemoveTarget(null);
          }}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-red-500/40 bg-[#161614] p-6 text-[#E1E0CC] shadow-2xl"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="remove-member-title"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-500/20 text-red-300">
                <AlertTriangle size={20} />
              </div>
              <div>
                <h3 id="remove-member-title" className="text-lg font-semibold text-red-100">
                  Remove Member from Classroom?
                </h3>
                <p className="text-xs text-red-300/70">Revoke classroom access</p>
              </div>
            </div>

            <div className="mt-4 space-y-3">
              {removeError && (
                <div role="alert" className="rounded-lg border border-red-500/40 bg-red-950/40 p-3 text-xs text-red-200">
                  {removeError}
                </div>
              )}

              <p className="text-sm text-[#D7D1B5]">
                Are you sure you want to remove <strong className="text-white">{removeTarget.name}</strong> from{" "}
                <strong className="text-white">{classroom.name}</strong>?
              </p>

              <div className="rounded-xl border border-red-500/20 bg-red-950/20 p-3.5 text-xs text-red-200/90 leading-relaxed">
                <strong>Important:</strong> Removing this user will revoke their enrollment in this classroom only. Their Curiosity account, assignments, and memberships in other classrooms remain completely untouched.
              </div>
            </div>

            <div className="mt-6 flex items-center justify-end gap-3 border-t border-primary/15 pt-4">
              <button
                type="button"
                onClick={() => setRemoveTarget(null)}
                disabled={removingMember}
                className="rounded-lg border border-primary/25 px-4 py-2 text-sm text-[#D7D1B5] hover:bg-white/5"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmRemoveMember}
                disabled={removingMember}
                className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-500 disabled:opacity-50"
              >
                {removingMember && <LoaderCircle size={15} className="animate-spin" />}
                <Trash2 size={15} />
                <span>{removingMember ? "Removing…" : "Remove Member"}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MEMBER DETAILS MODAL                                      */}
      {/* ========================================================= */}
      {detailMember && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setDetailMember(null);
          }}
        >
          <div
            className="w-full max-w-lg rounded-2xl border border-primary/30 bg-[#161614] p-6 text-[#E1E0CC] shadow-2xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="member-details-title"
          >
            <div className="flex items-center justify-between border-b border-primary/15 pb-4">
              <div className="flex items-center gap-3">
                {detailMember.picture ? (
                  <img
                    src={detailMember.picture}
                    alt=""
                    className="h-12 w-12 rounded-full object-cover ring-2 ring-primary/40"
                  />
                ) : (
                  <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/20 text-lg font-bold text-primary ring-2 ring-primary/30">
                    {(detailMember.name || "U").charAt(0).toUpperCase()}
                  </div>
                )}
                <div>
                  <h3 id="member-details-title" className="text-lg font-semibold text-[#E1E0CC]">
                    {detailMember.name || "Class Member"}
                  </h3>
                  <p className="text-xs text-primary/70">{detailMember.email || "No email"}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setDetailMember(null)}
                className="text-primary/60 hover:text-white"
                aria-label="Close member details"
              >
                <X size={20} />
              </button>
            </div>

            <div className="mt-5 space-y-4">
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="rounded-xl border border-primary/15 bg-black/40 p-3">
                  <span className="text-[#D7D1B5]/70 block font-medium">Classroom Role</span>
                  <span className={`mt-1 inline-block px-2 py-0.5 rounded font-semibold border ${getRoleBadgeClasses(detailMember.role)}`}>
                    {getRoleLabel(detailMember.role)}
                  </span>
                </div>

                <div className="rounded-xl border border-primary/15 bg-black/40 p-3">
                  <span className="text-[#D7D1B5]/70 block font-medium">Platform Account Role</span>
                  <span className="mt-1 inline-block px-2 py-0.5 rounded font-semibold border border-primary/25 bg-primary/10 text-primary">
                    {detailMember.userRole || "STUDENT"}
                  </span>
                </div>

                <div className="rounded-xl border border-primary/15 bg-black/40 p-3">
                  <span className="text-[#D7D1B5]/70 block font-medium">Date Joined</span>
                  <span className="mt-1 block font-medium text-[#E1E0CC]">
                    {formatDate(detailMember.joinedAt)}
                  </span>
                </div>

                <div className="rounded-xl border border-primary/15 bg-black/40 p-3">
                  <span className="text-[#D7D1B5]/70 block font-medium">Status</span>
                  <span className="mt-1 flex items-center gap-1.5 font-medium text-emerald-300">
                    <span className="h-2 w-2 rounded-full bg-emerald-400" />
                    {detailMember.status || "Active"}
                  </span>
                </div>
              </div>

              <div className="rounded-xl border border-primary/15 bg-black/30 p-3.5 text-xs text-[#D7D1B5]">
                <span className="block font-medium text-primary/80">User ID</span>
                <span className="mt-1 block font-mono text-[11px] text-[#D7D1B5]/80 select-all">
                  {detailMember.userId}
                </span>
              </div>
            </div>

            <div className="mt-6 flex justify-end border-t border-primary/15 pt-4">
              <button
                type="button"
                onClick={() => setDetailMember(null)}
                className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-black hover:bg-primary/90"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
