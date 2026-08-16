import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { ErrorAlert, PageHeader } from '../common/PageHeader'
import { Button } from '../ui/Button'
import { AIComposer } from './AIComposer'
import { AIConversationHistory } from './AIConversationHistory'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'
import { mapAIChatError } from '../../lib/aiChatErrors'
import {
  deleteAIConversation,
  getAIConversation,
  listAIConversations,
  postAIChat,
} from '../../services/aiApi'
import {
  MAX_CHAT_QUESTION_CHARS,
  type AIChatCitation,
  type AIConversationMessage,
  type ChatMessage,
} from '../../types/ai'

const SUGGESTIONS = [
  'ai.suggestions.vpn',
  'ai.suggestions.vacation',
  'ai.suggestions.it',
] as const

const LIST_KEY = ['ai-conversations'] as const

function uniqueCitations(citations: AIChatCitation[]): AIChatCitation[] {
  const seen = new Set<string>()
  const unique: AIChatCitation[] = []
  for (const citation of citations) {
    if (seen.has(citation.article_id)) continue
    seen.add(citation.article_id)
    unique.push(citation)
  }
  return unique
}

/** Hide internal [S1] markers in the visible answer; citations list uses titles. */
function visibleAssistantText(content: string): string {
  return content.replace(/\s*\[S\d+\]/g, '').trim() || content
}

function mapServerMessages(rows: AIConversationMessage[]): ChatMessage[] {
  return rows.map((row) => ({
    id: row.message_id,
    role: row.role,
    content: row.content,
    citations: row.citations,
    noAnswer: row.no_answer,
  }))
}

function AICitationList({ citations }: { citations: AIChatCitation[] }) {
  const paths = useWorkspacePaths()
  const items = uniqueCitations(citations)
  if (items.length === 0) return null

  return (
    <div className="mt-3 border-t border-[var(--color-border)] pt-2">
      <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-muted)]">
        {t('ai.sources')}
      </p>
      <ol className="mt-1 list-decimal space-y-1 pl-4 text-sm">
        {items.map((citation) => (
          <li key={citation.article_id} className="break-words">
            <Link
              to={paths.article(citation.article_id)}
              className="font-medium text-[var(--color-accent)] hover:underline"
            >
              {citation.title}
            </Link>
          </li>
        ))}
      </ol>
    </div>
  )
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user'
  return (
    <article
      className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
      aria-label={isUser ? t('ai.you') : t('ai.assistant')}
    >
      <div
        className={`max-w-[min(100%,36rem)] rounded-lg border px-3 py-2 text-sm leading-6 ${
          isUser
            ? 'border-teal-700 bg-teal-700 text-white'
            : message.noAnswer
              ? 'border-[var(--color-border)] bg-slate-50 text-[var(--color-text)]'
              : 'border-[var(--color-border)] bg-white text-[var(--color-text)]'
        }`}
      >
        <p className="whitespace-pre-wrap break-words">
          {isUser ? message.content : visibleAssistantText(message.content)}
        </p>
        {!isUser && message.citations && message.citations.length > 0 ? (
          <AICitationList citations={message.citations} />
        ) : null}
      </div>
    </article>
  )
}

function TypingIndicator() {
  return (
    <div
      className="flex justify-start"
      role="status"
      aria-live="polite"
      aria-label={t('ai.thinking')}
    >
      <div className="rounded-lg border border-[var(--color-border)] bg-white px-3 py-2 text-sm text-[var(--color-muted)]">
        <span className="inline-flex items-center gap-1">
          {t('ai.thinking')}
          <span className="inline-flex gap-0.5" aria-hidden="true">
            <span className="animate-pulse">·</span>
            <span className="animate-pulse [animation-delay:150ms]">·</span>
            <span className="animate-pulse [animation-delay:300ms]">·</span>
          </span>
        </span>
      </div>
    </div>
  )
}

