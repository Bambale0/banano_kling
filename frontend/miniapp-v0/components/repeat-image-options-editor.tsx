'use client'

import { useEffect, useRef, useState } from 'react'
import type { TrendUserField } from '@/lib/types'
import { uploadFile } from '@/lib/api'
import { normalizeMiniAppMediaUrl } from '@/lib/media-url'
import { createTrendRunRequestId } from '@/lib/trend-api'

export function RepeatImageOptionsEditor({ field, onChange, onBusyChange }: {
  field: TrendUserField
  onChange: (patch: Partial<TrendUserField>) => void
  onBusyChange: (busy: boolean) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const alive = useRef(true)
  const options = field.image_choices || []
  const fieldRef = useRef(field)
  const changeRef = useRef(onChange)
  fieldRef.current = field; changeRef.current = onChange
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  return <fieldset disabled={busy} className="space-y-2 sm:col-span-4">
    <legend className="text-xs text-muted-foreground">Варианты с изображениями</legend>
    <div className="grid grid-cols-3 gap-2">
      {options.map(option => <div key={option.id} className="min-w-0 space-y-1 rounded-xl border border-border/60 p-1">
        <img src={normalizeMiniAppMediaUrl(option.image_url)} alt={option.label} className="aspect-square w-full rounded-lg object-contain" />
        <input aria-label={`Название варианта ${option.label}`} value={option.label} maxLength={80}
          onChange={event => onChange({ image_choices: options.map(item => item.id === option.id ? { ...item, label: event.target.value } : item) })}
          className="w-full rounded border border-border bg-background px-2 py-1 text-xs" />
        <button type="button" className="w-full py-1 text-xs text-destructive"
          onClick={() => onChange({ image_choices: options.filter(item => item.id !== option.id) })}>Удалить</button>
      </div>)}
    </div>
    <label className="inline-flex min-h-10 cursor-pointer items-center rounded-lg border border-border px-3 text-xs">
      {busy ? 'Загрузка…' : 'Добавить изображение варианта'}
      <input type="file" accept="image/*" disabled={busy || options.length >= 12} className="sr-only"
        onChange={async event => {
          const file = event.target.files?.[0]
          event.target.value = ''
          if (!file || busy) return
          setBusy(true); onBusyChange(true); setError('')
          try {
            const uploaded = await uploadFile('repeat_choice_image', file)
            if (alive.current) changeRef.current({ type: 'text', choices: [], image_choices: [...(fieldRef.current.image_choices || []),
              { id: createTrendRunRequestId(), label: (file.name.replace(/\.[^.]+$/, '') || 'Вариант').slice(0, 80), image_url: uploaded.url }] })
          } catch (cause) {
            if (alive.current) setError(cause instanceof Error ? cause.message : 'Не удалось загрузить изображение')
          } finally {
            if (alive.current) { setBusy(false); onBusyChange(false) }
          }
        }} />
    </label>
    {options.length ? <label className="flex items-center gap-2 text-xs">
      <input type="checkbox" checked={Boolean(field.allow_custom_image)}
        onChange={event => onChange({ allow_custom_image: event.target.checked })} /> Разрешить загрузить свой вариант
    </label> : null}
    {error ? <p role="alert" className="text-xs text-destructive">{error}</p> : null}
  </fieldset>
}
