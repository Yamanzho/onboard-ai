import type { AIConversationSummary } from '../../types/ai'
import { t } from '../../i18n'

export function AIConversationHistory({
  items,
  selectedId,
  onSelect,
  onDelete,
  deletingId,
  disabled,
}: {
  items: AIConversationSummary[]
  selectedId?: string
  onSelect: (conversationId: string) => void
  onDelete: (conversationId: string) => void
  deletingId?: string
  disabled: boolean
}) {
  if (items.length === 0) {
    return (
      <p className="px-1 py-4 text-sm text-[var(--color-muted)]">
        {t('ai.historyEmpty')}
      </p>
    )
  }

  return (
    <ul className="flex flex-col gap-1">
      {items.map((item) => {
        const selected = item.conversation_id === selectedId
        return (
          <li key={item.conversation_id}>
            <div
              className={`flex items-start gap-1 rounded-md border px-2 py-2 ${
                selected
                  ? 'border-[var(--color-accent)] bg-teal-50'
                  : 'border-transparent hover:bg-slate-50'
              }`}
            >
              <button
                type="button"
                className="min-w-0 flex-1 text-left"
                onClick={() => onSelect(item.conversation_id)}
                disabled={disabled}
                aria-current={selected ? 'true' : undefined}
              >
                <span className="block truncate text-sm font-medium">
                  {item.title?.trim() || t('ai.untitled')}
                </span>
                {item.last_message_preview ? (
                  <span className="mt-0.5 block truncate text-xs text-[var(--color-muted)]">
                    {item.last_message_preview}
                  </span>
                ) : null}
              </button>
              <button
                type="button"
                className="shrink-0 rounded px-1.5 py-0.5 text-xs text-[var(--color-muted)] hover:bg-red-50 hover:text-[var(--color-danger)]"
                onClick={() => onDelete(item.conversation_id)}
                disabled={disabled || deletingId === item.conversation_id}
                aria-label={t('ai.deleteConversation')}
              >
                ×
              </button>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
