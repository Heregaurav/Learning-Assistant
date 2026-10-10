import type {
  DocumentLearningRequest,
  DocumentLearningResponse,
  Lesson,
  SavedSession,
  ClassroomCurriculum,
  CurriculumModule,
  CurriculumTopic,
  ClassroomAssessment,
  ClassroomSubmission,
  ClassroomKnowledgeGraph,
  ClassroomProgress,
} from "../types";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const CSRF_TOKEN_KEY = "curiosity.csrf-token";
let csrfToken = sessionStorage.getItem(CSRF_TOKEN_KEY) ?? "";

export const setCsrfToken = (token: string) => {
  csrfToken = token;
  sessionStorage.setItem(CSRF_TOKEN_KEY, token);
};

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
export const MSG: Record<string, string> = {
  auth_required: "Sign in with Google to continue.",
  invalid_auth:
    "Google rejected this sign-in token. Check the OAuth client ID and authorized origin.",
  auth_expired: "Your Google sign-in has expired. Please sign in again.",
  auth_not_configured: "Google sign-in is not configured on the backend.",
  invalid_json: "AI returned invalid JSON. Please try again.",
  bad_schema:
    "The generated learning material had an unexpected format. Please try again.",
  empty: "No learning material was generated. Please try again.",
  timeout: "This is taking longer than expected. Retry?",
  llm_failed: "We couldn't generate your lesson.",
  network: "Unable to connect to the server.",
  database_unavailable: "The database is unavailable right now.",
  database_auth_failed:
    "MongoDB rejected the username or password. Check backend/.env.",
  missing_api_key: "Add the selected provider API key to backend/.env.",
  retest_limit: "You have used all 3 retests for this topic.",
};

async function req<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = 70000,
): Promise<T> {
  const ctl = new AbortController(),
    t = setTimeout(() => ctl.abort("timeout"), timeoutMs);
  init.signal?.addEventListener("abort", () => ctl.abort("cancelled"));
  try {
    const guestId = localStorage.getItem("curiosity.guest-id");
    const r = await fetch(BASE + path, {
      ...init,
      credentials: "include",
      signal: ctl.signal,
      headers: {
        "Content-Type": "application/json",
        ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
        ...(guestId ? { "X-Guest-ID": guestId } : {}),
      },
    });
    if (!r.ok) {
      const b = await r.json().catch(() => ({}));
      const code = b?.detail?.code ?? `http_${r.status}`;
      throw new ApiError(
        code,
        MSG[code] ?? b?.detail?.message ?? "Request failed.",
      );
    }
    return (await r.json()) as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if ((e as Error).name === "AbortError")
      throw new ApiError(
        ctl.signal.reason === "timeout" ? "timeout" : "cancelled",
        MSG.timeout,
      );
    throw new ApiError("network", MSG.network);
  } finally {
    clearTimeout(t);
  }
}

export const googleAuth = (credential: string) =>
  req<{
    user: {
      id: string;
      name: string;
      email: string;
      picture: string;
      role?: "ADMIN" | "FACULTY" | "STUDENT";
    };
    csrfToken: string;
  }>("/api/auth/google", {
    method: "POST",
    body: JSON.stringify({ credential }),
  }).then((result) => {
    setCsrfToken(result.csrfToken);
    return result;
  });

export const getAuthSession = () =>
  req<{
    authenticated: boolean;
    user: {
      id: string;
      name: string;
      email: string;
      picture: string;
      role: "ADMIN" | "FACULTY" | "STUDENT";
    } | null;
  }>("/api/auth/session");

export const getProfile = () =>
  req<{
    id: string;
    name: string;
    email: string;
    picture: string;
    role?: "ADMIN" | "FACULTY" | "STUDENT";
    isGuest?: boolean;
    stats: {
      topicsStudied: number;
      sessionsCompleted: number;
      averageScore: number;
      cardsReviewed: number;
      quizzesCompleted: number;
    };
    strong: {
      id: string;
      name: string;
      retestsUsed: number;
      progress: { score: number };
    }[];
    needsReview: {
      id: string;
      name: string;
      retestsUsed: number;
      progress: { score: number };
    }[];
  }>("/api/profile");

export const getClassrooms = () =>
  req<
    {
      id: string;
      name: string;
      subject: string;
      section: string;
      semester: string;
      description: string;
      joinCode?: string;
      ownerId?: string;
      memberCount?: number;
      status?: string;
      createdAt?: string;
      curriculum?: { modules: unknown[] };
    }[]
  >("/api/classrooms");

