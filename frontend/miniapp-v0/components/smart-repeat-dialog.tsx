'use client'

import { useEffect, useRef, useState } from 'react'
import { useApp } from '@/lib/app-context'
import { smartRepeatCall, type RepeatDraft, type RepeatSlot } from '@/lib/smart-repeat-api'
import { uploadFile } from '@/lib/api'
import { uploadSeedance25Video } from '@/lib/seedance25-api'
import { uploadWan3PrimeReference } from '@/lib/wan3-prime-api'
import type { UploadedFile } from '@/lib/types'
import { Button } from './ui/button'
import { Dialog, DialogContent, DialogTitle } from './ui/dialog'

export function SmartRepeatDialog({ sourceId, onClose }: { sourceId: number | null; onClose: () => void }) {
  const { state, addTask, setCredits, addSavedReference, refreshTasks, selectTask } = useApp()
  const [draft, setDraft] = useState<RepeatDraft | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [updating, setUpdating] = useState(0)
  const [uploading, setUploading] = useState<Set<string>>(new Set())
  const [slotErrors, setSlotErrors] = useState<Record<string, string>>({})
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
    setDraft(null); setError(''); setUploading(new Set()); setSlotErrors({}); setUserValues({})
    submitting.current = false; setBusy(false); setUpdating(0)
    slotEpochs.current = {}
    if (sourceId) {
      smartRepeatCall<RepeatDraft>('open', { source_id: sourceId }, controller.signal)
        .then(next => { accept(next, generation); if (generation === session.current) setUserValues(next.user_values) })
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
      const ready = await smartRepeatCall<RepeatDraft>('update', { draft_id: draftId, operation: 'ready', slot_id: slot.slot_id, upload_token: token,
        ...(uploaded.saved_reference_id ? { saved_reference_id: uploaded.saved_reference_id } : { url: uploaded.url }) })
      accept(ready, generation)
      if (generation === session.current) addSavedReference(uploaded)
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
  const required = slots.filter(slot => slot.required)
  const ready = required.filter(slot => draft?.slots[slot.slot_id]?.state === 'READY').length
  const variablesReady = (draft?.template.variables || []).every(variable => {
    const value = userValues[variable.id] || ''
    return (!variable.required || Boolean(value.trim())) && value.length <= variable.max_length
  })
  const invalidFile = slots.some(slot => ['UPLOADING', 'PROCESSING', 'FAILED'].includes(draft?.slots[slot.slot_id]?.state || 'EMPTY'))
  const valuesSaved = (draft?.template.variables || []).every(variable => (draft?.user_values[variable.id] || '') === (userValues[variable.id] || ''))
  const canRequest = Boolean(draft && draft.status === 'draft' && ready === required.length && variablesReady && valuesSaved && !invalidFile && !uploading.size && !busy && !updating)

  const submit = async () => {
    if (!draft || !canRequest || submitting.current) return
    submitting.current = true; setBusy(true); setError('')
    const generation = session.current
    try {
      if (!draft.quote) {
        const next = await smartRepeatCall<RepeatDraft>('quote', { draft_id: draft.draft_id })
        accept(next, generation)
      } else {
        const result = await smartRepeatCall<{ task_id?: string; internal_task_id?: string; credits?: number; status?: string }>('launch', {
          draft_id: draft.draft_id, quote_id: draft.quote.quote_id,
        })
        if (generation !== session.current) return
        const taskId = result.task_id || result.internal_task_id
        if (taskId) {
          addTask({ task_id: taskId, type: draft.template.type, model: draft.template.model,
            model_label: [...state.videoModels, ...state.imageModels].find(m => m.id === draft.template.model)?.label || draft.template.model,
            status: result.status === 'done' ? 'completed' : 'pending', aspect_ratio: '',
            created_at: new Date().toISOString(), cost: draft.quote.cost,
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

  return <Dialog open={Boolean(sourceId)} onOpenChange={open => { if (!open) onClose() }}>
    <DialogContent className="max-h-[90dvh] overflow-y-auto min-w-0" aria-describedby={undefined}>
      <DialogTitle>{draft?.template.type === 'image' ? 'Повторить фото' : 'Повторить видео'}</DialogTitle>
      {!draft && !error ? <p role="status">Восстанавливаем ваши файлы…</p> : null}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
      {draft ? <>
        <p className="text-sm text-muted-foreground">Модель исходной работы: {[...state.videoModels, ...state.imageModels].find(m => m.id === draft.template.model)?.label || draft.template.model}</p>
        {draft.status !== 'draft' ? <div className="space-y-3">
          <p role="status">{draft.status === 'rejected' ? 'Запуск отклонён. Можно создать новый повтор.' : draft.task_id ? 'Задача сохранена в истории.' : 'Проверяем ранее созданную операцию. Повторный запуск заблокирован.'}</p>
          <Button onClick={async () => { await refreshTasks(); onClose(); if (draft.task_id) selectTask({
            task_id: draft.task_id, type: draft.template.type, model: draft.template.model, model_label: draft.template.model,
            status: 'pending', aspect_ratio: '', created_at: new Date().toISOString(), cost: draft.quote?.cost || 0, prompt_preview: '', prompt_hidden: true,
          }) }}>Открыть историю</Button>
          {draft.status === 'rejected' || state.recentTasks.some(task => task.task_id === draft.task_id && task.status !== 'pending') ? <Button variant="outline" disabled={busy} onClick={async () => {
            setBusy(true)
            try { const next = await smartRepeatCall<RepeatDraft>('open', { source_id: sourceId, new: true }); accept(next, session.current); setUserValues(next.user_values); setError('') }
            catch (e) { setError(e instanceof Error ? e.message : 'Не удалось создать новый повтор.') }
            finally { setBusy(false) }
          }}>Повторить ещё раз</Button> : null}
        </div> : <>
          {draft.template.presets.length ? <label className="text-sm">Что заменить
            <select aria-label="Вариант персонализации" className="mt-1 w-full rounded border bg-background p-2" value={draft.preset_id || ''}
              disabled={busy || Boolean(uploading.size)} onChange={event => { setError(''); update({ operation: 'preset', preset_id: event.target.value || null }).catch(e => setError(e.message)) }}>
              <option value="">Все поля</option>{draft.template.presets.map(preset => <option key={preset.id} value={preset.id}>{preset.label}</option>)}
            </select>
          </label> : null}
          <p role="status" className="text-sm">Загружено обязательных референсов: {ready} / {required.length}</p>
          {slots.map((slot, index) => {
            const asset = draft.slots[slot.slot_id]
            const pending = uploading.has(slot.slot_id)
            const savedFiles = state.savedReferences.filter(file => file.type === slot.kind && !Object.values(draft.slots).some(value => value.url === file.url)).slice(0, 6)
            const selectedName = asset?.filename || state.savedReferences.find(file =>
              (asset?.saved_reference_id && file.saved_reference_id === asset.saved_reference_id) || file.url === asset?.url)?.name
            return <fieldset key={slot.slot_id} aria-label={slot.label} className="min-w-0 rounded-xl border p-3 space-y-2" disabled={busy}>
              <legend className="text-sm font-medium">{index + 1}. {slot.label}{slot.required ? ' · Обязательно' : ''}</legend>
              {slot.hint ? <p className="text-xs text-muted-foreground">{slot.hint}</p> : null}
              <p role="status" className="text-xs">{asset?.state === 'READY' ? 'Файл готов' : pending || asset?.state === 'UPLOADING' ? 'Загружаем файл…' : asset?.state === 'PROCESSING' ? 'Проверяем файл…' : asset?.state === 'FAILED' ? 'Ошибка загрузки' : 'Файл не выбран'}</p>
              {asset?.state === 'READY' ? <p className="break-words text-xs font-medium">{selectedName ? `Выбрано: ${selectedName}` : 'Файл закреплён за этим полем'}</p> : null}
              {asset?.state === 'READY' && asset.url && slot.kind === 'image' ? <img alt={slot.label} src={asset.url} className="max-h-28 max-w-full rounded object-contain" /> : null}
              <input aria-label={`Загрузить: ${slot.label}`} type="file" accept={`${slot.kind}/*`} disabled={pending}
                onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void upload(slot, file) }} className="block w-full min-w-0 text-xs" />
              {savedFiles.length ? <div className="space-y-2">
                <p className="text-xs text-muted-foreground">Или выберите из ваших сохранённых файлов. Файл добавится в это поле после выбора.</p>
                {savedFiles.map(file => <button key={file.id} type="button" aria-label={`Выбрать: ${file.name}`} disabled={pending}
                  className="flex w-full min-w-0 items-center gap-2 rounded-lg border p-2 text-left text-xs hover:bg-accent disabled:opacity-50"
                  onClick={() => void upload(slot, undefined, file)}>
                  {file.type === 'image' ? <img alt="" src={file.preview_url || file.url} loading="lazy" className="h-12 w-12 shrink-0 rounded object-cover" /> : null}
                  <span className="min-w-0"><span className="block truncate">{file.name}</span><span className="text-primary">Выбрать для этого поля</span></span>
                </button>)}
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
          {!slots.length ? <p className="text-sm">Автор сохранил необходимые исходники. Дополнительные файлы не нужны.</p> : null}
          {draft.template.variables.map(variable => <label key={variable.id} className="text-sm">{variable.label}
            <input className="mt-1 w-full rounded border bg-background p-2" value={userValues[variable.id] || ''} maxLength={variable.max_length} required={variable.required}
              onChange={event => { setUserValues(current => ({ ...current, [variable.id]: event.target.value })); setDraft(current => current ? { ...current, quote: null } : current) }}
              onBlur={() => update({ operation: 'values', user_values: userValues }).catch(e => setError(e.message))} />
          </label>)}
          <Button className="w-full" disabled={!canRequest} onClick={submit}>{busy ? 'Проверяем…' : draft.quote ? `Создать ${draft.template.type === 'image' ? 'фото' : 'видео'} · ${draft.quote.cost}🍌` : 'Рассчитать стоимость'}</Button>
          <p className="text-xs text-muted-foreground">Для запуска загрузите и проверьте все обязательные файлы, затем подтвердите стоимость.</p>
        </>}
      </> : null}
    </DialogContent>
  </Dialog>
}
