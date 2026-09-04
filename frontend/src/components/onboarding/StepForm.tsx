import { useState, type FormEvent } from 'react'
import { labelStepType, t } from '../../i18n'
import { Button } from '../ui/Button'
import { Input, Label, Select, Textarea } from '../ui/Field'
import { STEP_TYPES, type StepType } from '../../types/step'
import {
  newContentBlock,
  newStructuredQuestion,
  nextQuizOptionId,
  type ContentBlockDraft,
  type StepFormValues,
  type StructuredQuizQuestionDraft,
} from './stepFormUtils'

interface StepFormProps {
  initial: StepFormValues
  submitLabel: string
  pending?: boolean
  onSubmit: (values: StepFormValues) => Promise<void>
  onCancel?: () => void
}

function validate(values: StepFormValues): string | null {
  const title = values.title.trim()
  if (!title) return t('programs.steps.validation.titleRequired')
  if (title.length > 255) return t('programs.steps.validation.titleMax')
  if (values.description.length > 5000) {
    return t('programs.steps.validation.descriptionMax')
  }
  if (!STEP_TYPES.includes(values.step_type)) {
    return t('programs.steps.validation.typeInvalid')
  }
  const minutes = values.estimated_minutes.trim()
  if (minutes) {
    if (!/^\d+$/.test(minutes)) {
      return t('programs.steps.validation.minutesInvalid')
    }
  }
  if (values.step_type === 'quiz') {
    if (values.quiz_is_legacy && !values.quiz_convert) {
      return null
    }
    if (values.quiz_questions.length < 1) {
      return t('programs.steps.validation.questionsRequired')
    }
    for (const question of values.quiz_questions) {
      if (!question.text.trim()) {
        return t('programs.steps.validation.questionTextRequired')
      }
      if (question.options.length < 2) {
        return t('programs.steps.validation.optionsMin')
      }
      if (question.options.some((option) => !option.text.trim())) {
        return t('programs.steps.validation.optionTextRequired')
      }
      const correct = new Set(question.correct_option_ids)
      if (question.type === 'single_choice' && correct.size !== 1) {
        return t('programs.steps.validation.singleCorrect')
      }
      if (question.type === 'multiple_choice' && correct.size < 1) {
        return t('programs.steps.validation.multipleCorrect')
      }
    }
  }
  return null
}

function moveBlock(
  blocks: ContentBlockDraft[],
  index: number,
  direction: -1 | 1,
): ContentBlockDraft[] {
  const target = index + direction
  if (target < 0 || target >= blocks.length) return blocks
  const next = [...blocks]
  const current = next[index]!
  next[index] = next[target]!
  next[target] = current
  return next
}

