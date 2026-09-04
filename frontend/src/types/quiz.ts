export type QuizQuestionType = 'single_choice' | 'multiple_choice'

export interface QuizOption {
  id: string
  text: string
}

/** Employee-facing quiz question. Must not include answer keys. */
export interface EmployeeQuizQuestion {
  id: string
  type?: QuizQuestionType | string
  text: string
  options?: QuizOption[]
}

export interface ManagementQuizQuestion extends EmployeeQuizQuestion {
  correct_option_ids?: string[]
  explanation?: string
  correct?: string
  answer?: string
}

export interface QuizAttemptSummary {
  attempt_count: number | null
  last_score: number | null
  best_score: number | null
  last_attempt_at: string | null
  passed: boolean | null
}

export const QUIZ_QUESTION_TYPES: QuizQuestionType[] = [
  'single_choice',
  'multiple_choice',
]
