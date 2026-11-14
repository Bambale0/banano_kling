'use client'

import { useEffect, useRef, useState } from 'react'
import {
  postVkPublicFeedComment, type VkNativeFeedCommentWriteResult,
} from '@/lib/shared-account-api'

function requestKey() {
  if (typeof crypto === 'undefined' || typeof crypto.getRandomValues !== 'function') {
    throw new Error('Недоступна безопасная отправка комментариев. Обновите приложение.')
  }
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return 'vk_comment_' + Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
}

/** Owner-scoped, idempotent native VK write to the same shared public feed. */
export function VkNativeCommentComposer({
  feedGenId, onPosted,
}: {
  feedGenId: number
  onPosted: (result: VkNativeFeedCommentWriteResult) => void
}) {
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const attempt = useRef<{ key: string; text: string } | null>(null)
  const mounted = useRef(false)
  const version = useRef(0)

  useEffect(() => {
    mounted.current = true
    version.current += 1
    attempt.current = null
    setDraft('')
    setError('')
    setPending(false)
    setBusy(false)
    return () => {
      mounted.current = false
      version.current += 1
    }
  }, [feedGenId])

  const normalized = draft.trim().replace(/\s+/g, ' ')
  const valid = normalized.length >= 1 && normalized.length <= 500

  async function submit() {
    if (busy || (!pending && !valid)) return
    const epoch = version.current
    if (!attempt.current) {
      try {
        attempt.current = { key: requestKey(), text: normalized }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Ошибка безопасного запроса.')
        return
      }
      setPending(true)
    }
    setBusy(true)
    setError('')
    try {
      const claimed = attempt.current
      const result = await postVkPublicFeedComment(feedGenId, claimed.text, claimed.key)
      if (!mounted.current || epoch !== version.current) return
      attempt.current = null
      setPending(false)
      setDraft('')
      onPosted(result)
    } catch (cause) {
      if (mounted.current && epoch === version.current) {
        setError(cause instanceof Error ? cause.message : 'Статус комментария неясен. Повторите тот же запрос.')
      }
    } finally {
      if (mounted.current && epoch === version.current) setBusy(false)
    }
  }

  return <form aria-label="Комментарий ВКонтакте" className="space-y-2" onSubmit={event => {
    event.preventDefault()
    void submit()
  }}>
    <label className="block text-sm font-medium">
      Новый комментарий
      <textarea aria-label="Новый комментарий" maxLength={500} rows={2}
        value={draft} disabled={busy || pending}
        onChange={event => setDraft(event.target.value)}
        className="mt-1 block w-full rounded-lg border border-border bg-background p-2 text-sm"
      />
    </label>
    <p className="text-xs text-muted-foreground">До 500 символов. Автор — ваш аккаунт ВКонтакте.</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <button type="submit" disabled={busy || (!pending && !valid)}
      className="rounded-lg border border-primary px-3 py-2 text-sm font-medium text-primary">
      {busy ? 'Проверяем публикацию…' : pending
        ? 'Проверить и повторить тот же комментарий' : 'Опубликовать комментарий'}
    </button>
  </form>
}
