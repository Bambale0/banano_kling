'use client'

import { useEffect, useState } from 'react'
import { trendContent, type TrendContent } from '@/lib/trend-admin-api'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

export function TrendContentEditor({ trendId, disabled, onSaved }: {
  trendId: number
  disabled: boolean
  onSaved: (title: string) => Promise<void>
}) {
  const [original, setOriginal] = useState<TrendContent | null>(null)
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    let cancelled = false
    setOriginal(null)
    setError('')
    trendContent(trendId).then((content) => {
      if (cancelled) return
      setOriginal(content)
      setTitle(content.title)
      setPrompt(content.prompt_text)
    }).catch((reason) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить промпт')
    })
    return () => { cancelled = true }
  }, [trendId])

  const save = async () => {
    if (!original || saving || disabled) return
    setSaving(true)
    setSaved(false)
    setError('')
    try {
      const updated = await trendContent(trendId, {
        title, revision: original.revision,
        ...(original.prompt_editable ? { prompt_text: prompt } : {}),
      })
      setOriginal(updated)
      setTitle(updated.title)
      setPrompt(updated.prompt_text)
      await onSaved(updated.title)
      setSaved(true)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось сохранить тренд')
    } finally {
      setSaving(false)
    }
  }

  return <div className="space-y-3">
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    {!original && !error ? <p role="status">Загружаю название и промпт…</p> : null}
    {original ? <>
      <label className="block text-sm">Название тренда
        <input aria-label="Название тренда" maxLength={80} value={title} disabled={saving}
          onChange={(event) => { setTitle(event.target.value); setSaved(false) }}
          className="mt-1 w-full rounded-lg border border-border bg-background p-2" />
      </label>
      {original.prompt_editable ? <label className="block text-sm">Промпт тренда — виден только администраторам
        <Textarea aria-label="Промпт тренда" value={prompt} disabled={saving} rows={8}
          onChange={(event) => { setPrompt(event.target.value); setSaved(false) }} />
      </label> : <p className="text-xs text-muted-foreground">Промпт этого тренда хранится в отдельном рецепте. Откройте его в студии модели.</p>}
      <p className="text-xs text-muted-foreground">Изменения применяются к новым повторам. Сохраните ссылки на референсы и переменные шаблона.</p>
      <Button type="button" disabled={disabled || saving || !title.trim() || (original.prompt_editable && !prompt.trim())}
        onClick={() => void save()}>{saving ? 'Сохраняю…' : 'Сохранить название и промпт'}</Button>
      {saved ? <p role="status" className="text-sm">Изменения сохранены</p> : null}
    </> : null}
  </div>
}
