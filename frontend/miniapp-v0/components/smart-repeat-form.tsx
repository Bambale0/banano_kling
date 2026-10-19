'use client'

import { useEffect, useRef, useState } from 'react'
import { useApp } from '@/lib/app-context'
import { smartRepeatCall, type RepeatDraft, type RepeatSlot } from '@/lib/smart-repeat-api'
import { uploadFile } from '@/lib/api'
import { uploadSeedance25Video } from '@/lib/seedance25-api'
import { uploadWan3PrimeReference } from '@/lib/wan3-prime-api'
import type { UploadedFile } from '@/lib/types'
import { Button } from './ui/button'
import { ImagePlus, Film, Music, Plus, X } from 'lucide-react'
import { Textarea } from './ui/textarea'
import { AdditionalRepeatImages } from './additional-repeat-images'

export function SmartRepeatForm({ sourceId, onClose }: { sourceId: number | null; onClose: (showSource?: boolean) => void | Promise<void> }) {
  const { state, addTask, setCredits, addSavedReference, refreshTasks, selectTask } = useApp()
  const [draft, setDraft] = useState<RepeatDraft | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [updating, setUpdating] = useState(0)
  const [uploading, setUploading] = useState<Set<string>>(new Set())
  const [slotErrors, setSlotErrors] = useState<Record<string, string>>({})
  const [promptChanges, setPromptChanges] = useState('')
  const [pickerSlot, setPickerSlot] = useState<string | null>(null)
  const [librarySlot, setLibrarySlot] = useState<string | null>(null)
  const [userValues, setUserValues] = useState<Record<string, string>>({})
  const session = useRef(0)
  const submitting = useRef(false)
  const slotEpochs = useRef<Record<string, number>>({})

  const accept = (next: RepeatDraft, generation: number) => {
    if (generation !== session.current) return
    setDraft(current => !current || current.draft_id !== next.draft_id || next.revision >= current.revision ? next : current)
  }

  useEffect(() => {
    const generation = ++session.current
    const controller = new AbortController()
    setDraft(null); setError(''); setUploading(new Set()); setSlotErrors({}); setUserValues({}); setPromptChanges(''); setPickerSlot(null); setLibrarySlot(null)
    submitting.current = false; setBusy(false); setUpdating(0)
    slotEpochs.current = {}
    if (sourceId) {
      smartRepeatCall<RepeatDraft>('open', { source_id: sourceId }, controller.signal)
        .then(next => { accept(next, generation); if (generation === session.current) { setUserValues(next.user_values); setPromptChanges(next.prompt_changes || '') } })
        .catch(e => { if (!controller.signal.aborted && generation === session.current) setError(e.message) })
    }
    return () => { controller.abort(); if (session.current === generation) session.current = generation + 1 }
  }, [sourceId])

  const update = async (payload: Record<string, unknown>, generation = session.current) => {
    if (!draft) throw new Error('Черновик ещё загружается.')
    setUpdating(current => current + 1)
    try {
      const next = await smartRepeatCall<RepeatDraft>('update', { draft_id: draft.draft_id, ...payload })
      accept(next, generation)
      return next
    } finally {
      if (generation === session.current) setUpdating(current => Math.max(0, current - 1))
    }
  }

  const upload = async (slot: RepeatSlot, file?: File, saved?: UploadedFile) => {
    if (!draft || submitting.current) return
    const generation = session.current
    const draftId = draft.draft_id
    const epoch = (slotEpochs.current[slot.slot_id] || 0) + 1
    slotEpochs.current[slot.slot_id] = epoch
    setUploading(current => new Set(current).add(slot.slot_id))
    setSlotErrors(current => ({ ...current, [slot.slot_id]: '' }))
    let token: string | undefined
    try {
      const begun = await update({ operation: 'begin', slot_id: slot.slot_id }, generation)
      token = begun.slots[slot.slot_id].upload_token
      if (generation !== session.current || slotEpochs.current[slot.slot_id] !== epoch) return
      let uploaded = saved
      if (file) {
        uploaded = draft.template.model.startsWith('wan_3')
          ? await uploadWan3PrimeReference(slot.kind, file)
          : slot.kind === 'video' && draft.template.model === 'seedance_2_5'
            ? await uploadSeedance25Video(file)
            : await uploadFile(`${slot.kind}_reference`, file)
      }
      if (!uploaded) throw new Error('Выберите файл.')
      if (generation !== session.current || slotEpochs.current[slot.slot_id] !== epoch) return
      await smartRepeatCall<RepeatDraft>('update', { draft_id: draftId, operation: 'processing', slot_id: slot.slot_id, upload_token: token })
      if (generation !== session.current || slotEpochs.current[slot.slot_id] !== epoch) return
      const ready = await smartRepeatCall<RepeatDraft>('update', { draft_id: draftId, operation: 'ready', slot_id: slot.slot_id, upload_token: token,
        ...(uploaded.wan3_media_id ? { wan3_media_id: uploaded.wan3_media_id }
          : uploaded.saved_reference_id ? { saved_reference_id: uploaded.saved_reference_id } : { url: uploaded.url }) })
      accept(ready, generation)
      if (generation === session.current) { addSavedReference(uploaded); setPickerSlot(null); setLibrarySlot(null) }
    } catch (e) {
      if (generation !== session.current || slotEpochs.current[slot.slot_id] !== epoch) return
      setSlotErrors(current => ({ ...current, [slot.slot_id]: e instanceof Error ? e.message : 'Не удалось загрузить файл.' }))
      if (token) {
        try {
          const failed = await smartRepeatCall<RepeatDraft>('update', { draft_id: draftId, operation: 'failed', slot_id: slot.slot_id, upload_token: token })
          accept(failed, generation)
        } catch { /* A replaced/cancelled upload cannot overwrite its successor. */ }
      }
    } finally {
      if (generation === session.current && slotEpochs.current[slot.slot_id] === epoch) setUploading(current => { const next = new Set(current); next.delete(slot.slot_id); return next })
    }
  }

  const selected = draft?.preset_id ? draft.template.presets.find(p => p.id === draft.preset_id)?.slot_ids || []
    : draft?.template.slots.filter(slot => slot.binding === 'upload').map(slot => slot.slot_id) || []
  const slots = draft?.template.slots.filter(slot => selected.includes(slot.slot_id)) || []
  const extraSlots = draft?.template.type === 'image' ? draft.additional_image_slots || [] : []
  const extraLimit = draft?.additional_image_limit || 0
  const extraOverLimit = extraSlots.filter(slot => draft?.slots[slot.slot_id]).length > extraLimit
  const required = slots.filter(slot => slot.required)
  const ready = required.filter(slot => draft?.slots[slot.slot_id]?.state === 'READY').length
  const variablesReady = (draft?.template.variables || []).every(variable => {
    const value = userValues[variable.id] || ''
    return (!variable.required || Boolean(value.trim())) && value.length <= variable.max_length
  })
  const invalidFile = [...slots, ...extraSlots].some(slot => ['UPLOADING', 'PROCESSING', 'FAILED'].includes(draft?.slots[slot.slot_id]?.state || 'EMPTY'))
  const canRequest = Boolean(draft && draft.status === 'draft' && ready === required.length && variablesReady && !extraOverLimit && !invalidFile && !uploading.size && !busy && !updating)

  const removeExtra = async (slot: RepeatSlot) => {
    const generation = session.current
    slotEpochs.current[slot.slot_id] = (slotEpochs.current[slot.slot_id] || 0) + 1
    setUploading(current => { const next = new Set(current); next.delete(slot.slot_id); return next })
    setSlotErrors(current => ({ ...current, [slot.slot_id]: '' }))
    try { await update({ operation: 'remove', slot_id: slot.slot_id }, generation) }
    catch (e) { if (generation === session.current) setError(e instanceof Error ? e.message : 'Не удалось удалить фото.') }
  }

  const persistEdits = async (generation = session.current) => {
    if (!draft) return null
    let next = draft
    if (draft.status !== 'draft') return next
    if ((draft.prompt_changes || '') !== promptChanges.trim()) {
      next = await update({ operation: 'changes', prompt_changes: promptChanges }, generation)
      if (generation !== session.current) return null
    }
    if (draft.template.variables.some(variable => (draft.user_values[variable.id] || '') !== (userValues[variable.id] || ''))) {
      next = await update({ operation: 'values', user_values: userValues }, generation)
      if (generation !== session.current) return null
    }
    return next
  }

  const close = async () => {
    if (busy || submitting.current) return
    const generation = session.current
    setBusy(true); setError('')
    try { await persistEdits(generation); if (generation === session.current) await onClose() }
    catch (e) { setError(e instanceof Error ? e.message : 'Не удалось сохранить изменения.'); setBusy(false) }
  }

  const newRepeat = async () => {
    const generation = session.current
    setBusy(true)
    try {
      const next = await smartRepeatCall<RepeatDraft>('open', { source_id: sourceId, new: true })
      if (generation !== session.current) return
      accept(next, generation); setUserValues(next.user_values); setPromptChanges(next.prompt_changes || ''); setError('')
    } catch (e) {
      if (generation === session.current) setError(e instanceof Error ? e.message : 'Не удалось создать новый повтор.')
    } finally {
      if (generation === session.current) setBusy(false)
    }
  }

  const submit = async () => {
    if (!draft || !canRequest || submitting.current) return
    submitting.current = true; setBusy(true); setError('')
    const generation = session.current
    try {
      const saved = await persistEdits(generation)
      if (!saved || generation !== session.current) return
      if (!saved.quote) {
        const next = await smartRepeatCall<RepeatDraft>('quote', { draft_id: draft.draft_id })
        accept(next, generation)
      } else {
        const result = await smartRepeatCall<{ task_id?: string; internal_task_id?: string; credits?: number; status?: string }>('launch', {
          draft_id: draft.draft_id, quote_id: saved.quote.quote_id,
        })
        if (generation !== session.current) return
        const taskId = result.task_id || result.internal_task_id
        if (taskId) {
          addTask({ task_id: taskId, type: draft.template.type, model: draft.template.model,
            model_label: [...state.videoModels, ...state.imageModels].find(m => m.id === draft.template.model)?.label || draft.template.model,
            status: result.status === 'done' ? 'completed' : 'pending', aspect_ratio: '',
            created_at: new Date().toISOString(), cost: saved.quote.cost,
            prompt_preview: '', prompt_hidden: true })
        }
        if (typeof result.credits === 'number') setCredits(result.credits)
        const next = await smartRepeatCall<RepeatDraft>('open', { source_id: sourceId })
        accept(next, generation)
        await refreshTasks()
      }
    } catch (e) {
      if (generation === session.current) {
        setError(e instanceof Error ? e.message : 'Не удалось проверить операцию.')
        // Recover authoritative state after a lost response; never replay a launch.
        try { accept(await smartRepeatCall<RepeatDraft>('open', { source_id: sourceId }), generation) } catch { /* Keep the draft for a later explicit check. */ }
      }
    } finally {
      if (generation === session.current) { submitting.current = false; setBusy(false) }
    }
  }

  const title = !draft ? 'Повторить публикацию' : draft.template.type === 'image' ? 'Повторить фото' : 'Повторить видео'
  return <section aria-label={title} className="glass min-w-0 space-y-4 rounded-2xl border border-border/50 p-4 sm:p-5">
      <div className="flex items-center justify-between gap-3"><h3 className="text-lg font-semibold">{title}</h3>
        <Button type="button" variant="ghost" size="icon" aria-label="Закрыть повтор" disabled={busy} onClick={() => void close()}><X /></Button></div>
      {!draft && !error ? <p role="status">Восстанавливаем ваши файлы…</p> : null}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
      {draft ? <>
        <p className="text-sm text-muted-foreground">Модель исходной работы: {[...state.videoModels, ...state.imageModels].find(m => m.id === draft.template.model)?.label || draft.template.model}</p>
        {draft.status !== 'draft' ? <div className="space-y-3">
          <p role="status">{draft.status === 'rejected' ? 'Запуск отклонён. Можно создать новый повтор.' : draft.task_id ? 'Задача сохранена в истории.' : 'Проверяем ранее созданную операцию. Повторный запуск заблокирован.'}</p>
          <Button onClick={async () => { await refreshTasks(); await onClose(false); if (draft.task_id) selectTask({
            task_id: draft.task_id, type: draft.template.type, model: draft.template.model, model_label: draft.template.model,
            status: 'pending', aspect_ratio: '', created_at: new Date().toISOString(), cost: draft.quote?.cost || 0, prompt_preview: '', prompt_hidden: true,
          }) }}>Открыть историю</Button>
          {draft.status === 'rejected' || state.recentTasks.some(task => task.task_id === draft.task_id && task.status !== 'pending') ? <Button variant="outline" disabled={busy} onClick={() => void newRepeat()}>Повторить ещё раз</Button> : null}
        </div> : <>
          <div className="space-y-2">
            <label htmlFor="repeat-prompt-changes" className="text-sm font-medium">Что изменить</label>
            <Textarea id="repeat-prompt-changes" aria-label="Что изменить" value={promptChanges} disabled={busy}
              placeholder="Опишите, что изменить. Остальное из исходной работы будет сохранено."
              className="min-h-[140px] resize-none bg-secondary/50 border-border/50 focus:border-gold/50 focus:ring-gold/20"
              onChange={event => { setPromptChanges(event.target.value); setDraft(current => current ? { ...current, quote: null } : current) }} />
          </div>
          {draft.template.presets.length ? <label className="text-sm">Что заменить
            <select aria-label="Вариант персонализации" className="mt-1 w-full rounded border bg-background p-2" value={draft.preset_id || ''}
              disabled={busy || Boolean(uploading.size)} onChange={event => { setError(''); update({ operation: 'preset', preset_id: event.target.value || null }).catch(e => setError(e.message)) }}>
              <option value="">Все поля</option>{draft.template.presets.map(preset => <option key={preset.id} value={preset.id}>{preset.label}</option>)}
            </select>
          </label> : null}
          <p role="status" className="text-sm">Загружено обязательных референсов: {ready} / {required.length}</p>
          {slots.map(slot => {
            const asset = draft.slots[slot.slot_id]
            const pending = uploading.has(slot.slot_id)
            const savedFiles = state.savedReferences.filter(file => file.type === slot.kind && !Object.values(draft.slots).some(value => value.url === file.url))
            const selectedName = asset?.filename || state.savedReferences.find(file =>
              (asset?.saved_reference_id && file.saved_reference_id === asset.saved_reference_id) || file.url === asset?.url)?.name
            const Icon = slot.kind === 'image' ? ImagePlus : slot.kind === 'video' ? Film : Music
            const expanded = pickerSlot === slot.slot_id
            return <fieldset key={slot.slot_id} aria-label={slot.label} className="min-w-0 space-y-3 rounded-2xl border border-dashed border-border/70 bg-secondary/30 p-3" disabled={busy}>
              <button type="button" aria-label={`Выбрать файл: ${slot.label}`} aria-expanded={expanded} disabled={pending}
                className="flex w-full min-w-0 items-center gap-3 text-left" onClick={() => { setPickerSlot(expanded ? null : slot.slot_id); setLibrarySlot(null) }}>
                {asset?.state === 'READY' && asset.url && slot.kind === 'image'
                  ? <img alt={slot.label} src={asset.url} className="h-16 w-16 shrink-0 rounded-xl object-cover" />
                  : <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-secondary"><Icon className="h-6 w-6" /></span>}
                <span className="min-w-0 flex-1"><span className="block break-words text-sm font-semibold">{slot.label}{slot.required ? ' · Обязательно' : ''}</span>
                  {slot.hint ? <span className="block text-xs text-muted-foreground">{slot.hint}</span> : null}
                  <span role="status" className="block text-xs text-muted-foreground">{asset?.state === 'READY' ? (selectedName ? `Выбрано: ${selectedName}` : 'Файл закреплён за этим полем') : pending || asset?.state === 'UPLOADING' ? 'Загружаем файл…' : asset?.state === 'PROCESSING' ? 'Проверяем файл…' : asset?.state === 'FAILED' ? 'Ошибка загрузки' : 'Выберите файл'}</span>
                </span>
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-secondary"><Plus className="h-5 w-5" /></span>
              </button>
              <input id={`repeat-upload-${slot.slot_id}`} aria-label={`Загрузить: ${slot.label}`} type="file" accept={`${slot.kind}/*`} disabled={pending}
                onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void upload(slot, file) }} className="sr-only" />
              {asset?.state === 'READY' && asset.url && slot.kind !== 'image' ? slot.kind === 'video'
                ? <video src={asset.url} controls playsInline preload="metadata" aria-label={slot.label} className="max-h-40 w-full rounded-xl" />
                : <audio src={asset.url} controls preload="metadata" aria-label={slot.label} className="w-full min-w-0" /> : null}
              {expanded ? <div className="space-y-3">
                <label htmlFor={`repeat-upload-${slot.slot_id}`} className="flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-xl border border-gold/40 bg-gold/10 px-3 text-sm"><Icon className="h-4 w-4" />Загрузить новый файл</label>
                <Button type="button" variant="outline" className="min-h-11 w-full" disabled={pending} onClick={() => setLibrarySlot(librarySlot === slot.slot_id ? null : slot.slot_id)}>Взять из сохранённых</Button>
                {librarySlot === slot.slot_id ? <div className="max-h-64 space-y-2 overflow-y-auto" aria-label={`Сохранённые файлы: ${slot.label}`}>
                  {!savedFiles.length ? <p className="text-xs text-muted-foreground">Подходящих сохранённых файлов пока нет. Загрузите новый файл.</p> : null}
                  {savedFiles.map(file => <button key={file.id} type="button" aria-label={`Выбрать: ${file.name}`} disabled={pending}
                    className="flex w-full min-w-0 items-center gap-2 rounded-lg border p-2 text-left text-xs hover:bg-accent disabled:opacity-50"
                    onClick={() => void upload(slot, undefined, file)}>
                    {file.type === 'image' ? <img alt="" src={file.preview_url || file.url} loading="lazy" className="h-12 w-12 shrink-0 rounded object-cover" /> : <Icon className="h-6 w-6 shrink-0" />}
                    <span className="min-w-0"><span className="block truncate">{file.name}</span><span className="text-primary">Выбрать для этого поля</span></span>
                  </button>)}
                </div> : null}
              </div> : null}
              {asset ? <button type="button" className="text-xs underline" onClick={() => {
                slotEpochs.current[slot.slot_id] = (slotEpochs.current[slot.slot_id] || 0) + 1
                setUploading(current => { const next = new Set(current); next.delete(slot.slot_id); return next })
                setSlotErrors(current => ({ ...current, [slot.slot_id]: '' }))
                update({ operation: 'remove', slot_id: slot.slot_id }).catch(e => setError(e.message))
              }}>Удалить файл</button> : null}
              {slotErrors[slot.slot_id] ? <p role="alert" className="text-xs text-destructive">{slotErrors[slot.slot_id]}</p> : null}
            </fieldset>
          })}
          {!slots.length ? <p className="text-sm">Автор сохранил необходимые исходники. Обязательные файлы загружать не нужно.</p> : null}
          {draft.template.type === 'image' && typeof draft.additional_image_limit === 'number' ? <AdditionalRepeatImages
            key={draft.draft_id} slots={extraSlots} limit={extraLimit} values={draft.slots}
            savedFiles={state.savedReferences} uploading={uploading} errors={slotErrors}
            disabled={busy || updating > 0} onUpload={upload} onRemove={removeExtra}
          /> : null}
          {draft.template.variables.map(variable => <label key={variable.id} className="text-sm">{variable.label}
            <input className="mt-1 w-full rounded border bg-background p-2" value={userValues[variable.id] || ''} maxLength={variable.max_length} required={variable.required}
              onChange={event => { setUserValues(current => ({ ...current, [variable.id]: event.target.value })); setDraft(current => current ? { ...current, quote: null } : current) }}
              disabled={busy} />
          </label>)}
          <Button className="w-full" disabled={!canRequest} onClick={submit}>{busy ? 'Проверяем…' : draft.quote ? `Создать ${draft.template.type === 'image' ? 'фото' : 'видео'} · ${draft.quote.cost}🍌` : 'Рассчитать стоимость'}</Button>
          <p className="text-xs text-muted-foreground">Для запуска загрузите и проверьте все обязательные файлы, затем подтвердите стоимость.</p>
        </>}
      </> : null}
  </section>
}
