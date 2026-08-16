import type { KeyboardEvent } from 'react'
import { Button } from '../ui/Button'
import { Label, Textarea } from '../ui/Field'
import { t } from '../../i18n'
import { MAX_CHAT_QUESTION_CHARS } from '../../types/ai'

function isCoarsePointer(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia('(pointer: coarse)').matches
  )
}

export function AIComposer({
  value,
  onChange,
  onSend,
  disabled,
}: {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  disabled: boolean
}) {
  const canSend = !disabled && value.trim().length > 0

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) {
      return
    }
    if (isCoarsePointer()) return
    event.preventDefault()
    if (canSend) onSend()
  }

  return (
    <div className="border-t border-[var(--color-border)] bg-[var(--color-bg)] pt-3">
      <Label htmlFor="ai-chat-message">{t('ai.composerLabel')}</Label>
      <Textarea
        id="ai-chat-message"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        maxLength={MAX_CHAT_QUESTION_CHARS}
        disabled={disabled}
        rows={3}
        placeholder={t('ai.composerPlaceholder')}
        aria-label={t('ai.composerLabel')}
        className="min-h-[4.5rem] resize-y"
      />
      <div className="mt-2 flex items-center justify-between gap-3">
        <p className="text-xs text-[var(--color-muted)]" aria-live="polite">
          {t('ai.charCount', {
            current: value.length,
            max: MAX_CHAT_QUESTION_CHARS,
          })}
        </p>
        <Button
          type="button"
          onClick={onSend}
          disabled={!canSend}
          aria-label={t('ai.send')}
        >
          {t('ai.send')}
        </Button>
      </div>
    </div>
  )
}