export const createClassroom = (payload: {
  name: string;
  subject: string;
  section: string;
  semester: string;
  description?: string;
}) =>
  req<{ id: string; name: string; joinCode: string; memberCount: number }>("/api/classrooms", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const deleteClassroom = (classroomId: string) =>
  req<{ deleted: boolean; id: string }>(`/api/classrooms/${encodeURIComponent(classroomId)}`, {
    method: "DELETE",
  });

export const joinClassroom = (joinCode: string) =>
  req<{ id: string; name: string; joinCode?: string; memberCount: number }>(
    "/api/classrooms/join",
    { method: "POST", body: JSON.stringify({ joinCode }) },
  );

export type PlatformUser = {
  id: string;
  name: string;
  email: string;
  role: "ADMIN" | "FACULTY" | "STUDENT";
  createdAt?: string;
};

export const getPlatformUsers = () => req<PlatformUser[]>("/api/admin/users");

export const updatePlatformUserRole = (
  userId: string,
  role: PlatformUser["role"],
) =>
  req<PlatformUser>(`/api/admin/users/${encodeURIComponent(userId)}/role`, {
    method: "POST",
    body: JSON.stringify({ role }),
  });

export const getClassroomCurriculum = (classroomId: string) =>
  req<ClassroomCurriculum>(`/api/classrooms/${classroomId}/curriculum`);

export const createCurriculumModule = (
  classroomId: string,
  payload: { title: string; description?: string; position?: number },
) =>
  req<CurriculumModule>(`/api/classrooms/${classroomId}/modules`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const createCurriculumTopic = (
  classroomId: string,
  moduleId: string,
  payload: Omit<CurriculumTopic, "id">,
) =>
  req<CurriculumTopic>(
    `/api/classrooms/${classroomId}/modules/${moduleId}/topics`,
    { method: "POST", body: JSON.stringify(payload) },
  );

export const getClassroomAssessments = (classroomId: string) =>
  req<ClassroomAssessment[]>(`/api/classrooms/${classroomId}/classwork`);

export const createClassroomAssessment = (
  classroomId: string,
  payload: Omit<ClassroomAssessment, "id" | "classroomId">,
) =>
  req<ClassroomAssessment>(`/api/classrooms/${classroomId}/classwork`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const submitClassroomAssessment = (
  classroomId: string,
  assessmentId: string,
  answer: string,
) =>
  req<ClassroomSubmission>(
    `/api/classrooms/${classroomId}/classwork/${assessmentId}/submissions`,
    { method: "POST", body: JSON.stringify({ answer }) },
  );

export const getClassroomSubmissions = (
  classroomId: string,
  assessmentId: string,
) =>
  req<ClassroomSubmission[]>(
    `/api/classrooms/${classroomId}/classwork/${assessmentId}/submissions`,
  );

export const gradeClassroomSubmission = (
  classroomId: string,
  assessmentId: string,
  submissionId: string,
  payload: { score: number; feedback: string; release: boolean },
) =>
  req<{ id: string; score: number; released: boolean }>(
    `/api/classrooms/${classroomId}/classwork/${assessmentId}/submissions/${submissionId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );

export type AnswerEvaluation = {
  score: number;
  conceptScores: Record<string, number>;
  strengths: string[];
  misconceptions: string[];
  feedback: string;
  recommendedTopics: string[];
};

export const evaluateClassroomSubmission = (
  classroomId: string,
  assessmentId: string,
  submissionId: string,
) =>
  req<AnswerEvaluation>(
    `/api/classrooms/${classroomId}/classwork/${assessmentId}/submissions/${submissionId}/evaluate`,
    { method: "POST", body: JSON.stringify({}) },
  );

export const getClassroomProgress = (classroomId: string) =>
  req<ClassroomProgress>(`/api/classrooms/${classroomId}/progress`);

export const getClassroomAnalytics = (classroomId: string) =>
  req<{
    enrolledStudents: number;
    studentsWithEvidence: number;
    averageMastery: number | null;
    students: {
      studentId: string;
      mastery: { score: number | null; state: string };
      coverage: { percent: number; coveredTopics: number; totalTopics: number };
    }[];
    topics: { topicId: string; title: string; averageMastery: number; evidenceCount: number }[];
  }>(`/api/classrooms/${classroomId}/analytics`);

export const getClassroomGraph = (classroomId: string, studentId?: string) =>
  req<ClassroomKnowledgeGraph>(`/api/classrooms/${classroomId}/graph${studentId ? `?student_id=${encodeURIComponent(studentId)}` : ""}`);

export type ClassroomPost = {
  id: string;
  kind: "announcement" | "discussion";
  title: string;
  body: string;
  authorId: string;
  replies: { id: string; authorId: string; body: string }[];
};

export const getClassroomStream = (classroomId: string) =>
  req<ClassroomPost[]>(`/api/classrooms/${classroomId}/stream`);

export const createClassroomPost = (
  classroomId: string,
  payload: { kind: "announcement" | "discussion"; title: string; body: string },
) =>
  req<ClassroomPost>(`/api/classrooms/${classroomId}/stream`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const replyToClassroomPost = (classroomId: string, postId: string, body: string) =>
  req<ClassroomPost["replies"][number]>(
    `/api/classrooms/${classroomId}/stream/${postId}/replies`,
    { method: "POST", body: JSON.stringify({ body }) },
  );

export const learnDocument = (
  file: File,
  payload: DocumentLearningRequest,
): Promise<DocumentLearningResponse> => {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("difficulty", payload.difficulty);
  form.append("provider", payload.provider);
  form.append("model", payload.model);
  form.append("instructions", payload.instructions ?? "");

  return fetch(`${BASE}/api/learn/document`, {
    method: "POST",
    credentials: "include",
    body: form,
    headers: {
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...(localStorage.getItem("curiosity.guest-id")
        ? { "X-Guest-ID": localStorage.getItem("curiosity.guest-id") ?? "" }
        : {}),
    },
  }).then(async (r) => {
    if (!r.ok) {
      const b = await r.json().catch(() => ({}));
      const code = b?.detail?.code ?? `http_${r.status}`;
      throw new ApiError(code, MSG[code] ?? b?.detail?.message ?? "Request failed.");
    }
    return (await r.json()) as DocumentLearningResponse;
  });
};

export const learn = (
  content: string,
  difficulty: string,
  provider: string,
  model: string,
  signal: AbortSignal,
) =>
  req<{ sessionId: string; topic: string; learningContent: unknown }>(
    "/api/learn",
    {
      method: "POST",
      body: JSON.stringify({ content, difficulty, provider, model }),
      signal,
    },
  );
export const learnStream = async (
  content: string,
  difficulty: string,
  provider: string,
  model: string,
  signal: AbortSignal,
  onStage: (stage: string) => void,
  classroomContext?: { classroomId: string; curriculumTopicId: string },
) => {
  const response = await fetch(`${BASE}/api/learn/stream`, {
    method: "POST",
    credentials: "include",
    signal,
    headers: {
      "Content-Type": "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...(localStorage.getItem("curiosity.guest-id")
        ? { "X-Guest-ID": localStorage.getItem("curiosity.guest-id") ?? "" }
        : {}),
    },
    body: JSON.stringify({ content, difficulty, provider, model, ...classroomContext }),
  });
  if (!response.ok || !response.body) throw new ApiError("network", MSG.network);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const event of events) {
      const line = event.split("\n").find((item) => item.startsWith("data: "));
      if (!line) continue;
      const payload = JSON.parse(line.slice(6));
      if (payload.error) throw new ApiError(payload.error, payload.message);
      if (payload.stage) onStage(payload.stage);
      if (payload.learningContent) return payload;
    }
    if (done) break;
  }
  throw new ApiError("empty", MSG.empty);
};
export const completeSession = (id: string, body: object) =>
  req<{ topicProgress: number }>(`/api/sessions/${id}/complete`, {
    method: "POST",
    body: JSON.stringify(body),
  });
export const getSessions = () => req<SavedSession[]>("/api/sessions");
export const getSession = (id: string) => req<SavedSession & { learningContent: Lesson }>(`/api/sessions/${id}`);
export const retestTopic = (id: string) =>
  req<{ sessionId: string; topic: string; learningContent: unknown }>(
    `/api/topics/${id}/retest`,
    { method: "POST" },
  );
export const refineSession = (id: string, prompt: string) =>
  req<{ sessionId: string; learningContent: unknown }>(
    `/api/sessions/${id}/refine`,
    { method: "POST", body: JSON.stringify({ prompt }) },
  );

export const logout = () =>
  req<{ status: string }>("/api/auth/logout", { method: "POST" }).finally(() => {
    csrfToken = "";
    sessionStorage.removeItem(CSRF_TOKEN_KEY);
  });
