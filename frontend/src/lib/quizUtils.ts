import type {
  EmployeeQuizQuestion,
  QuizAttemptSummary,
  QuizOption,
} from '../types/quiz'

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

export function isStructuredQuizContent(
  content: Record<string, unknown> | undefined,
): boolean {
  const questions = content?.questions
  if (!Array.isArray(questions)) return false
  return questions.some((item) => {
    const rec = asRecord(item)
    if (!rec) return false
    if (typeof rec.type === 'string' && rec.type.trim()) return true
    if (Array.isArray(rec.options)) return true
    if (Array.isArray(rec.correct_option_ids)) return true
    return false
  })
}

export function parseEmployeeQuizQuestions(
  content: Record<string, unknown> | undefined,
): EmployeeQuizQuestion[] {
  if (!content || !Array.isArray(content.questions)) return []
  const questions: EmployeeQuizQuestion[] = []
  content.questions.forEach((item, index) => {
    const rec = asRecord(item)
    if (!rec) return
    const textRaw = rec.text ?? rec.prompt ?? rec.question
    if (typeof textRaw !== 'string' || !textRaw.trim()) return
    const id =
      typeof rec.id === 'string' && rec.id.trim()
        ? rec.id.trim()
        : `q${index + 1}`
    const options: QuizOption[] = []
    if (Array.isArray(rec.options)) {
      rec.options.forEach((opt, optIndex) => {
        const option = asRecord(opt)
        if (!option) return
        const optText = option.text
        if (typeof optText !== 'string' || !optText.trim()) return
        const optId =
          typeof option.id === 'string' && option.id.trim()
            ? option.id.trim()
            : String.fromCharCode(97 + optIndex)
        options.push({ id: optId, text: optText.trim() })
      })
    }
    questions.push({
      id,
      type: typeof rec.type === 'string' ? rec.type : undefined,
      text: textRaw.trim(),
      options: options.length > 0 ? options : undefined,
    })
  })
  return questions
}

export function parseQuizAttemptSummary(
  payload: Record<string, unknown> | undefined,
): QuizAttemptSummary {
  const empty: QuizAttemptSummary = {
    attempt_count: null,
    last_score: null,
    best_score: null,
    last_attempt_at: null,
    passed: null,
  }
  if (!payload) return empty
  const quizScore = asRecord(payload.quiz_score)
  const lastScore =
    typeof payload.last_score === 'number'
      ? payload.last_score
      : typeof quizScore?.score === 'number'
        ? quizScore.score
        : null
  const bestScore =
    typeof payload.best_score === 'number' ? payload.best_score : lastScore
  return {
    attempt_count:
      typeof payload.attempt_count === 'number' ? payload.attempt_count : null,
    last_score: lastScore,
    best_score: bestScore,
    last_attempt_at:
      typeof payload.last_attempt_at === 'string'
        ? payload.last_attempt_at
        : null,
    passed:
      typeof payload.passed === 'boolean'
        ? payload.passed
        : typeof quizScore?.passed === 'boolean'
          ? quizScore.passed
          : null,
  }
}

export function quizScoreLabel(
  payload: Record<string, unknown> | undefined,
): string | null {
  const summary = parseQuizAttemptSummary(payload)
  if (summary.best_score != null) return `${summary.best_score}%`
  const score = payload?.quiz_score
  const rec = asRecord(score)
  if (rec && typeof rec.correct_count === 'number' && typeof rec.total === 'number') {
    return `${rec.correct_count}/${rec.total}`
  }
  return null
}
