'use client'

import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { GenjutsuError, genjutsuCall, roleLabels, type Run, type RunStep } from '@/lib/genjutsu-api'
import { notifyFeedChanged } from '@/lib/feed-events'
import type { FeedItem } from '@/lib/types'

type Declaration = { run_id: string; step_id: string; title: string; source_binding: 'user' | 'fixed' }
const field = 'w-full min-w-0 rounded-xl border border-border bg-background px-3 py-2 text-sm'

export function GenjutsuFeedPublisher({ run, step, disabled = false }: { run: Run; step: RunStep; disabled?: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const [title, setTitle] = useState('Genjutsu · вариант ' + (step.variant + 1))
  const [sourceBinding, setSourceBinding] = useState<'user' | 'fixed'>('user')
  const [pending, setPending] = useState(false)
  const [card, setCard] = useState<FeedItem | null>(null)
  const [error, setError] = useState('')
  const [canRetry, setCanRetry] = useState(true)
  const declaration = useRef<Declaration | null>(null)
  const inFlight = useRef(false)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  const finalOrdinal = Math.max(...run.steps.filter(item => item.variant === step.variant).map(item => item.ordinal))
  if (run.state !== 'completed' || run.private_recipe || !run.plan || step.status !== 'completed'
      || !step.output_asset || step.ordinal !== finalOrdinal || step.ordinal !== run.plan.steps.length - 1) return null

  async function publish() {
    if (inFlight.current || disabled || !canRetry || !title.trim()) return
    inFlight.current = true
    declaration.current ||= { run_id: run.id, step_id: step.id, title: title.trim(), source_binding: sourceBinding }
    setPending(true); setError('')
    try {
      const result = await genjutsuCall<{ card: FeedItem }>('feed_publish', declaration.current)
      notifyFeedChanged(result.card)
      if (alive.current) setCard(result.card)
    } catch (cause) {
      if (alive.current) {
        setError(cause instanceof Error ? cause.message : 'Не удалось опубликовать. Повторите попытку.')
        setCanRetry(!(cause instanceof GenjutsuError && cause.status >= 400 && cause.status < 500 && ![408, 429].includes(cause.status)))
      }
    } finally {
      inFlight.current = false
      if (alive.current) setPending(false)
    }
  }

  if (card) return <p role="status" className="rounded-xl border border-border p-3 text-sm">Опубликовано в ленте</p>
  if (!expanded) return <Button variant="outline" size="sm" disabled={disabled} onClick={() => setExpanded(true)}>Опубликовать в ленту</Button>

  return <section aria-label="Публикация Genjutsu" className="min-w-0 space-y-3 rounded-2xl border border-border p-3">
    <p className="text-sm font-medium">Результат появится в общей ленте и вашем профиле</p>
    <p className="text-xs text-muted-foreground">Промпт и исходные референсы останутся скрытыми. Выберите, какое видео потребуется для повтора.</p>
    <fieldset disabled={disabled || pending || Boolean(declaration.current)} className="min-w-0 space-y-3">
      <label className="block space-y-1 text-sm">Название публикации<input className={field} maxLength={120} value={title} onChange={event => setTitle(event.target.value)} /></label>
      <label className="block space-y-1 text-sm">Видео при повторе<select className={field} value={sourceBinding} onChange={event => setSourceBinding(event.target.value as 'user' | 'fixed')}>
        <option value="user">Пользователь загружает своё видео</option>
        <option value="fixed">Скрытое видео автора без замены</option>
      </select></label>
    </fieldset>
    <p className="text-xs text-muted-foreground">{sourceBinding === 'user'
      ? 'Для повтора нужно своё видео. Исходное видео автора не показывается.'
      : 'Повтор использует исходное видео автора. Оно скрыто и не заменяется.'}</p>
    {run.plan.steps.some(item => item.references.length > 0) && <div className="space-y-1 text-xs text-muted-foreground">
      <p className="font-medium">Фото при повторе — из настроек завершённой работы:</p>
      {run.plan.steps.flatMap((item, stepIndex) => item.references.map((reference, index) => <p key={stepIndex + ':' + index}>
        {reference.label || roleLabels[reference.role] || 'Фото ' + (index + 1)}: {reference.binding === 'fixed' ? 'скрытый закреплённый референс' : 'своё фото при повторе'}
      </p>))}
    </div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {error && canRetry && <p className="text-xs text-muted-foreground">Повторная попытка сохранит эти настройки и не создаст вторую публикацию.</p>}
    <div className="flex flex-wrap gap-2">
      <Button size="sm" disabled={disabled || pending || !canRetry || !title.trim()} onClick={() => void publish()}>{pending ? 'Публикуем…' : !canRetry ? 'Публикация недоступна' : declaration.current ? 'Повторить публикацию' : 'Опубликовать результат'}</Button>
      <Button size="sm" variant="ghost" disabled={pending} onClick={() => setExpanded(false)}>Отмена</Button>
    </div>
  </section>
}
