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
export type SavedSession = {
  id: string;
  topic: string;
  learningContent: Lesson;
  answers?: Record<string, string>;
  evaluation: { completed: boolean; score?: number };
  createdAt: string;
};
