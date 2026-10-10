export type Lesson = {
  topic: string;
  explanation: {
    overview: string;
    sections: { title: string; content: string; examples: string[] }[];
    keyTakeaways: string[];
    commonMistakes: string[];
  };
  flashcards: { id: string; question: string; answer: string }[];
  quiz: {
    id: string;
    question: string;
    options: string[];
    correctAnswer: string;
    explanation: string;
  }[];
  blocks: ContentBlock[];
};
export type ContentBlock =
  | { kind: "card"; title: string; body: string }
  | { kind: "checklist"; title: string; items: string[] }
  | { kind: "chart"; title: string; labels: string[]; values: number[] };
export type DocumentMetadata = {
  title: string;
  filename: string;
  extension: string;
  mime_type: string;
  word_count: number;
  page_count?: number | null;
  warnings: string[];
};
export type DocumentUpload = {
  file: File;
  filename: string;
  size: number;
  type: string;
};
export type DocumentLearningRequest = {
  difficulty: "beginner" | "intermediate" | "advanced";
  provider: "groq" | "gemini" | "openrouter";
  model: string;
  instructions?: string;
};
export type DocumentLearningResponse = {
  sessionId: string;
  topic: string;
  learningContent: Lesson;
  document?: DocumentMetadata;
};
export type SavedSession = {
  id: string;
  topic: string;
  source?: "topic" | "document";
  document?: DocumentMetadata;
  learningContent: Lesson;
  answers?: Record<string, string>;
  evaluation: { completed: boolean; score?: number };
  createdAt: string;
};

export type Role = "ADMIN" | "FACULTY" | "STUDENT";

export type ClassroomDraft = {
  name: string;
  subject: string;
  section: string;
  semester: string;
  description?: string;
};

export type Classroom = {
  id: string;
  name: string;
  subject: string;
  section: string;
  semester: string;
  description: string;
  joinCode?: string;
  ownerId?: string;
  status?: string;
  memberCount?: number;
  createdAt?: string;
  curriculum?: { modules: unknown[] };
  members?: { userId: string; name: string; role: string; joinedAt?: string }[];
};

export type CurriculumConcept = {
  name: string;
  description: string;
  prerequisites: string[];
};

export type CurriculumMaterial = {
  kind: "note" | "link";
  title: string;
  content?: string;
  url?: string;
};

export type CurriculumTopic = {
  id: string;
  title: string;
  description: string;
  learningObjectives: string[];
  prerequisites: string[];
  concepts: CurriculumConcept[];
  materials: CurriculumMaterial[];
};

export type CurriculumModule = {
  id: string;
  title: string;
  description: string;
  position: number;
  topics: CurriculumTopic[];
};

export type ClassroomCurriculum = {
  classroom: Classroom;
  modules: CurriculumModule[];
  status?: "draft" | "published";
  version?: number;
};

export type AdaptivePathItem = {
  topicId: string;
  moduleId: string;
  title: string;
  status: "locked" | "available" | "revision_needed" | "practice" | "completed";
  mastery: {
    score: number | null;
    state: string;
    confidence: string;
    evidenceCount: number;
    evidenceIds: string[];
  };
  reason: string;
  nextAction: string;
};

export type ClassroomProgress = {
  mastery: { score: number | null; state: string };
  coverage: { coveredTopics: number; totalTopics: number; percent: number };
  learningPath: {
    items: AdaptivePathItem[];
    recommendation: AdaptivePathItem | null;
    progress: { completed: number; total: number; percent: number };
  };
  modules: {
    id: string;
    title: string;
    topics: {
      id: string;
      title: string;
      coverage: string;
      mastery: AdaptivePathItem["mastery"];
      concepts: { name: string; mastery: AdaptivePathItem["mastery"] }[];
      evidence: { id: string; activityType: string; masteryScore?: number; evaluationStatus: string }[];
    }[];
    mastery: { score: number | null; state: string };
    coverage: { covered: number; total: number };
  }[];
  recommendations: { kind: string; topicId: string; title: string }[];
};

export type ClassroomAssessment = {
  id: string;
  classroomId: string;
  title: string;
  kind: "assignment" | "quiz" | "test" | "practice" | "curiosity";
  instructions: string;
  topicId?: string | null;
  conceptIds: string[];
  dueAt?: string | null;
  maxMarks: number;
  rubric: string;
  expectedAnswer: string;
  published: boolean;
};

export type ClassroomSubmission = {
  id: string;
  classroomId: string;
  assessmentId: string;
  studentId: string;
  answer?: string;
  status: string;
  evaluationStatus: string;
  score?: number;
  feedback?: string;
  released?: boolean;
  aiEvaluation?: {
    score: number;
    conceptScores: Record<string, number>;
    strengths: string[];
    misconceptions: string[];
    feedback: string;
    recommendedTopics: string[];
  };
};

export type KnowledgeGraphNode = {
  id: string;
  curriculumId: string;
  label: string;
  kind: "topic" | "concept";
  mastery: {
    score: number | null;
    state: string;
    confidence: string;
    evidenceCount: number;
    evidenceIds: string[];
  };
  coverage: string;
};

export type KnowledgeGraphEdge = {
  source: string;
  target: string;
  kind: string;
};

export type ClassroomKnowledgeGraph = {
  studentId: string;
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
};
