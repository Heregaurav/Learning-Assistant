import { FormEvent, MouseEvent as ReactMouseEvent, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  Clock,
  Download,
  ExternalLink,
  Eye,
  File,
  FileSpreadsheet,
  FileText,
  Film,
  Image as ImageIcon,
  LoaderCircle,
  Maximize2,
  Minus,
  Pause,
  Pencil,
  Play,
  Plus,
  RotateCcw,
  RotateCw,
  Search,
  Sliders,
  Trash2,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import {
  createClassroomLecture,
  deleteClassroomLecture,
  deleteClassroomMaterial,
  getClassroomLectures,
  getClassroomMaterials,
  getMaterialDownloadUrl,
  getMaterialViewUrl,
  recordLectureProgress,
  updateClassroomLecture,
  updateClassroomMaterial,
  uploadClassroomMaterial,
  validateLectureUrl,
} from "../lib/api";
import type { ClassroomLecture, ClassroomMaterial, Role } from "../types";

declare global {
  interface Window {
    YT?: any;
    onYouTubeIframeAPIReady?: () => void;
  }
}

type Props = {
  classroomId: string;
  canEdit: boolean;
  user: { id: string; role?: Role } | null;
};

const PLAYBACK_SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];

function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return "Duration unspecified";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h}h ${m > 0 ? `${m}m` : ""}`.trim();
  }
  if (m > 0) {
    return `${m} min${s > 0 ? ` ${s}s` : ""}`;
  }
  return `${s}s`;
}

function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

function getFileIcon(filename: string, fileType: string) {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  if (["pdf"].includes(ext) || fileType.includes("pdf")) {
    return <FileText className="text-red-400" size={20} />;
  }
  if (["doc", "docx"].includes(ext) || fileType.includes("word")) {
    return <FileText className="text-blue-400" size={20} />;
  }
  if (["ppt", "pptx"].includes(ext) || fileType.includes("presentation")) {
    return <FileSpreadsheet className="text-orange-400" size={20} />;
  }
  if (["png", "jpg", "jpeg", "webp", "gif"].includes(ext) || fileType.includes("image")) {
    return <ImageIcon className="text-emerald-400" size={20} />;
  }
  return <File className="text-primary" size={20} />;
}

export default function ClassroomLectures({ classroomId, canEdit, user }: Props) {
  const [activeSection, setActiveSection] = useState<"lectures" | "materials">("lectures");
  const [lectures, setLectures] = useState<ClassroomLecture[]>([]);
  const [materials, setMaterials] = useState<ClassroomMaterial[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Material Upload & Edit Modals
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadDesc, setUploadDesc] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [editingMaterial, setEditingMaterial] = useState<ClassroomMaterial | null>(null);
  const [materialDeleteTarget, setMaterialDeleteTarget] = useState<ClassroomMaterial | null>(null);
  const [materialSearch, setMaterialSearch] = useState("");
  const [viewingMaterial, setViewingMaterial] = useState<ClassroomMaterial | null>(null);

  // Lecture Add & Edit Modals
  const [showLectureModal, setShowLectureModal] = useState(false);
  const [lectureTitle, setLectureTitle] = useState("");
  const [lectureDesc, setLectureDesc] = useState("");
  const [lectureUrl, setLectureUrl] = useState("");
  const [lectureMinutes, setLectureMinutes] = useState("60");
  const [lectureThreshold, setLectureThreshold] = useState("100");
  const [savingLecture, setSavingLecture] = useState(false);
  const [urlValidation, setUrlValidation] = useState<{
    valid: boolean;
    platform: string;
    embedUrl: string;
    trackingSupported: boolean;
    durationSeconds?: number;
    durationMinutes?: number;
    suggestedTitle?: string;
    message: string;
  } | null>(null);
  const [editingLecture, setEditingLecture] = useState<ClassroomLecture | null>(null);
  const [lectureDeleteTarget, setLectureDeleteTarget] = useState<ClassroomLecture | null>(null);

  // Active Playing Lecture
  const [playingLecture, setPlayingLecture] = useState<ClassroomLecture | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const [lecList, matList] = await Promise.all([
        getClassroomLectures(classroomId),
        getClassroomMaterials(classroomId),
      ]);
      setLectures(lecList);
      setMaterials(matList);
    } catch (err: any) {
      setError(err?.message || "Failed to load classroom lectures and materials.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, [classroomId]);

  // Handle URL changes with live preview validation and auto-duration detection
  useEffect(() => {
    if (!lectureUrl.trim()) {
      setUrlValidation(null);
      return;
    }
    const timer = setTimeout(() => {
      validateLectureUrl(classroomId, lectureUrl.trim())
        .then((res) => {
          setUrlValidation(res);
          if (res.durationMinutes && res.durationMinutes > 0) {
            setLectureMinutes(String(res.durationMinutes));
          }
          if (res.suggestedTitle && !lectureTitle.trim()) {
            setLectureTitle(res.suggestedTitle);
          }
        })
        .catch(() => setUrlValidation(null));
    }, 350);
    return () => clearTimeout(timer);
  }, [lectureUrl, classroomId]);

  // Handle Material Upload
  const handleUploadMaterial = async (e: FormEvent) => {
    e.preventDefault();
    if (!uploadFile) {
      setError("Please select a file to upload.");
      return;
    }
    setUploading(true);
    setError("");
    try {
      await uploadClassroomMaterial(classroomId, uploadTitle, uploadDesc, uploadFile);
      setNotice(`"${uploadTitle || uploadFile.name}" uploaded successfully.`);
      setShowUploadModal(false);
      setUploadTitle("");
      setUploadDesc("");
      setUploadFile(null);
      const updated = await getClassroomMaterials(classroomId);
      setMaterials(updated);
    } catch (err: any) {
      setError(err?.message || "Failed to upload study material.");
    } finally {
      setUploading(false);
    }
  };

  // Handle Material Update
  const handleUpdateMaterial = async (e: FormEvent) => {
    e.preventDefault();
    if (!editingMaterial) return;
    setUploading(true);
    setError("");
    try {
      await updateClassroomMaterial(classroomId, editingMaterial.id, {
        title: editingMaterial.title,
        description: editingMaterial.description,
      });
      setNotice("Material updated successfully.");
      setEditingMaterial(null);
      const updated = await getClassroomMaterials(classroomId);
      setMaterials(updated);
    } catch (err: any) {
      setError(err?.message || "Failed to update study material.");
    } finally {
      setUploading(false);
    }
  };

  // Handle Material Delete
  const handleDeleteMaterial = async () => {
    if (!materialDeleteTarget) return;
    try {
      await deleteClassroomMaterial(classroomId, materialDeleteTarget.id);
      setNotice(`"${materialDeleteTarget.title}" deleted.`);
      setMaterialDeleteTarget(null);
      setMaterials((prev) => prev.filter((m) => m.id !== materialDeleteTarget.id));
    } catch (err: any) {
      setError(err?.message || "Failed to delete study material.");
    }
  };

  // Handle Lecture Create or Edit
  const handleSaveLecture = async (e: FormEvent) => {
    e.preventDefault();
    if (!lectureTitle.trim() || !lectureUrl.trim()) {
      setError("Lecture title and video URL are required.");
      return;
    }
    setSavingLecture(true);
    setError("");
    const durationSeconds = Math.max(0, Math.round((parseFloat(lectureMinutes) || 0) * 60));
    const threshold = Math.max(1, Math.min(100, parseInt(lectureThreshold, 10) || 100));

    try {
      if (editingLecture) {
        await updateClassroomLecture(classroomId, editingLecture.id, {
          title: lectureTitle.trim(),
          description: lectureDesc.trim(),
          videoUrl: lectureUrl.trim(),
          durationSeconds,
          completionThreshold: threshold,
        });
        setNotice(`Lecture "${lectureTitle}" updated successfully.`);
      } else {
        await createClassroomLecture(classroomId, {
          title: lectureTitle.trim(),
          description: lectureDesc.trim(),
          videoUrl: lectureUrl.trim(),
          durationSeconds,
          completionThreshold: threshold,
        });
        setNotice(`Lecture "${lectureTitle}" published successfully.`);
      }
      setShowLectureModal(false);
      setEditingLecture(null);
      setLectureTitle("");
      setLectureDesc("");
      setLectureUrl("");
      setLectureMinutes("60");
      setLectureThreshold("100");
      const updated = await getClassroomLectures(classroomId);
      setLectures(updated);
    } catch (err: any) {
      setError(err?.message || "Failed to save lecture.");
    } finally {
      setSavingLecture(false);
    }
  };

  // Handle Lecture Delete
  const handleDeleteLecture = async () => {
    if (!lectureDeleteTarget) return;
    try {
      await deleteClassroomLecture(classroomId, lectureDeleteTarget.id);
      setNotice(`Lecture "${lectureDeleteTarget.title}" deleted.`);
      setLectureDeleteTarget(null);
      setLectures((prev) => prev.filter((l) => l.id !== lectureDeleteTarget.id));
    } catch (err: any) {
      setError(err?.message || "Failed to delete lecture.");
    }
  };

  const openEditLectureModal = (lec: ClassroomLecture) => {
    setEditingLecture(lec);
    setLectureTitle(lec.title);
    setLectureDesc(lec.description || "");
    setLectureUrl(lec.videoUrl);
    setLectureMinutes(String(Math.round(lec.durationSeconds / 60) || 0));
    setLectureThreshold(String(lec.completionThreshold || 100));
    setShowLectureModal(true);
  };

  const filteredMaterials = materials.filter(
    (m) =>
      m.title.toLowerCase().includes(materialSearch.toLowerCase()) ||
      m.filename.toLowerCase().includes(materialSearch.toLowerCase()) ||
      m.description.toLowerCase().includes(materialSearch.toLowerCase()),
  );

  return (
    <div className="mt-6 text-[#f2efe8]">
      {/* Sub-navigation tabs: Lectures & Study Materials */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-primary/20 pb-3">
        <div className="flex items-center gap-2" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={activeSection === "lectures"}
            onClick={() => setActiveSection("lectures")}
            className={`inline-flex items-center gap-2 border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
              activeSection === "lectures"
                ? "border-primary text-primary"
                : "border-transparent text-[#D7D1B5] hover:text-primary"
            }`}
          >
            <Film size={16} /> Lecture Videos ({lectures.length})
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeSection === "materials"}
            onClick={() => setActiveSection("materials")}
            className={`inline-flex items-center gap-2 border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
              activeSection === "materials"
                ? "border-primary text-primary"
                : "border-transparent text-[#D7D1B5] hover:text-primary"
            }`}
          >
            <FileText size={16} /> Study Materials ({materials.length})
          </button>
        </div>

        {/* Action Buttons for Teachers */}
        {canEdit && (
          <div className="flex items-center gap-2">
            {activeSection === "lectures" ? (
              <button
                type="button"
                onClick={() => {
                  setEditingLecture(null);
                  setLectureTitle("");
                  setLectureDesc("");
                  setLectureUrl("");
                  setLectureMinutes("60");
                  setLectureThreshold("100");
                  setUrlValidation(null);
                  setShowLectureModal(true);
                }}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-3.5 py-2 text-xs font-semibold text-black transition-opacity hover:opacity-90"
              >
                <Plus size={15} /> Add Lecture
              </button>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setUploadTitle("");
                  setUploadDesc("");
                  setUploadFile(null);
                  setShowUploadModal(true);
                }}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-3.5 py-2 text-xs font-semibold text-black transition-opacity hover:opacity-90"
              >
                <Plus size={15} /> Upload Material
              </button>
            )}
          </div>
        )}
      </div>

      {/* Global Alerts */}
      {error && (
        <div role="alert" className="mt-4 rounded-lg border border-red-400/40 bg-red-950/40 p-3 text-sm text-red-100 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError("")} className="text-red-300 hover:text-white"><X size={16} /></button>
        </div>
      )}
      {notice && (
        <div role="status" className="mt-4 rounded-lg border border-emerald-400/30 bg-emerald-950/40 p-3 text-sm text-emerald-200 flex items-center justify-between">
          <span>{notice}</span>
          <button onClick={() => setNotice("")} className="text-emerald-300 hover:text-white"><X size={16} /></button>
        </div>
      )}

      {loading ? (
        <div className="mt-12 flex flex-col items-center justify-center gap-3 py-16 text-primary/70">
          <LoaderCircle size={28} className="animate-spin" />
          <p className="text-sm">Loading classroom resources…</p>
        </div>
      ) : activeSection === "lectures" ? (
        <div className="mt-6">
          {lectures.length === 0 ? (
            <div className="rounded-lg border border-primary/20 bg-black/40 p-8 text-center">
              <Film size={36} className="mx-auto text-primary/50" />
              <h3 className="mt-3 text-base font-semibold text-[#f2efe8]">No lectures shared yet</h3>
              <p className="mt-1 text-sm text-[#D7D1B5]">
                {canEdit
                  ? "Click 'Add Lecture' above to share recorded lectures with your students."
                  : "No lecture videos have been shared in this classroom yet."}
              </p>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {lectures.map((lecture, index) => {
                const prog = lecture.progress;
                const percent = Math.round(prog?.watchPercent || 0);
                const isCompleted = prog?.completed || (prog?.status === "completed");
                const isInProgress = !isCompleted && percent > 0;

                return (
                  <article
                    key={lecture.id}
                    className="group relative flex flex-col justify-between rounded-lg border border-primary/25 bg-black/80 p-5 shadow-lg transition-all hover:border-primary/60 hover:bg-black/95"
                  >
                    <div>
                      {/* Card Header & Badges */}
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-[11px] font-mono tracking-wider text-primary/70 uppercase">
                          Lecture {lecture.position || index + 1}
                        </span>
                        <div className="flex items-center gap-2">
                          {isCompleted ? (
                            <span className="inline-flex items-center gap-1 rounded bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-300 border border-emerald-500/30">
                              <CheckCircle2 size={11} /> Complete
                            </span>
                          ) : isInProgress ? (
                            <span className="inline-flex items-center gap-1 rounded bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-300 border border-amber-500/30">
                              <Clock size={11} /> {percent}%
                            </span>
                          ) : (
                            <span className="rounded bg-white/5 px-2 py-0.5 text-[10px] font-medium text-[#c9c4b5] border border-white/10">
                              Not started
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Lecture Title */}
                      <h3 className="mt-2 text-base font-semibold leading-snug text-[#f2efe8] group-hover:text-primary transition-colors">
                        {lecture.title}
                      </h3>

                      {/* Description */}
                      {lecture.description && (
                        <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-[#c9c4b5]">
                          {lecture.description}
                        </p>
                      )}

                      {/* Metadata: Duration & Threshold */}
                      <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-primary/75">
                        <span className="inline-flex items-center gap-1">
                          <Clock size={13} /> {formatDuration(lecture.durationSeconds)}
                        </span>
                        {canEdit && (
                          <span className="rounded border border-primary/20 bg-primary/5 px-1.5 py-0.5 text-[10px]">
                            Threshold: {lecture.completionThreshold}%
                          </span>
                        )}
                        {!lecture.trackingSupported && (
                          <span className="text-[10px] text-amber-300/80" title="Automatic progress tracking unavailable for this source">
                            (Preview only)
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Progress Bar & Actions */}
                    <div className="mt-5 border-t border-primary/15 pt-3">
                      {!canEdit && (
                        <div className="mb-3">
                          <div className="flex justify-between text-[11px] text-[#c9c4b5] mb-1">
                            <span>Watch Progress</span>
                            <span>{percent}%</span>
                          </div>
                          <div className="h-1.5 w-full overflow-hidden rounded bg-white/10">
                            <div
                              className={`h-full transition-all duration-300 ${
                                isCompleted ? "bg-emerald-400" : "bg-primary"
                              }`}
                              style={{ width: `${percent}%` }}
                            />
                          </div>
                        </div>
                      )}

                      <div className="flex items-center justify-between gap-2">
                        <button
                          type="button"
                          onClick={() => setPlayingLecture(lecture)}
                          className="inline-flex flex-1 items-center justify-center gap-2 rounded-md bg-primary/15 px-3 py-2 text-xs font-medium text-primary border border-primary/30 transition-colors hover:bg-primary hover:text-black"
                        >
                          <Play size={13} fill="currentColor" /> Watch Lecture
                        </button>

                        {canEdit && (
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => openEditLectureModal(lecture)}
                              className="rounded p-1.5 text-primary/80 hover:bg-white/10 hover:text-primary"
                              title="Edit lecture"
                              aria-label="Edit lecture"
                            >
                              <Pencil size={14} />
                            </button>
                            <button
                              type="button"
                              onClick={() => setLectureDeleteTarget(lecture)}
                              className="rounded p-1.5 text-red-300/80 hover:bg-red-950/40 hover:text-red-200"
                              title="Delete lecture"
                              aria-label="Delete lecture"
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        <div className="mt-6">
          {/* Search bar */}
          <div className="mb-4 flex items-center gap-3">
            <div className="relative flex-1 max-w-md">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-primary/60" />
              <input
                type="text"
                placeholder="Search notes and materials…"
                value={materialSearch}
                onChange={(e) => setMaterialSearch(e.target.value)}
                className="w-full rounded-lg border border-primary/25 bg-black/40 pl-9 pr-3 py-2 text-sm text-[#f2efe8] placeholder:text-primary/40 focus:border-primary focus:outline-none"
              />
            </div>
            <span className="text-xs text-primary/70">{filteredMaterials.length} materials</span>
          </div>

          {filteredMaterials.length === 0 ? (
            <div className="rounded-lg border border-primary/20 bg-black/40 p-8 text-center">
              <FileText size={36} className="mx-auto text-primary/50" />
              <h3 className="mt-3 text-base font-semibold text-[#f2efe8]">No materials found</h3>
              <p className="mt-1 text-sm text-[#D7D1B5]">
                {canEdit
                  ? "Click 'Upload Material' to share PDFs, presentations, documents, or images with your students."
                  : "No study materials or notes have been shared yet."}
              </p>
            </div>
          ) : (
            <div className="divide-y divide-primary/15 border-y border-primary/15">
              {filteredMaterials.map((mat) => (
                <div key={mat.id} className="flex flex-wrap items-center justify-between gap-4 py-3.5">
                  <div className="flex items-start gap-3 min-w-0 flex-1">
                    <button
                      type="button"
                      onClick={() => setViewingMaterial(mat)}
                      className="mt-0.5 shrink-0 rounded bg-white/5 p-2 border border-primary/15 hover:border-primary/50 hover:bg-primary/10 transition-colors"
                      title="Click to view material"
                    >
                      {getFileIcon(mat.filename, mat.fileType)}
                    </button>
                    <div className="min-w-0">
                      <h4
                        onClick={() => setViewingMaterial(mat)}
                        className="truncate text-sm font-medium text-[#f2efe8] cursor-pointer hover:text-primary transition-colors"
                        title="Click to view material"
                      >
                        {mat.title}
                      </h4>
                      {mat.description && (
                        <p className="mt-0.5 line-clamp-1 text-xs text-[#c9c4b5]">{mat.description}</p>
                      )}
                      <div className="mt-1 flex flex-wrap items-center gap-3 text-[11px] text-primary/65">
                        <span>{mat.filename}</span>
                        <span>·</span>
                        <span>{formatBytes(mat.fileSize)}</span>
                        {mat.uploadedByName && (
                          <>
                            <span>·</span>
                            <span>Uploaded by {mat.uploadedByName}</span>
                          </>
                        )}
                        {mat.createdAt && (
                          <>
                            <span>·</span>
                            <span>{new Date(mat.createdAt).toLocaleDateString()}</span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={() => setViewingMaterial(mat)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/20 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary hover:text-black transition-colors"
                      title="View file on screen without downloading"
                    >
                      <Eye size={13} /> View
                    </button>

                    <a
                      href={getMaterialDownloadUrl(classroomId, mat.id)}
                      download={mat.filename}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs font-medium text-[#c9c4b5] hover:bg-white/10 hover:text-white transition-colors"
                      target="_blank"
                      rel="noopener noreferrer"
                      title="Download file to computer"
                    >
                      <Download size={13} /> Download
                    </a>

                    {canEdit && (
                      <>
                        <button
                          type="button"
                          onClick={() => setEditingMaterial(mat)}
                          className="rounded p-1.5 text-primary/80 hover:bg-white/10 hover:text-primary"
                          title="Edit details"
                          aria-label="Edit material"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => setMaterialDeleteTarget(mat)}
                          className="rounded p-1.5 text-red-300/80 hover:bg-red-950/40 hover:text-red-200"
                          title="Delete material"
                          aria-label="Delete material"
                        >
                          <Trash2 size={14} />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* In-App Study Material / PDF Viewer Modal */}
      {viewingMaterial && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-3 md:p-6 backdrop-blur-sm"
          onMouseDown={(e) => e.target === e.currentTarget && setViewingMaterial(null)}
        >
          <div className="flex h-full max-h-[92vh] w-full max-w-5xl flex-col rounded-xl border border-primary/30 bg-[#080d12] shadow-2xl overflow-hidden">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-primary/20 px-5 py-3.5 bg-black/50">
              <div className="flex items-center gap-3 min-w-0 pr-4">
                <div className="rounded bg-white/5 p-2 border border-primary/15 shrink-0">
                  {getFileIcon(viewingMaterial.filename, viewingMaterial.fileType)}
                </div>
                <div className="min-w-0">
                  <h3 className="truncate text-base font-semibold text-[#f2efe8]">{viewingMaterial.title}</h3>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-primary/70">
                    <span className="font-mono">{viewingMaterial.filename}</span>
                    <span>·</span>
                    <span>{formatBytes(viewingMaterial.fileSize)}</span>
                    {viewingMaterial.uploadedByName && (
                      <>
                        <span>·</span>
                        <span>Uploaded by {viewingMaterial.uploadedByName}</span>
                      </>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <a
                  href={getMaterialViewUrl(classroomId, viewingMaterial.id)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary hover:text-black transition-colors"
                  title="Open file in full browser tab"
                >
                  <ExternalLink size={13} /> Full Window
                </a>
                <a
                  href={getMaterialDownloadUrl(classroomId, viewingMaterial.id)}
                  download={viewingMaterial.filename}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-white/20 bg-white/5 px-3 py-1.5 text-xs font-medium text-[#c9c4b5] hover:bg-white/10 hover:text-white transition-colors"
                  title="Download file to device"
                >
                  <Download size={13} /> Download
                </a>
                <button
                  type="button"
                  onClick={() => setViewingMaterial(null)}
                  className="grid h-8 w-8 place-items-center rounded-lg border border-primary/25 text-primary hover:bg-white/10 ml-1"
                  aria-label="Close viewer"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Modal Viewer Content */}
            <div className="relative flex-1 bg-[#05080c] flex items-center justify-center overflow-hidden">
              {viewingMaterial.filename.toLowerCase().endsWith(".pdf") || viewingMaterial.fileType.includes("pdf") ? (
                <iframe
                  src={getMaterialViewUrl(classroomId, viewingMaterial.id)}
                  title={viewingMaterial.title}
                  className="h-full w-full border-0 bg-white"
                />
              ) : ["png", "jpg", "jpeg", "webp", "gif"].some((ext) => viewingMaterial.filename.toLowerCase().endsWith("." + ext)) || viewingMaterial.fileType.includes("image") ? (
                <div className="flex h-full w-full items-center justify-center p-4">
                  <img
                    src={getMaterialViewUrl(classroomId, viewingMaterial.id)}
                    alt={viewingMaterial.title}
                    className="max-h-full max-w-full object-contain rounded-lg shadow-2xl"
                  />
                </div>
              ) : ["txt", "md", "csv"].some((ext) => viewingMaterial.filename.toLowerCase().endsWith("." + ext)) || viewingMaterial.fileType.includes("text") ? (
                <iframe
                  src={getMaterialViewUrl(classroomId, viewingMaterial.id)}
                  title={viewingMaterial.title}
                  className="h-full w-full border-0 bg-[#0d1318] text-[#f2efe8] p-4 font-mono text-xs"
                />
              ) : (
                <div className="flex flex-col items-center justify-center p-8 text-center max-w-md">
                  <FileSpreadsheet size={48} className="text-primary/70 mb-3" />
                  <h4 className="text-base font-semibold text-[#f2efe8]">{viewingMaterial.filename}</h4>
                  <p className="mt-2 text-xs text-[#c9c4b5] leading-relaxed">
                    This file format is designed to be opened in desktop applications like Microsoft Word or PowerPoint. You can download it directly to view its complete formatting.
                  </p>
                  <a
                    href={getMaterialDownloadUrl(classroomId, viewingMaterial.id)}
                    download={viewingMaterial.filename}
                    className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-black hover:opacity-90 transition-opacity"
                  >
                    <Download size={14} /> Download File
                  </a>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* In-Page Video Player Modal */}
      {playingLecture && (
        <InAppLecturePlayer
          key={playingLecture.id}
          classroomId={classroomId}
          lecture={playingLecture}
          onClose={() => {
            setPlayingLecture(null);
            void loadData();
          }}
        />
      )}

      {/* Upload Study Material Modal */}
      {showUploadModal && (
        <div className="classroom-delete-overlay" onMouseDown={(e) => e.target === e.currentTarget && setShowUploadModal(false)}>
          <div className="classroom-delete-dialog max-w-lg" role="dialog" aria-modal="true">
            <h2 className="text-lg font-semibold text-[#f2efe8]">Upload Study Material</h2>
            <p className="mt-1 text-xs text-[#c9c4b5]">
              Upload study guides, presentations, PDFs, or notes for this classroom (up to 25 MB).
            </p>
            <form onSubmit={handleUploadMaterial} className="mt-4 grid gap-3">
              <label className="grid gap-1 text-xs text-primary/80">
                Material Title *
                <input
                  required
                  value={uploadTitle}
                  onChange={(e) => setUploadTitle(e.target.value)}
                  placeholder="e.g. Microservices Architecture Cheatsheet"
                  className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#f2efe8]"
                />
              </label>

              <label className="grid gap-1 text-xs text-primary/80">
                Description (optional)
                <textarea
                  value={uploadDesc}
                  onChange={(e) => setUploadDesc(e.target.value)}
                  placeholder="Summary of topics covered in this document…"
                  className="min-h-16 rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#f2efe8]"
                />
              </label>

              <label className="grid gap-1 text-xs text-primary/80">
                Select File *
                <input
                  type="file"
                  required
                  accept=".pdf,.doc,.docx,.ppt,.pptx,.png,.jpg,.jpeg,.gif,.webp,.txt,.md,.csv,.xlsx,.xls"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) {
                      setUploadFile(f);
                      if (!uploadTitle.trim()) {
                        setUploadTitle(f.name.replace(/\.[^/.]+$/, ""));
                      }
                    }
                  }}
                  className="rounded-lg border border-primary/25 bg-black/40 p-2 text-xs text-[#f2efe8] file:mr-3 file:rounded file:border-0 file:bg-primary file:px-2.5 file:py-1 file:text-xs file:font-semibold file:text-black"
                />
              </label>

              <div className="classroom-delete-actions mt-3">
                <button type="button" onClick={() => setShowUploadModal(false)} disabled={uploading}>
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={uploading || !uploadFile}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-black disabled:opacity-50"
                >
                  {uploading ? <LoaderCircle size={15} className="animate-spin" /> : <Check size={15} />}
                  {uploading ? "Uploading…" : "Upload Material"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Material Modal */}
      {editingMaterial && (
        <div className="classroom-delete-overlay" onMouseDown={(e) => e.target === e.currentTarget && setEditingMaterial(null)}>
          <div className="classroom-delete-dialog max-w-lg" role="dialog" aria-modal="true">
            <h2 className="text-lg font-semibold text-[#f2efe8]">Edit Material</h2>
            <form onSubmit={handleUpdateMaterial} className="mt-4 grid gap-3">
              <label className="grid gap-1 text-xs text-primary/80">
                Material Title
                <input
                  required
                  value={editingMaterial.title}
                  onChange={(e) => setEditingMaterial({ ...editingMaterial, title: e.target.value })}
                  className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#f2efe8]"
                />
              </label>

              <label className="grid gap-1 text-xs text-primary/80">
                Description
                <textarea
                  value={editingMaterial.description || ""}
                  onChange={(e) => setEditingMaterial({ ...editingMaterial, description: e.target.value })}
                  className="min-h-16 rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#f2efe8]"
                />
              </label>

              <div className="classroom-delete-actions mt-3">
                <button type="button" onClick={() => setEditingMaterial(null)}>
                  Cancel
                </button>
                <button type="submit" className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-black">
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Material Confirmation */}
      {materialDeleteTarget && (
        <div className="classroom-delete-overlay" onMouseDown={(e) => e.target === e.currentTarget && setMaterialDeleteTarget(null)}>
          <div className="classroom-delete-dialog" role="alertdialog">
            <div className="classroom-delete-icon"><Trash2 size={22} /></div>
            <p className="classroom-delete-eyebrow">Delete Material</p>
            <h2>Delete "{materialDeleteTarget.title}"?</h2>
            <p>This will permanently remove this resource file and make it inaccessible to all students.</p>
            <div className="classroom-delete-actions">
              <button type="button" onClick={() => setMaterialDeleteTarget(null)}>Cancel</button>
              <button type="button" className="classroom-delete-confirm" onClick={handleDeleteMaterial}>Delete</button>
            </div>
          </div>
        </div>
      )}

      {/* Add / Edit Lecture Modal with URL Preview */}
      {showLectureModal && (
        <div className="classroom-delete-overlay" onMouseDown={(e) => e.target === e.currentTarget && setShowLectureModal(false)}>
          <div className="classroom-delete-dialog max-w-xl max-h-[90vh] overflow-y-auto" role="dialog" aria-modal="true">
            <h2 className="text-lg font-semibold text-[#f2efe8]">
              {editingLecture ? "Edit Lecture" : "Add New Lecture"}
            </h2>
            <p className="mt-1 text-xs text-[#c9c4b5]">
              Share YouTube, Google Drive, direct MP4, or external lecture videos.
            </p>

            <form onSubmit={handleSaveLecture} className="mt-4 grid gap-3.5">
              <label className="grid gap-1 text-xs text-primary/80">
                Lecture Title *
                <input
                  required
                  value={lectureTitle}
                  onChange={(e) => setLectureTitle(e.target.value)}
                  placeholder="e.g. Lecture 1 — Introduction to Microservices"
                  className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#f2efe8]"
                />
              </label>

              <label className="grid gap-1 text-xs text-primary/80">
                Description (optional)
                <textarea
                  value={lectureDesc}
                  onChange={(e) => setLectureDesc(e.target.value)}
                  placeholder="Core concepts explained in this lecture…"
                  className="min-h-16 rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#f2efe8]"
                />
              </label>

              <label className="grid gap-1 text-xs text-primary/80">
                Video URL *
                <input
                  type="url"
                  required
                  value={lectureUrl}
                  onChange={(e) => setLectureUrl(e.target.value)}
                  placeholder="https://www.youtube.com/watch?v=... or Google Drive / MP4 link"
                  className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#f2efe8]"
                />
              </label>

              {/* URL Platform Detection Preview */}
              {urlValidation && (
                <div
                  className={`rounded-lg border p-3 text-xs leading-relaxed ${
                    urlValidation.valid
                      ? "border-primary/40 bg-primary/10 text-primary"
                      : "border-red-400/40 bg-red-950/40 text-red-200"
                  }`}
                >
                  <div className="flex items-center gap-1.5 font-semibold uppercase tracking-wide">
                    {urlValidation.valid ? <Check size={14} /> : <AlertCircle size={14} />}
                    Detected Platform: {urlValidation.platform}
                  </div>
                  <p className="mt-1">{urlValidation.message}</p>
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label className="grid gap-1 text-xs text-primary/80">
                  <div className="flex items-center justify-between">
                    <span>Duration (Minutes)</span>
                    {urlValidation?.durationMinutes ? (
                      <span className="text-[10px] text-emerald-400 font-medium">
                        ✓ Auto-detected: {urlValidation.durationMinutes} min
                      </span>
                    ) : null}
                  </div>
                  <input
                    type="number"
                    step="any"
                    min="0.1"
                    value={lectureMinutes}
                    onChange={(e) => setLectureMinutes(e.target.value)}
                    placeholder="e.g. 36.15"
                    className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm text-[#f2efe8] focus:border-primary focus:outline-none"
                  />
                  <span className="text-[10px] text-[#c9c4b5]">
                    {urlValidation?.durationMinutes
                      ? "Automatically set from video. You can adjust if needed."
                      : "Enter video duration in minutes (e.g. 36.15)"}
                  </span>
                </label>

                <div className="grid gap-1 text-xs text-primary/80">
                  <div className="flex items-center justify-between">
                    <span>Completion Threshold: {lectureThreshold}%</span>
                    <span className="rounded bg-primary/20 px-1.5 py-0.5 text-[10px] font-mono text-primary font-semibold">
                      {lectureThreshold}% required
                    </span>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="100"
                    value={lectureThreshold}
                    onChange={(e) => setLectureThreshold(e.target.value)}
                    className="w-full accent-primary cursor-pointer my-1"
                  />
                  <div className="flex items-center justify-between gap-1 text-[10px]">
                    <span className="text-[#c9c4b5]">Presets:</span>
                    {[100, 90, 75, 50].map((val) => (
                      <button
                        key={val}
                        type="button"
                        onClick={() => setLectureThreshold(String(val))}
                        className={`rounded px-1.5 py-0.5 border text-[10px] transition-colors ${
                          lectureThreshold === String(val)
                            ? "border-primary bg-primary text-black font-semibold"
                            : "border-primary/25 text-primary hover:bg-white/5"
                        }`}
                      >
                        {val}%
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="classroom-delete-actions mt-3">
                <button type="button" onClick={() => setShowLectureModal(false)} disabled={savingLecture}>
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingLecture || !lectureTitle.trim() || !lectureUrl.trim()}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-black disabled:opacity-50"
                >
                  {savingLecture ? <LoaderCircle size={15} className="animate-spin" /> : <Check size={15} />}
                  {savingLecture ? "Saving…" : editingLecture ? "Save Changes" : "Publish Lecture"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Lecture Confirmation */}
      {lectureDeleteTarget && (
        <div className="classroom-delete-overlay" onMouseDown={(e) => e.target === e.currentTarget && setLectureDeleteTarget(null)}>
          <div className="classroom-delete-dialog" role="alertdialog">
            <div className="classroom-delete-icon"><Trash2 size={22} /></div>
            <p className="classroom-delete-eyebrow">Delete Lecture</p>
            <h2>Delete "{lectureDeleteTarget.title}"?</h2>
            <p>This will permanently remove this lecture and all associated student watch progress records.</p>
            <div className="classroom-delete-actions">
              <button type="button" onClick={() => setLectureDeleteTarget(null)}>Cancel</button>
              <button type="button" className="classroom-delete-confirm" onClick={handleDeleteLecture}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ============================================================================= */
/* In-App Embedded Lecture Video Player Component                                */
/* Strict requirement: plays in-app, supports HTML5, YouTube, GDrive iframe      */
/* ============================================================================= */

type WatchRange = { start: number; end: number };

/** Adds [start, end] to a sorted list of watched ranges, merging any overlaps. */
function addWatchRange(ranges: WatchRange[], start: number, end: number): WatchRange[] {
  if (!(end > start)) return ranges;
  let next = { start, end };
  const kept: WatchRange[] = [];
  for (const r of ranges) {
    if (r.end < next.start || r.start > next.end) {
      kept.push(r);
    } else {
      next = { start: Math.min(r.start, next.start), end: Math.max(r.end, next.end) };
    }
  }
  kept.push(next);
  return kept.sort((a, b) => a.start - b.start);
}

function totalWatchRanges(ranges: WatchRange[]): number {
  return ranges.reduce((sum, r) => sum + (r.end - r.start), 0);
}

/** Formats seconds as a player clock, e.g. 0:00, 4:05, 1:02:09. */
function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const ss = String(total % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** Extracts the 11-character YouTube video id from an embed / watch / short / shorts URL. */
function extractYouTubeId(...urls: string[]): string {
  for (const u of urls) {
    const m = (u || "").match(/(?:embed\/|youtu\.be\/|[?&]v=|shorts\/)([a-zA-Z0-9_-]{11})/);
    if (m) return m[1];
  }
  return "";
}

let ytApiPromise: Promise<any> | null = null;

/** Loads the YouTube IFrame API exactly once and resolves with `window.YT` when it is ready. */
function loadYouTubeApi(): Promise<any> {
  if (window.YT && window.YT.Player) return Promise.resolve(window.YT);
  if (ytApiPromise) return ytApiPromise;
  ytApiPromise = new Promise((resolve, reject) => {
    const prevCallback = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      if (typeof prevCallback === "function") prevCallback();
      resolve(window.YT);
    };
    if (!document.querySelector('script[src*="youtube.com/iframe_api"]')) {
      const tag = document.createElement("script");
      tag.src = "https://www.youtube.com/iframe_api";
      tag.async = true;
      tag.onerror = () => {
        ytApiPromise = null;
        reject(new Error("Failed to load the YouTube IFrame API"));
      };
      document.head.appendChild(tag);
    }
  });
  return ytApiPromise;
}

function youTubeErrorMessage(code: number): string {
  if (code === 101 || code === 150) {
    return "The owner of this video does not allow it to be played on other websites. Use \"Open Source Video\" to watch it on YouTube.";
  }
  if (code === 100) return "This video was removed or is private.";
  if (code === 2) return "The video link is invalid. Ask your teacher to check the lecture URL.";
  if (code === 5) return "This video cannot be played in the in-app HTML5 player.";
  return `YouTube could not play this video (error ${code}).`;
}

function InAppLecturePlayer({
  classroomId,
  lecture,
  onClose,
}: {
  classroomId: string;
  lecture: ClassroomLecture;
  onClose: () => void;
}) {
  const initialWatched = lecture.progress?.watchedSeconds || 0;
  const resumeAt = lecture.progress?.lastPositionSeconds || 0;

  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(resumeAt);
  const [duration, setDuration] = useState(lecture.durationSeconds || 0);
  const [watchedSeconds, setWatchedSeconds] = useState(initialWatched);
  const [ytReady, setYtReady] = useState(false);
  const [playerError, setPlayerError] = useState("");

  const videoRef = useRef<HTMLVideoElement>(null);
  const ytHostRef = useRef<HTMLDivElement>(null);
  const ytPlayerRef = useRef<any>(null);

  // Previously-saved watch time is treated as the opening segment of the video, so
  // re-watching the beginning in a later session is not counted twice.
  const seedRanges: WatchRange[] = initialWatched > 0 ? [{ start: 0, end: initialWatched }] : [];
  const watchedRangesRef = useRef<WatchRange[]>(seedRanges);

  // Latest values mirrored into refs so timers and unmount cleanup never read stale state.
  const watchedRef = useRef(initialWatched);
  const positionRef = useRef(resumeAt);
  const durationRef = useRef(lecture.durationSeconds || 0);
  const lastSavedRef = useRef({ watched: Math.round(initialWatched), position: Math.round(resumeAt) });

  const youTubeId = lecture.platform === "youtube" ? extractYouTubeId(lecture.embedUrl, lecture.videoUrl) : "";

  const threshold = lecture.completionThreshold || 100;
  const currentPercent = duration > 0 ? Math.min(100, Math.round((watchedSeconds / duration) * 100)) : 0;
  const isCompleted = currentPercent >= threshold;

  const updateDuration = (d: number) => {
    if (d > 0 && Math.abs(d - durationRef.current) > 0.5) {
      durationRef.current = d;
      setDuration(d);
    }
  };

  const updatePosition = (t: number) => {
    positionRef.current = t;
    setCurrentTime(t);
  };

  /** Recomputes verified watch time from the merged watched ranges. */
  const commitWatchedRanges = (ranges: WatchRange[]) => {
    watchedRangesRef.current = ranges;
    const total = durationRef.current;
    const watched = total > 0 ? Math.min(total, totalWatchRanges(ranges)) : totalWatchRanges(ranges);
    watchedRef.current = watched;
    setWatchedSeconds(watched);
  };

  // Persist progress to backend (no-op when nothing changed since the last save)
  const persistProgress = (): Promise<void> => {
    const total = durationRef.current;
    if (!lecture.trackingSupported || total <= 0) return Promise.resolve();
    const watched = Math.round(Math.min(watchedRef.current, total));
    const position = Math.round(Math.min(positionRef.current, total));
    if (watched === lastSavedRef.current.watched && position === lastSavedRef.current.position) {
      return Promise.resolve();
    }
    lastSavedRef.current = { watched, position };
    return recordLectureProgress(classroomId, lecture.id, {
      watchedSeconds: watched,
      lastPositionSeconds: position,
      totalDurationSeconds: Math.round(total),
    })
      .then(() => undefined)
      .catch(() => {
        // silent fail in background
      });
  };

  // Sync periodically, when the tab is hidden, and when the player unmounts
  useEffect(() => {
    const timer = window.setInterval(() => void persistProgress(), 10000);
    const onVisibility = () => {
      if (document.visibilityState === "hidden") void persistProgress();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      void persistProgress();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lecture.id]);

  // YouTube IFrame API player. Created once per lecture; play/pause state changes never
  // recreate it. React only owns the empty host <div>; the API injects its own iframe
  // into a child node, so creating/destroying the player never conflicts with React's DOM.
  useEffect(() => {
    if (lecture.platform !== "youtube") return;
    const host = ytHostRef.current;
    if (!host) return;
    if (!youTubeId) {
      setPlayerError("Could not read the YouTube video ID from this lecture link.");
      return;
    }

    let cancelled = false;
    let pollTimer: number | undefined;
    let lastSample: { time: number; at: number } | null = null;

    const mountNode = document.createElement("div");
    host.appendChild(mountNode);

    // Samples the real playback clock. Only natural forward playback is counted as
    // watched; seeks, skips and paused time are ignored.
    const sample = () => {
      const player = ytPlayerRef.current;
      if (!player || typeof player.getCurrentTime !== "function") return;
      const t = Number(player.getCurrentTime()) || 0;
      updateDuration(Number(player.getDuration?.()) || 0);

      const playing = player.getPlayerState?.() === window.YT?.PlayerState?.PLAYING;
      const now = performance.now();
      if (playing && lastSample) {
        const delta = t - lastSample.time;
        const rate = Number(player.getPlaybackRate?.()) || 1;
        const maxNaturalAdvance = ((now - lastSample.at) / 1000) * rate + 1;
        if (delta > 0 && delta <= maxNaturalAdvance) {
          commitWatchedRanges(addWatchRange(watchedRangesRef.current, lastSample.time, t));
        }
      }
      lastSample = playing ? { time: t, at: now } : null;
      updatePosition(t);
    };

    loadYouTubeApi()
      .then((YT) => {
        if (cancelled) return;
        ytPlayerRef.current = new YT.Player(mountNode, {
          videoId: youTubeId,
          width: "100%",
          height: "100%",
          playerVars: {
            autoplay: 1,
            rel: 0,
            playsinline: 1,
            modestbranding: 1,
            enablejsapi: 1,
            origin: window.location.origin,
            start: Math.floor(resumeAt),
          },
          events: {
            onReady: (event: any) => {
              if (cancelled) return;
              setYtReady(true);
              updateDuration(Number(event.target.getDuration?.()) || 0);
              try {
                event.target.playVideo();
              } catch {
                // autoplay may be blocked; the user can press play
              }
            },
            onStateChange: (event: any) => {
              if (cancelled) return;
              const state = YT.PlayerState;
              if (event.data === state.PLAYING) {
                setIsPlaying(true);
                setPlayerError("");
              } else if (event.data === state.PAUSED || event.data === state.ENDED) {
                setIsPlaying(false);
                sample();
                void persistProgress();
              }
            },
            onPlaybackRateChange: (event: any) => {
              if (!cancelled && typeof event.data === "number") setPlaybackSpeed(event.data);
            },
            onError: (event: any) => {
              if (cancelled) return;
              setIsPlaying(false);
              setPlayerError(youTubeErrorMessage(Number(event.data)));
            },
          },
        });
        pollTimer = window.setInterval(sample, 500);
      })
      .catch(() => {
        if (!cancelled) {
          setPlayerError("Could not load the YouTube player. Check your internet connection or disable any ad-blocker for this site.");
        }
      });

    return () => {
      cancelled = true;
      if (pollTimer) clearInterval(pollTimer);
      try {
        ytPlayerRef.current?.destroy?.();
      } catch {
        // ignore
      }
      ytPlayerRef.current = null;
      host.innerHTML = "";
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lecture.id, lecture.platform, youTubeId]);

  // HTML5 Video Events
  const handleHtml5TimeUpdate = () => {
    const v = videoRef.current;
    if (!v) return;
    updatePosition(v.currentTime);
    if (v.duration && Number.isFinite(v.duration)) updateDuration(v.duration);
    // Verified watched time = previously saved segment merged with ranges actually played now
    let ranges = seedRanges;
    for (let i = 0; i < v.played.length; i++) {
      ranges = addWatchRange(ranges, v.played.start(i), v.played.end(i));
    }
    commitWatchedRanges(ranges);
  };

  const handleHtml5LoadedMetadata = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.duration && Number.isFinite(v.duration)) updateDuration(v.duration);
    if (resumeAt > 0 && (!v.duration || resumeAt < v.duration - 1)) {
      v.currentTime = resumeAt;
    }
    v.play().catch(() => {});
  };

  const getYtPlayer = () => {
    const player = ytPlayerRef.current;
    return player && typeof player.getPlayerState === "function" ? player : null;
  };

  const togglePlay = () => {
    if (lecture.platform === "direct" && videoRef.current) {
      if (videoRef.current.paused) {
        videoRef.current.play().catch(() => {});
      } else {
        videoRef.current.pause();
      }
    } else if (lecture.platform === "youtube") {
      const player = getYtPlayer();
      if (!player) return;
      try {
        const state = player.getPlayerState();
        const YTState = window.YT?.PlayerState;
        if (state === YTState?.PLAYING || state === YTState?.BUFFERING) {
          player.pauseVideo();
        } else {
          player.playVideo();
        }
      } catch {
        // ignore
      }
    }
  };

  const seekTo = (target: number) => {
    const max = durationRef.current > 0 ? durationRef.current : Number.MAX_SAFE_INTEGER;
    const time = Math.max(0, Math.min(max, target));
    if (lecture.platform === "direct" && videoRef.current) {
      videoRef.current.currentTime = time;
    } else if (lecture.platform === "youtube") {
      const player = getYtPlayer();
      if (!player) return;
      try {
        player.seekTo(time, true);
      } catch {
        return;
      }
    }
    updatePosition(time);
  };

  const skipSeconds = (seconds: number) => {
    seekTo(positionRef.current + seconds);
  };

  const handleTimelineClick = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (durationRef.current <= 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const fraction = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    seekTo(fraction * durationRef.current);
  };

  const changeSpeed = (speed: number) => {
    setPlaybackSpeed(speed);
    if (lecture.platform === "direct" && videoRef.current) {
      videoRef.current.playbackRate = speed;
    } else if (lecture.platform === "youtube") {
      try {
        getYtPlayer()?.setPlaybackRate(speed);
      } catch {
        // ignore
      }
    }
  };

  const toggleFullscreen = () => {
    const container = document.getElementById("lecture-video-container");
    if (!container) return;
    if (!document.fullscreenElement) {
      container.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  };

  const handleClose = () => {
    // Save the latest position before the parent reloads lecture progress
    void persistProgress().finally(onClose);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-3 md:p-6 backdrop-blur-sm">
      <div className="flex h-full max-h-[92vh] w-full max-w-5xl flex-col rounded-xl border border-primary/30 bg-[#080d12] shadow-2xl overflow-hidden">
        {/* Player Header */}
        <div className="flex items-center justify-between border-b border-primary/20 px-5 py-3.5 bg-black/50">
          <div className="min-w-0 pr-4">
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase font-mono tracking-wider text-primary">
                Lecture Player · {lecture.platform.toUpperCase()}
              </span>
              {isCompleted ? (
                <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-[10px] font-semibold text-emerald-300 border border-emerald-500/40">
                  Completed ({currentPercent}%)
                </span>
              ) : (
                <span className="rounded bg-amber-500/20 px-2 py-0.5 text-[10px] font-semibold text-amber-300 border border-amber-500/40">
                  Progress: {currentPercent}% (Target: {threshold}%)
                </span>
              )}
            </div>
            <h2 className="mt-1 truncate text-base font-semibold text-[#f2efe8]">{lecture.title}</h2>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {lecture.videoUrl && (
              <a
                href={lecture.videoUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary hover:text-black transition-colors"
                title="Open video directly in YouTube / host site"
              >
                <ExternalLink size={13} /> Open Source Video
              </a>
            )}
            <button
              type="button"
              onClick={handleClose}
              className="grid h-8 w-8 place-items-center rounded-lg border border-primary/25 text-primary hover:bg-white/10"
              aria-label="Close lecture"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Video Canvas Container */}
        <div
          id="lecture-video-container"
          className="relative flex-1 bg-black flex items-center justify-center overflow-hidden min-h-[300px]"
        >
          {lecture.platform === "youtube" ? (
            <>
              {/* Host for the YouTube IFrame API player (populated imperatively) */}
              <div
                id="youtube-player-host"
                ref={ytHostRef}
                className="absolute inset-0 [&_iframe]:h-full [&_iframe]:w-full [&_iframe]:border-0"
              />
              {!ytReady && !playerError && (
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 text-primary/80">
                  <LoaderCircle size={28} className="animate-spin" />
                  <span className="text-xs">Loading video player…</span>
                </div>
              )}
              {playerError && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/90 p-6 text-center">
                  <AlertTriangle size={30} className="text-amber-400" />
                  <p className="max-w-md text-sm text-[#f2efe8]">{playerError}</p>
                  {lecture.videoUrl && (
                    <a
                      href={lecture.videoUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-black hover:opacity-90"
                    >
                      <ExternalLink size={13} /> Open Source Video
                    </a>
                  )}
                </div>
              )}
            </>
          ) : lecture.platform === "gdrive" ? (
            <div className="relative h-full w-full flex flex-col">
              <div className="bg-amber-950/70 border-b border-amber-500/30 p-2 text-center text-xs text-amber-200">
                <AlertCircle size={14} className="inline mr-1 -mt-0.5" />
                Google Drive Embedded Preview. Click the play button inside the frame to play.
              </div>
              <iframe
                src={lecture.embedUrl}
                title={lecture.title}
                className="h-full w-full border-0 flex-1"
                allow="autoplay; fullscreen"
                allowFullScreen
              />
            </div>
          ) : lecture.platform === "direct" ? (
            <video
              ref={videoRef}
              src={lecture.videoUrl}
              autoPlay
              controls
              onTimeUpdate={handleHtml5TimeUpdate}
              onLoadedMetadata={handleHtml5LoadedMetadata}
              onPlay={() => setIsPlaying(true)}
              onPause={() => {
                setIsPlaying(false);
                void persistProgress();
              }}
              onEnded={() => {
                setIsPlaying(false);
                void persistProgress();
              }}
              onRateChange={() => videoRef.current && setPlaybackSpeed(videoRef.current.playbackRate)}
              className="h-full w-full max-h-full object-contain"
              playsInline
            />
          ) : (
            <iframe
              src={lecture.embedUrl}
              title={lecture.title}
              className="h-full w-full border-0"
              allow="autoplay; fullscreen"
              allowFullScreen
            />
          )}
        </div>

        {/* Interactive Playback Control Bar for supported players */}
        {(lecture.platform === "direct" || lecture.platform === "youtube") && (
          <div className="border-t border-primary/20 bg-black/60 px-5 py-3">
            {/* Timeline Progress (click to seek) */}
            <div className="mb-2.5 flex items-center gap-3">
              <span className="text-[11px] font-mono text-primary/80 min-w-12">
                {formatClock(currentTime)}
              </span>
              <div
                className="relative flex-1 h-2 rounded bg-white/10 overflow-hidden cursor-pointer"
                onClick={handleTimelineClick}
                role="slider"
                aria-label="Seek"
                aria-valuemin={0}
                aria-valuemax={Math.round(duration)}
                aria-valuenow={Math.round(currentTime)}
              >
                <div
                  className="h-full bg-primary transition-all duration-150"
                  style={{ width: `${duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0}%` }}
                />
              </div>
              <span className="text-[11px] font-mono text-[#c9c4b5] min-w-12 text-right">
                {duration > 0 ? formatClock(duration) : "--:--"}
              </span>
            </div>

            {/* Playback Buttons */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={togglePlay}
                  className="grid h-9 w-9 place-items-center rounded-lg bg-primary text-black transition-opacity hover:opacity-90"
                  aria-label={isPlaying ? "Pause" : "Play"}
                >
                  {isPlaying ? <Pause size={16} /> : <Play size={16} fill="currentColor" />}
                </button>

                <button
                  type="button"
                  onClick={() => skipSeconds(-10)}
                  className="inline-flex items-center gap-1 rounded border border-primary/25 px-2.5 py-1.5 text-xs text-primary hover:bg-white/5"
                  title="Skip backward 10s"
                >
                  <RotateCcw size={13} /> 10s
                </button>

                <button
                  type="button"
                  onClick={() => skipSeconds(10)}
                  className="inline-flex items-center gap-1 rounded border border-primary/25 px-2.5 py-1.5 text-xs text-primary hover:bg-white/5"
                  title="Skip forward 10s"
                >
                  <RotateCw size={13} /> 10s
                </button>
              </div>

              {/* Speed Controls & Fullscreen */}
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1 text-xs text-primary/80">
                  <span className="text-[11px] uppercase tracking-wider text-primary/60">Speed:</span>
                  <select
                    value={playbackSpeed}
                    onChange={(e) => changeSpeed(parseFloat(e.target.value))}
                    className="rounded border border-primary/30 bg-black/60 px-2 py-1 text-xs text-primary focus:border-primary focus:outline-none"
                  >
                    {PLAYBACK_SPEEDS.map((sp) => (
                      <option key={sp} value={sp}>
                        {sp}×
                      </option>
                    ))}
                  </select>
                </div>

                <button
                  type="button"
                  onClick={toggleFullscreen}
                  className="rounded p-1.5 text-primary/80 hover:bg-white/10 hover:text-primary"
                  title="Toggle Fullscreen"
                  aria-label="Fullscreen"
                >
                  <Maximize2 size={16} />
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Footer Details */}
        <div className="flex flex-wrap items-center justify-between border-t border-primary/15 px-5 py-3 text-xs bg-black/40">
          <div className="min-w-0 flex-1 pr-4">
            {lecture.description ? (
              <p className="line-clamp-1 text-[#c9c4b5]">{lecture.description}</p>
            ) : (
              <p className="text-primary/60">Enrolled classroom lecture.</p>
            )}
          </div>
          <div className="text-[11px] text-primary/70">
            {isCompleted ? (
              <span className="text-emerald-300">✓ Lecture requirement satisfied ({threshold}%)</span>
            ) : (
              <span>Watch at least {threshold}% to complete this lecture</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
