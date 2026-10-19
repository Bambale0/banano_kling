'use client'

import { useEffect, useState } from 'react'
import { smartRepeatCall, type RepeatTemplate } from '@/lib/smart-repeat-api'
import { useApp } from '@/lib/app-context'
import { Button } from './ui/button'

export function SmartRepeatEditor({ sourceId, prompt = '' }: { sourceId: number; prompt?: string }) {
  const { state } = useApp()
  const [template, setTemplate] = useState<RepeatTemplate | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [pilotIds, setPilotIds] = useState('')
  useEffect(() => { setTemplate(null); setMessage('') }, [sourceId])

  const load = async () => {
    setBusy(true); setMessage('')
    try {
      const result = await smartRepeatCall<{ template: RepeatTemplate }>('template', { source_id: sourceId, author: true })
      const variables = [...new Set(Array.from(prompt.matchAll(/\{\{([a-zA-Z][a-zA-Z0-9_]*)\}\}/g), match => match[1]))]
      setTemplate({ ...result.template, variables: variables.map(id => result.template.variables.find(variable => variable.id === id)
        || { id, label: id, required: true, max_length: 80 }) })
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Не удалось открыть конструктор.') }
    finally { setBusy(false) }
  }
  const save = async () => {
    if (!template || busy) return
    setBusy(true); setMessage('')
    try {
      const result = await smartRepeatCall<{ template: RepeatTemplate }>('configure', { source_id: sourceId, template })
      setTemplate(result.template); setMessage('Новая версия полей сохранена. Уже запущенные задачи сохранят прежние настройки.')
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Не удалось сохранить поля.') }
    finally { setBusy(false) }
  }
  const rollout = async (enabled: boolean, pilot = false) => {
    setBusy(true)
    try {
      const telegramIds = pilot ? pilotIds.split(/[\s,]+/).filter(Boolean).map(Number) : []
      await smartRepeatCall('rollout', { enabled, telegram_ids: telegramIds })
      setMessage(enabled ? 'Умные повторы включены для всех. Обновите Mini App.' : pilot ? 'Пилот включён для выбранных пользователей.' : 'Умные повторы выключены. Старые повторы продолжают работать.')
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Не удалось изменить выпуск.') }
    finally { setBusy(false) }
  }

  return <section aria-label="Конструктор повтора" className="min-w-0 space-y-3 rounded-xl border p-3">
    <h3 className="text-sm font-semibold">Поля умного повтора</h3>
    <p className="text-xs text-muted-foreground">Выберите, какие исходники пользователь заменит своими файлами. Типы и привязка к модели сохраняются из вашей работы.</p>
    {!template ? <Button variant="outline" type="button" disabled={busy} onClick={load}>Настроить поля повтора</Button> : <>
      <p className="text-xs">Версия {template.version} · Заменяемых файлов: {template.slots.filter(slot => slot.binding === 'upload').length}</p>
      {template.slots.map((slot, index) => <fieldset key={slot.slot_id} className="min-w-0 rounded border p-2 space-y-2" disabled={busy}>
        <legend className="text-xs">Поле {index + 1} · {slot.kind === 'image' ? 'Фото' : slot.kind === 'video' ? 'Видео' : 'Аудио'}</legend>
        <label className="block text-xs">Название
          <input aria-label={`Название поля ${index + 1}`} value={slot.label} maxLength={80} className="mt-1 w-full rounded border bg-background p-2"
            onChange={event => setTemplate(current => current ? { ...current, slots: current.slots.map(item => item.slot_id === slot.slot_id ? { ...item, label: event.target.value } : item) } : current)} />
        </label>
        <label className="block text-xs">Подсказка
          <input aria-label={`Подсказка поля ${index + 1}`} value={slot.hint} maxLength={240} className="mt-1 w-full rounded border bg-background p-2"
            onChange={event => setTemplate(current => current ? { ...current, slots: current.slots.map(item => item.slot_id === slot.slot_id ? { ...item, hint: event.target.value } : item) } : current)} />
        </label>
        <select aria-label={`Действие для поля ${index + 1}`} value={slot.binding} className="w-full rounded border bg-background p-2 text-xs"
          onChange={event => setTemplate(current => current ? { ...current, slots: current.slots.map(item => item.slot_id === slot.slot_id ? { ...item, binding: event.target.value as 'fixed' | 'upload', required: event.target.value === 'upload' } : item) } : current)}>
          <option value="upload">Пользователь загружает свой файл</option>
          <option value="fixed" disabled={!slot.can_keep_original}>Сохранить мой исходник скрыто</option>
        </select>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={slot.required} disabled={slot.binding === 'fixed' || !slot.can_keep_original}
          onChange={event => setTemplate(current => current ? { ...current, slots: current.slots.map(item => item.slot_id === slot.slot_id ? { ...item, required: event.target.checked } : item) } : current)} />Обязательное поле</label>
        {!slot.can_keep_original ? <p className="text-xs text-muted-foreground">Чтобы разрешить пропуск, сначала разрешите скрытое использование этого исходника в настройках публикации.</p> : null}
        <Button type="button" variant="outline" disabled={!index} onClick={() => setTemplate(current => {
          if (!current) return current
          const next = [...current.slots]; [next[index - 1], next[index]] = [next[index], next[index - 1]]
          return { ...current, slots: next }
        })}>Выше</Button>
      </fieldset>)}
      <h4 className="text-sm font-medium">Варианты персонализации</h4>
      {template.presets.map((preset, index) => <fieldset key={preset.id} className="rounded border p-2 space-y-2" disabled={busy}>
        <input aria-label={`Название варианта ${index + 1}`} value={preset.label} maxLength={80} className="w-full rounded border bg-background p-2 text-xs"
          onChange={event => setTemplate(current => current ? { ...current, presets: current.presets.map(item => item.id === preset.id ? { ...item, label: event.target.value } : item) } : current)} />
        {template.slots.filter(slot => slot.binding === 'upload').map(slot => <label key={slot.slot_id} className="flex gap-2 text-xs"><input type="checkbox" checked={preset.slot_ids.includes(slot.slot_id)}
          onChange={event => setTemplate(current => current ? { ...current, presets: current.presets.map(item => item.id === preset.id ? { ...item, slot_ids: event.target.checked ? [...item.slot_ids, slot.slot_id] : item.slot_ids.filter(id => id !== slot.slot_id) } : item) } : current)} />{slot.label}</label>)}
        <button type="button" className="text-xs underline" onClick={() => setTemplate(current => current ? { ...current, presets: current.presets.filter(item => item.id !== preset.id) } : current)}>Удалить вариант</button>
      </fieldset>)}
      <Button type="button" variant="outline" disabled={busy || template.presets.length >= 20} onClick={() => setTemplate(current => current ? {
        ...current, presets: [...current.presets, { id: crypto.randomUUID(), label: 'Новый вариант', slot_ids: current.slots.filter(slot => slot.binding === 'upload').map(slot => slot.slot_id) }],
      } : current)}>Добавить вариант</Button>
      {template.variables.map(variable => <fieldset key={variable.id} className="space-y-2 rounded border p-2" disabled={busy}>
        <legend className="text-xs">Переменная {variable.id}</legend>
        <input aria-label={`Подпись переменной ${variable.id}`} value={variable.label} maxLength={80} className="w-full rounded border bg-background p-2 text-xs"
          onChange={event => setTemplate(current => current ? { ...current, variables: current.variables.map(item => item.id === variable.id ? { ...item, label: event.target.value } : item) } : current)} />
        <label className="text-xs">Максимум символов<input type="number" min={1} max={160} value={variable.max_length} className="ml-2 w-20 rounded border bg-background p-1"
          onChange={event => setTemplate(current => current ? { ...current, variables: current.variables.map(item => item.id === variable.id ? { ...item, max_length: Number(event.target.value) } : item) } : current)} /></label>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={variable.required} onChange={event => setTemplate(current => current ? {
          ...current, variables: current.variables.map(item => item.id === variable.id ? { ...item, required: event.target.checked } : item),
        } : current)} />Обязательная переменная</label>
      </fieldset>)}
      <Button type="button" disabled={busy} onClick={save}>Сохранить новую версию</Button>
    </>}
    {state.user.isAdmin ? <div className="space-y-2 border-t pt-3">
      <p className="text-xs font-semibold">Выпуск умных повторов</p>
      <input aria-label="Telegram ID участников пилота" placeholder="Telegram ID через запятую" value={pilotIds} onChange={event => setPilotIds(event.target.value)} className="w-full rounded border bg-background p-2 text-xs" />
      <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" disabled={busy || !pilotIds.trim()} onClick={() => rollout(false, true)}>Включить пилот</Button>
        <Button type="button" disabled={busy} onClick={() => rollout(true)}>Включить всем</Button>
        <Button type="button" variant="outline" disabled={busy} onClick={() => rollout(false)}>Выключить</Button></div>
    </div> : null}
    {message ? <p role="status" className="text-xs">{message}</p> : null}
  </section>
}
