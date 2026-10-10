'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { fetchWan3PrimeTrendRecipe, publishWan3PrimeTrend, type Wan3PrimeRepeatSlot } from '@/lib/wan3-prime-api'

function slotLabel(slot: Wan3PrimeRepeatSlot) {
  if (slot.role === 'first_frame') return 'Первый кадр'
  if (slot.role === 'last_frame') return 'Последний кадр'
  return ({ image: 'Image', video: 'Video', audio: 'Audio', file: 'Документ ', link: 'Страница ' }[slot.kind]) + (slot.index + 1)
}
export function Wan3TrendPublisher({ taskId }: { taskId: string }) {
  const [slots, setSlots] = useState<Array<Wan3PrimeRepeatSlot & { url: string }> | null>(null)
  const [replace, setReplace] = useState<string[]>([])
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [trendId, setTrendId] = useState<number | null>(null)
  const open = async () => {
    if (busy) return
    setBusy(true); setError('')
    try {
      const data = await fetchWan3PrimeTrendRecipe(taskId)
      setSlots(data.slots)
      const identity = data.slots.find(slot => slot.kind === 'image')
      setReplace(identity ? [identity.key] : [])
    } catch (error) { setError(error instanceof Error ? error.message : 'Не удалось восстановить рецепт.') }
    finally { setBusy(false) }
  }
  const publish = async () => {
    if (busy || !title.trim() || !slots) return
    setBusy(true); setError('')
    try {
      const data = await publishWan3PrimeTrend({ task_id: taskId, title: title.trim(), description: description.trim(), replacement_keys: replace })
      setTrendId(data.trend_id)
    } catch (error) { setError(error instanceof Error ? error.message : 'Не удалось подтвердить публикацию. Повтор с теми же параметрами не создаст дубликат.') }
    finally { setBusy(false) }
  }
  return <section className="min-w-0 space-y-3 rounded-xl border border-border/60 bg-secondary/20 p-3" aria-label="Публикация Wan-тренда">
    {!slots ? <Button type="button" variant="outline" className="w-full" disabled={busy} onClick={() => { void open() }}>{busy ? 'Загружаю…' : 'Создать тренд из Wan'}</Button> : trendId ?
      <p role="status" className="text-sm">Тренд #{trendId} опубликован в существующем разделе «Тренды». Все настройки модели сохранены.</p> : <>
      <p className="text-xs text-muted-foreground">Отметьте места, куда пользователь подставит свои файлы. Остальные материалы и промпт будут скрыты и подставлены сервером. Публикуя, вы разрешаете их использование в повторах.</p>
      {slots.map(slot => <label key={slot.key} className="flex min-w-0 items-start gap-2 rounded-lg border border-border p-2 text-xs">
        <input type="checkbox" disabled={busy} checked={replace.includes(slot.key)} aria-label={`Пользователь заменяет ${slotLabel(slot)}`} onChange={event => setReplace(old => event.target.checked ? [...old, slot.key] : old.filter(key => key !== slot.key))} />
        <span className="min-w-0 break-all">{slotLabel(slot)}{slot.role === 'source_video' ? ' — исходное видео' : ''}<span className="block text-muted-foreground">{slot.url.split('/').pop()}</span></span>
      </label>)}
      <label className="block space-y-1 text-sm">Название<Input aria-label="Название Wan-тренда" value={title} maxLength={60} onChange={e => setTitle(e.target.value)} disabled={busy} /></label>
      <label className="block space-y-1 text-sm">Инструкция для пользователя<Textarea aria-label="Описание Wan-тренда" value={description} maxLength={200} onChange={e => setDescription(e.target.value)} disabled={busy} /></label>
      <Button type="button" className="w-full" disabled={busy || !title.trim()} onClick={() => { void publish() }}>{busy ? 'Публикую…' : 'Опубликовать Wan-тренд'}</Button>
    </>}
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
  </section>
}
