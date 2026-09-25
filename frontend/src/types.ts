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