function EmptyState({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 py-10 text-center">
      <p className="text-lg font-semibold">{t('ai.emptyTitle')}</p>
      <p className="mt-1 max-w-md text-sm text-[var(--color-muted)]">
        {t('ai.emptyDescription')}
      </p>
      <ul className="mt-6 flex w-full max-w-md flex-col gap-2">
        {SUGGESTIONS.map((key) => (
          <li key={key}>
            <button
              type="button"
              className="w-full rounded-md border border-[var(--color-border)] bg-white px-3 py-2 text-left text-sm hover:border-[var(--color-accent)] hover:bg-slate-50"
              onClick={() => onPick(t(key))}
            >
              {t(key)}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function AIChat() {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const conversationId = searchParams.get('c') ?? undefined
  const [startedNewChat, setStartedNewChat] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)

  const listQuery = useQuery({
    queryKey: LIST_KEY,
    queryFn: listAIConversations,
  })

  const detailQuery = useQuery({
    queryKey: ['ai-conversation', conversationId],
    queryFn: () => getAIConversation(conversationId!),
    enabled: Boolean(conversationId),
    retry: false,
  })

  const mutation = useMutation({
    mutationFn: ({
      message,
      conversationId: threadId,
    }: {
      message: string
      conversationId?: string
    }) => postAIChat(message, threadId),
    retry: false,
    onSuccess: (data) => {
      setSearchParams({ c: data.conversation_id }, { replace: true })
      setStartedNewChat(false)
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: data.answer,
          citations: data.citations,
          noAnswer: data.no_answer,
        },
      ])
      setError(null)
      void queryClient.invalidateQueries({ queryKey: LIST_KEY })
      void queryClient.invalidateQueries({
        queryKey: ['ai-conversation', data.conversation_id],
      })
    },
    onError: (err) => {
      setError(mapAIChatError(err))
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteAIConversation,
    retry: false,
    onSuccess: (_data, deletedId) => {
      void queryClient.invalidateQueries({ queryKey: LIST_KEY })
      if (deletedId === conversationId) {
        startNewChat()
      }
    },
    onError: (err) => {
      setError(mapAIChatError(err))
    },
  })

  const pending = mutation.isPending
  const restoring =
    Boolean(conversationId) && detailQuery.isLoading && messages.length === 0

  useEffect(() => {
    if (conversationId || startedNewChat) return
    const first = listQuery.data?.items[0]
    if (!first) return
    setSearchParams({ c: first.conversation_id }, { replace: true })
  }, [conversationId, startedNewChat, listQuery.data, setSearchParams])

  useEffect(() => {
    if (!conversationId) return
    if (detailQuery.data) {
      setMessages(mapServerMessages(detailQuery.data.messages))
      setError(null)
      return
    }
    if (detailQuery.error) {
      setError(mapAIChatError(detailQuery.error))
    }
  }, [conversationId, detailQuery.data, detailQuery.error])

  useEffect(() => {
    if (!stickToBottom.current) return
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, pending])

  function handleListScroll() {
    const el = listRef.current
    if (!el) return
    stickToBottom.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  function sendMessage(raw: string) {
    const message = raw.trim()
    if (!message || pending || restoring) return
    if (message.length > MAX_CHAT_QUESTION_CHARS) return
    stickToBottom.current = true
    setError(null)
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: 'user', content: message },
    ])
    setDraft('')
    mutation.mutate({ message, conversationId })
  }

  function startNewChat() {
    if (pending) return
    mutation.reset()
    setStartedNewChat(true)
    setHistoryOpen(false)
    setMessages([])
    setError(null)
    setDraft('')
    stickToBottom.current = true
    setSearchParams({}, { replace: true })
  }

  function selectConversation(id: string) {
    if (pending) return
    setStartedNewChat(false)
    setHistoryOpen(false)
    setMessages([])
    setError(null)
    setDraft('')
    stickToBottom.current = true
    setSearchParams({ c: id })
  }

  const history = (
    <div className="flex min-h-0 flex-1 flex-col">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-muted)]">
        {t('ai.history')}
      </p>
      {listQuery.error ? (
        <p className="text-sm text-[var(--color-danger)]">
          {mapAIChatError(listQuery.error)}
        </p>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <AIConversationHistory
            items={listQuery.data?.items ?? []}
            selectedId={conversationId}
            onSelect={selectConversation}
            onDelete={(id) => deleteMutation.mutate(id)}
            deletingId={deleteMutation.variables}
            disabled={pending}
          />
        </div>
      )}
    </div>
  )

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col min-h-[calc(100dvh-10rem)]">
      <PageHeader
        title={t('ai.title')}
        description={t('ai.subtitle')}
        action={
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="secondary"
              className="md:hidden"
              onClick={() => setHistoryOpen(true)}
              aria-label={t('ai.openHistory')}
            >
              {t('ai.history')}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={startNewChat}
              disabled={pending}
            >
              {t('ai.newChat')}
            </Button>
          </div>
        }
      />

      {error ? (
        <div role="alert">
          <ErrorAlert message={error} />
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 gap-4">
        <aside className="hidden w-64 shrink-0 flex-col rounded-lg border border-[var(--color-border)] bg-white p-3 md:flex">
          {history}
        </aside>

        {historyOpen ? (
          <div className="fixed inset-0 z-40 md:hidden">
            <button
              type="button"
              className="absolute inset-0 bg-black/40"
              aria-label={t('ai.closeHistory')}
              onClick={() => setHistoryOpen(false)}
            />
            <aside className="absolute inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col bg-white p-4 shadow-lg">
              <div className="mb-3 flex items-center justify-between">
                <p className="text-sm font-semibold">{t('ai.history')}</p>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setHistoryOpen(false)}
                  aria-label={t('ai.closeHistory')}
                >
                  {t('common.close')}
                </Button>
              </div>
              {history}
            </aside>
          </div>
        ) : null}

        <div className="flex min-w-0 flex-1 flex-col">
          <div
            ref={listRef}
            onScroll={handleListScroll}
            className="flex min-h-[16rem] flex-1 flex-col gap-3 overflow-y-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
            aria-live="polite"
            aria-busy={pending || restoring}
          >
            {restoring ? (
              <p className="py-10 text-center text-sm text-[var(--color-muted)]">
                {t('common.loading')}
              </p>
            ) : messages.length === 0 && !pending ? (
              <EmptyState onPick={(prompt) => sendMessage(prompt)} />
            ) : (
              <>
                {messages.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}
                {pending ? <TypingIndicator /> : null}
                <div ref={bottomRef} />
              </>
            )}
          </div>

          <AIComposer
            value={draft}
            onChange={setDraft}
            onSend={() => sendMessage(draft)}
            disabled={pending || restoring}
          />
        </div>
      </div>
    </div>
  )
}
