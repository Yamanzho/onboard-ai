import type { StepType } from '../../types/step'

export interface StepFormValues {
  title: string
  description: string
  step_type: StepType
  content_body: string
  content_url: string
  content_questions: string
  is_required: boolean
  estimated_minutes: string
}

export interface QuizQuestion {
  id: string
  text: string
  correct?: string
}

export function stepContentBody(content: Record<string, unknown> | undefined) {
  if (!content) return ''
  const body = content.body
  return typeof body === 'string' ? body : ''
}

export function stepContentUrl(content: Record<string, unknown> | undefined) {
  if (!content) return ''
  const url = content.url ?? content.link
  return typeof url === 'string' ? url : ''
}

export function parseQuizQuestions(
  content: Record<string, unknown> | undefined,
): QuizQuestion[] {
  if (!content) return []
  const raw = content.questions
  if (!Array.isArray(raw)) return []
  const questions: QuizQuestion[] = []
  raw.forEach((item, index) => {
    if (typeof item === 'string' && item.trim()) {
      questions.push({ id: `q${index + 1}`, text: item.trim() })
      return
    }
    if (!item || typeof item !== 'object') return
    const record = item as Record<string, unknown>
    const text = record.text ?? record.prompt ?? record.question
    if (typeof text !== 'string' || !text.trim()) return
    const id =
      typeof record.id === 'string' && record.id.trim()
        ? record.id.trim()
        : `q${index + 1}`
    const correctRaw = record.correct ?? record.answer
    const correct =
      typeof correctRaw === 'string' && correctRaw.trim()
        ? correctRaw.trim()
        : undefined
    questions.push(correct ? { id, text: text.trim(), correct } : { id, text: text.trim() })
  })
  return questions
}

export function stepContentQuestions(content: Record<string, unknown> | undefined) {
  return parseQuizQuestions(content)
    .map((q) => (q.correct ? `${q.text} | ${q.correct}` : q.text))
    .join('\n')
}

export function questionsFromText(text: string): QuizQuestion[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const splitAt = line.indexOf('|')
      if (splitAt === -1) {
        return { id: `q${index + 1}`, text: line }
      }
      const prompt = line.slice(0, splitAt).trim()
      const correct = line.slice(splitAt + 1).trim()
      if (!prompt) {
        return { id: `q${index + 1}`, text: line }
      }
      return correct
        ? { id: `q${index + 1}`, text: prompt, correct }
        : { id: `q${index + 1}`, text: prompt }
    })
}

export function buildStepContent(
  values: Pick<StepFormValues, 'content_body' | 'content_url' | 'content_questions' | 'step_type'>,
  existing?: Record<string, unknown>,
): Record<string, unknown> {
  const next = { ...(existing ?? {}) }
  const trimmed = values.content_body.trim()
  if (trimmed) next.body = trimmed
  else delete next.body

  const url = values.content_url.trim()
  if (values.step_type === 'task' && url) {
    next.url = url
  } else {
    delete next.url
    delete next.link
  }

  if (values.step_type === 'quiz') {
    const questions = questionsFromText(values.content_questions)
    if (questions.length > 0) next.questions = questions
    else delete next.questions
  } else {
    delete next.questions
  }
  return next
}
