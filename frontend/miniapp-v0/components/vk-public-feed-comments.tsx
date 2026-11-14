'use client'

import { useEffect, useState } from 'react'
import { fetchVkPublicFeedComments, type VkPublicFeedCommentsPage } from '@/lib/shared-account-api'

/** Read-only comments from the same public feed as Telegram; no TG actor. */
export function VkPublicFeedComments({ feedGenId }: { feedGenId: number }) {
  const [retry, setRetry] = useState(0)
  const [result, setResult] = useState<VkPublicFeedCommentsPage | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    setBusy(true)
    setError('')
    setResult(null)
    fetchVkPublicFeedComments(feedGenId, controller.signal).then(value => {
      if (!controller.signal.aborted) setResult(value)
    }).catch(cause => {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : 'Не удалось получить комментарии.')
      }
    }).finally(() => {
      if (!controller.signal.aborted) setBusy(false)
    })
    return () => controller.abort()
  }, [feedGenId, retry])

  return <section aria-label="Комментарии общей ленты" className="space-y-2 rounded-xl border border-border p-3 text-sm">
    <h4 className="font-semibold">Комментарии</h4>
    {busy && <p role="status">Загружаем комментарии…</p>}
    {error && <>
      <p role="alert">{error}</p>
      <button type="button" className="text-primary underline" onClick={() => setRetry(value => value + 1)}>
        Повторить загрузку комментариев
      </button>
    </>}
    {!busy && result?.comments.length === 0 && <p>Комментариев пока нет.</p>}
    {result?.comments.map(comment => (
      <article key={comment.id} className="space-y-1 rounded-lg border border-border/60 p-2">
        <strong className="block text-sm">{comment.author}</strong>
        <p className="whitespace-pre-wrap break-words">{comment.text}</p>
      </article>
    ))}
    <p className="text-xs text-muted-foreground">
      Комментарии общей ленты доступны для чтения. Публикация комментариев из VK Mini App пока недоступна.
    </p>
  </section>
}