export function StepForm({
  initial,
  submitLabel,
  pending,
  onSubmit,
  onCancel,
}: StepFormProps) {
  const [values, setValues] = useState(initial)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const validationError = validate(values)
    if (validationError) {
      setError(validationError)
      return
    }
    setError(null)
    try {
      await onSubmit({
        ...values,
        title: values.title.trim(),
        description: values.description.trim(),
        content_body: values.content_body,
        estimated_minutes: values.estimated_minutes.trim(),
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.saveFailed'))
    }
  }

  function updateBlock(index: number, text: string) {
    const next = values.content_blocks.map((block, i) =>
      i === index ? { ...block, text } : block,
    )
    setValues({ ...values, content_blocks: next })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3" noValidate>
      {error ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      ) : null}

      <div>
        <Label htmlFor="step-title">{t('common.name')}</Label>
        <Input
          id="step-title"
          value={values.title}
          onChange={(e) => setValues({ ...values, title: e.target.value })}
          required
          maxLength={255}
        />
      </div>

      <div>
        <Label htmlFor="step-description">{t('common.description')}</Label>
        <Textarea
          id="step-description"
          rows={3}
          value={values.description}
          onChange={(e) =>
            setValues({ ...values, description: e.target.value })
          }
          placeholder={t('common.optional')}
        />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <Label htmlFor="step-type">{t('programs.steps.colType')}</Label>
          <Select
            id="step-type"
            value={values.step_type}
            onChange={(e) => {
              const stepType = e.target.value as StepType
              setValues({
                ...values,
                step_type: stepType,
                quiz_questions:
                  stepType === 'quiz' && values.quiz_questions.length === 0
                    ? [newStructuredQuestion(0)]
                    : values.quiz_questions,
                quiz_is_legacy: stepType === 'quiz' ? values.quiz_is_legacy : false,
                quiz_convert: stepType === 'quiz' ? values.quiz_convert : false,
              })
            }}
          >
            {STEP_TYPES.map((stepType) => (
              <option key={stepType} value={stepType}>
                {labelStepType(stepType)}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="step-minutes">{t('programs.steps.estimatedMinutes')}</Label>
          <Input
            id="step-minutes"
            inputMode="numeric"
            value={values.estimated_minutes}
            onChange={(e) =>
              setValues({ ...values, estimated_minutes: e.target.value })
            }
            placeholder={t('common.optional')}
          />
        </div>
      </div>

      {values.step_type === 'content' ? (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Label>{t('programs.steps.contentBlocks')}</Label>
            <Button
              type="button"
              variant="secondary"
              onClick={() =>
                setValues({
                  ...values,
                  content_blocks: [
                    ...values.content_blocks,
                    newContentBlock('', values.content_blocks.length),
                  ],
                })
              }
            >
              {t('programs.steps.addBlock')}
            </Button>
          </div>
          {values.content_blocks.length === 0 ? (
            <p className="text-xs text-[var(--color-muted)]">
              {t('programs.steps.blocksEmpty')}
            </p>
          ) : (
            <ol className="space-y-3">
              {values.content_blocks.map((block, index) => (
                <li
                  key={block.id}
                  className="rounded-md border border-[var(--color-border)] p-3"
                >
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-medium text-[var(--color-muted)]">
                      {t('programs.steps.blockLabel', { n: index + 1 })}
                    </span>
                    <div className="flex flex-wrap gap-1">
                      <Button
                        type="button"
                        variant="ghost"
                        disabled={index === 0}
                        onClick={() =>
                          setValues({
                            ...values,
                            content_blocks: moveBlock(
                              values.content_blocks,
                              index,
                              -1,
                            ),
                          })
                        }
                      >
                        {t('programs.steps.up')}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        disabled={index === values.content_blocks.length - 1}
                        onClick={() =>
                          setValues({
                            ...values,
                            content_blocks: moveBlock(
                              values.content_blocks,
                              index,
                              1,
                            ),
                          })
                        }
                      >
                        {t('programs.steps.down')}
                      </Button>
                      <Button
                        type="button"
                        variant="danger"
                        onClick={() =>
                          setValues({
                            ...values,
                            content_blocks: values.content_blocks.filter(
                              (_, i) => i !== index,
                            ),
                          })
                        }
                      >
                        {t('common.delete')}
                      </Button>
                    </div>
                  </div>
                  <Textarea
                    id={`step-block-${block.id}`}
                    rows={3}
                    value={block.text}
                    onChange={(e) => updateBlock(index, e.target.value)}
                    placeholder={t('programs.steps.contentPlaceholder')}
                  />
                </li>
              ))}
            </ol>
          )}
        </div>
      ) : (
        <div>
          <Label htmlFor="step-content">{t('programs.steps.contentBody')}</Label>
          <Textarea
            id="step-content"
            rows={4}
            value={values.content_body}
            onChange={(e) =>
              setValues({ ...values, content_body: e.target.value })
            }
            placeholder={t('programs.steps.contentPlaceholder')}
          />
        </div>
      )}

      {values.step_type === 'task' ? (
        <div>
          <Label htmlFor="step-url">{t('programs.steps.taskUrl')}</Label>
          <Input
            id="step-url"
            type="url"
            value={values.content_url}
            onChange={(e) =>
              setValues({ ...values, content_url: e.target.value })
            }
            placeholder={t('programs.steps.taskUrlPlaceholder')}
          />
        </div>
      ) : null}

      {values.step_type === 'quiz' ? (
        <QuizEditor
          values={values}
          onChange={setValues}
        />
      ) : null}

      {values.step_type === 'ack' ? (
        <p className="text-xs text-[var(--color-muted)]">
          {t('programs.steps.ackHint')}
        </p>
      ) : null}

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={values.is_required}
          onChange={(e) =>
            setValues({ ...values, is_required: e.target.checked })
          }
        />
        {t('programs.steps.requiredStep')}
      </label>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={pending}>
          {pending ? t('common.saving') : submitLabel}
        </Button>
        {onCancel ? (
          <Button type="button" variant="secondary" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
        ) : null}
      </div>
    </form>
  )
}

function moveItem<T>(items: T[], index: number, direction: -1 | 1): T[] {
  const target = index + direction
  if (target < 0 || target >= items.length) return items
  const next = [...items]
  const current = next[index]!
  next[index] = next[target]!
  next[target] = current
  return next
}

function QuizEditor({
  values,
  onChange,
}: {
  values: StepFormValues
  onChange: (values: StepFormValues) => void
}) {
  const showStructured = !values.quiz_is_legacy || values.quiz_convert

  function updateQuestion(
    index: number,
    patch: Partial<StructuredQuizQuestionDraft>,
  ) {
    const quiz_questions = values.quiz_questions.map((question, i) => {
      if (i !== index) return question
      const next = { ...question, ...patch }
      if (patch.type === 'single_choice' && next.correct_option_ids.length > 1) {
        next.correct_option_ids = next.correct_option_ids.slice(0, 1)
      }
      return next
    })
    onChange({ ...values, quiz_questions })
  }

  function toggleCorrect(questionIndex: number, optionId: string) {
    const question = values.quiz_questions[questionIndex]
    if (!question) return
    const selected = new Set(question.correct_option_ids)
    if (question.type === 'single_choice') {
      onChange({
        ...values,
        quiz_questions: values.quiz_questions.map((item, i) =>
          i === questionIndex ? { ...item, correct_option_ids: [optionId] } : item,
        ),
      })
      return
    }
    if (selected.has(optionId)) selected.delete(optionId)
    else selected.add(optionId)
    updateQuestion(questionIndex, { correct_option_ids: [...selected] })
  }

  return (
    <div className="space-y-3">
      <div>
        <Label>{t('programs.steps.questions')}</Label>
        <p className="mt-1 text-xs text-[var(--color-muted)]">
          {t('programs.steps.questionsHint')}
        </p>
      </div>

      {values.quiz_is_legacy && !values.quiz_convert ? (
        <div className="space-y-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-950">
          <p>{t('programs.steps.legacyQuizNotice')}</p>
          {values.content_questions ? (
            <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded bg-white/80 p-2 text-xs">
              {values.content_questions}
            </pre>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            onClick={() =>
              onChange({
                ...values,
                quiz_convert: true,
                quiz_questions:
                  values.quiz_questions.length > 0
                    ? values.quiz_questions
                    : [newStructuredQuestion(0)],
              })
            }
          >
            {t('programs.steps.convertQuiz')}
          </Button>
        </div>
      ) : null}

      {showStructured ? (
        <div className="space-y-3">
          {values.quiz_questions.map((question, qIndex) => (
            <div
              key={question.id}
              className="space-y-3 rounded-md border border-[var(--color-border)] p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs font-medium text-[var(--color-muted)]">
                  {t('programs.steps.questionLabel', { n: qIndex + 1 })}
                </span>
                <div className="flex flex-wrap gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={qIndex === 0}
                    onClick={() =>
                      onChange({
                        ...values,
                        quiz_questions: moveItem(
                          values.quiz_questions,
                          qIndex,
                          -1,
                        ),
                      })
                    }
                  >
                    {t('programs.steps.up')}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={qIndex === values.quiz_questions.length - 1}
                    onClick={() =>
                      onChange({
                        ...values,
                        quiz_questions: moveItem(
                          values.quiz_questions,
                          qIndex,
                          1,
                        ),
                      })
                    }
                  >
                    {t('programs.steps.down')}
                  </Button>
                  <Button
                    type="button"
                    variant="danger"
                    onClick={() =>
                      onChange({
                        ...values,
                        quiz_questions: values.quiz_questions.filter(
                          (_, i) => i !== qIndex,
                        ),
                      })
                    }
                  >
                    {t('common.delete')}
                  </Button>
                </div>
              </div>
              <div>
                <Label htmlFor={`quiz-q-${question.id}`}>
                  {t('programs.steps.questionText')}
                </Label>
                <Textarea
                  id={`quiz-q-${question.id}`}
                  rows={2}
                  value={question.text}
                  onChange={(e) =>
                    updateQuestion(qIndex, { text: e.target.value })
                  }
                />
              </div>
              <div>
                <Label htmlFor={`quiz-type-${question.id}`}>
                  {t('programs.steps.questionType')}
                </Label>
                <Select
                  id={`quiz-type-${question.id}`}
                  value={question.type}
                  onChange={(e) =>
                    updateQuestion(qIndex, {
                      type: e.target.value as StructuredQuizQuestionDraft['type'],
                    })
                  }
                >
                  <option value="single_choice">
                    {t('programs.steps.singleChoice')}
                  </option>
                  <option value="multiple_choice">
                    {t('programs.steps.multipleChoice')}
                  </option>
                </Select>
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <Label>{t('programs.steps.options')}</Label>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      updateQuestion(qIndex, {
                        options: [
                          ...question.options,
                          { id: nextQuizOptionId(question.options), text: '' },
                        ],
                      })
                    }
                  >
                    {t('programs.steps.addOption')}
                  </Button>
                </div>
                {question.options.map((option, oIndex) => (
                  <div key={option.id} className="flex items-start gap-2">
                    <label className="mt-2 flex items-center gap-2 text-sm">
                      <input
                        type={
                          question.type === 'single_choice'
                            ? 'radio'
                            : 'checkbox'
                        }
                        name={`correct-${question.id}`}
                        checked={question.correct_option_ids.includes(option.id)}
                        onChange={() => toggleCorrect(qIndex, option.id)}
                      />
                      <span className="sr-only">
                        {t('programs.steps.markCorrect')}
                      </span>
                    </label>
                    <Input
                      value={option.text}
                      onChange={(e) => {
                        const options = question.options.map((item, i) =>
                          i === oIndex ? { ...item, text: e.target.value } : item,
                        )
                        updateQuestion(qIndex, { options })
                      }}
                      placeholder={t('programs.steps.optionPlaceholder', {
                        n: oIndex + 1,
                      })}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={question.options.length <= 2}
                      onClick={() => {
                        const options = question.options.filter(
                          (_, i) => i !== oIndex,
                        )
                        updateQuestion(qIndex, {
                          options,
                          correct_option_ids: question.correct_option_ids.filter(
                            (id) => id !== option.id,
                          ),
                        })
                      }}
                    >
                      {t('common.delete')}
                    </Button>
                  </div>
                ))}
                <p className="text-xs text-[var(--color-muted)]">
                  {t('programs.steps.markCorrectHint')}
                </p>
              </div>
              <div>
                <Label htmlFor={`quiz-expl-${question.id}`}>
                  {t('programs.steps.explanation')}
                </Label>
                <Input
                  id={`quiz-expl-${question.id}`}
                  value={question.explanation}
                  onChange={(e) =>
                    updateQuestion(qIndex, { explanation: e.target.value })
                  }
                  placeholder={t('common.optional')}
                />
              </div>
            </div>
          ))}
          <Button
            type="button"
            variant="secondary"
            onClick={() =>
              onChange({
                ...values,
                quiz_questions: [
                  ...values.quiz_questions,
                  newStructuredQuestion(values.quiz_questions.length),
                ],
              })
            }
          >
            {t('programs.steps.addQuestion')}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
