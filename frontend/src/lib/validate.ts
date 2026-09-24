import type { Lesson } from '../types'
const str = (v: unknown): v is string => typeof v === 'string' && v.trim().length > 0
const strs = (v: unknown): v is string[] => Array.isArray(v) && v.every(str)
const list = (v: unknown) => (v === undefined ? [] : strs(v) ? v : null)

/** Second line of defence (the backend already validates): never render an unchecked shape. */
export function validateLesson(d: any): Lesson | null {
  try {
    const e = d?.explanation
    if (!str(d?.topic) || !str(e?.overview) || !Array.isArray(e.sections) || !e.sections.length) return null
    const keyTakeaways = list(e.keyTakeaways), commonMistakes = list(e.commonMistakes)
    if (!keyTakeaways || !commonMistakes) return null
    const sections = e.sections.map((s: any) => str(s?.title) && str(s?.content) && list(s.examples) !== null
      ? { title: s.title, content: s.content, examples: list(s.examples) as string[] } : null)
    if (sections.includes(null)) return null
    const cardsOk = Array.isArray(d.flashcards) && d.flashcards.length > 0 &&
      d.flashcards.every((c: any) => str(c?.id) && str(c?.question) && str(c?.answer))
    const quizOk = Array.isArray(d.quiz) && d.quiz.length > 0 && d.quiz.every((q: any) =>
      str(q?.id) && str(q?.question) && strs(q?.options) && q.options.length >= 2 &&
      str(q?.explanation) && q.options.includes(q.correctAnswer))
    if (!cardsOk || !quizOk) return null
    return { topic: d.topic, explanation: { overview: e.overview, sections, keyTakeaways, commonMistakes },
      flashcards: d.flashcards, quiz: d.quiz }
  } catch { return null }
}
