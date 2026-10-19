'use client'

import { useEffect, useRef, useState } from 'react'
import { ImagePlus, Plus, X } from 'lucide-react'
import type { RepeatDraft, RepeatSlot } from '@/lib/smart-repeat-api'
import type { UploadedFile } from '@/lib/types'
import { Button } from './ui/button'

type Props = {
  slots: RepeatSlot[]
  values: RepeatDraft['slots']
  limit: number
  savedFiles: UploadedFile[]
  uploading: Set<string>
  errors: Record<string, string>
  disabled: boolean
  onUpload: (slot: RepeatSlot, file?: File, saved?: UploadedFile) => Promise<void>
  onRemove: (slot: RepeatSlot) => Promise<void>
}

export function AdditionalRepeatImages({ slots, values, limit, savedFiles, uploading, errors, disabled, onUpload, onRemove }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const mounted = useRef(true)
  const working = useRef(false)
  const [batchPending, setBatchPending] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const attached = slots.filter(slot => values[slot.slot_id] || uploading.has(slot.slot_id))
  const available = slots.filter(slot => !values[slot.slot_id] && !uploading.has(slot.slot_id))
  const remaining = Math.max(0, Math.min(limit - attached.length, available.length))
  const library = savedFiles.filter(file => file.type === 'image' && !Object.values(values).some(asset =>
    asset.url === file.url || (asset.saved_reference_id && asset.saved_reference_id === file.saved_reference_id)
    || (asset.wan3_media_id && asset.wan3_media_id === file.wan3_media_id)))

  const add = async (files: File[], saved?: UploadedFile) => {
    if (disabled || working.current) return
    setError('')
    const count = saved ? 1 : files.length
    if (!count) return
    if (count > remaining) { setError(`Можно добавить ещё ${remaining} фото. Уменьшите количество выбранных файлов.`); return }
    // Empty/octet-stream MIME is common on mobile: the existing upload API
    // inspects bytes. A declared non-image must never be accepted as a photo.
    if (files.some(file => file.type && file.type !== 'application/octet-stream' && !file.type.startsWith('image/'))) {
      setError('В дополнительные референсы можно добавить только фото.'); return
    }
    working.current = true; setBatchPending(true)
    const targets = available.slice(0, count)
    try {
      for (let index = 0; index < targets.length; index += 1) {
        if (!mounted.current) return
        await onUpload(targets[index], saved ? undefined : files[index], saved)
      }
    } finally {
      working.current = false
      if (mounted.current) setBatchPending(false)
    }
  }

  return <section aria-label="Дополнительные референсы" className="min-w-0 space-y-3 rounded-2xl border border-border/60 bg-secondary/20 p-3">
    <div className="space-y-1">
      <h4 className="text-sm font-semibold">Дополнительные референсы <span className="font-normal text-muted-foreground">· Необязательно</span></h4>
      <p className="text-xs text-muted-foreground">Маникюр, телефон, чехол и другие детали. Основные фото останутся на своих местах.</p>
      <p className="text-xs text-muted-foreground">В поле «Что изменить» укажите, какие детали взять из этих фото.</p>
      <p role="status" className="text-xs">Дополнительных фото: {attached.length} / {limit}</p>
    </div>
    {attached.length > limit ? <p role="alert" className="text-xs text-destructive">Лимит модели изменился. Удалите лишние дополнительные фото перед расчётом.</p> : null}
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {attached.map((slot, index) => {
        const asset = values[slot.slot_id]
        const pending = uploading.has(slot.slot_id) || asset?.state === 'UPLOADING' || asset?.state === 'PROCESSING'
        const name = asset?.filename || savedFiles.find(file => file.url === asset?.url)?.name || slot.label
        return <div key={slot.slot_id} className="flex min-w-0 items-center gap-2 rounded-xl border p-2">
          {asset?.url && asset.state === 'READY' ? <img src={asset.url} alt={slot.label} className="h-14 w-14 shrink-0 rounded-lg object-cover" /> : <ImagePlus className="h-8 w-8 shrink-0" />}
          <div className="min-w-0 flex-1"><p className="truncate text-xs">{name}</p>
            <p role="status" className="text-xs text-muted-foreground">{pending ? 'Загружаем и проверяем…' : asset?.state === 'FAILED' ? 'Ошибка загрузки' : 'Фото добавлено'}</p>
            {errors[slot.slot_id] ? <p role="alert" className="break-words text-xs text-destructive">{errors[slot.slot_id]}</p> : null}
          </div>
          <Button type="button" variant="ghost" size="icon" aria-label={`Удалить дополнительное фото ${index + 1}`} disabled={disabled} onClick={() => void onRemove(slot)}><X className="h-4 w-4" /></Button>
        </div>
      })}
    </div>
    <input ref={input} type="file" multiple accept="image/*" aria-label="Загрузить дополнительные фото" className="sr-only"
      disabled={disabled || batchPending || remaining === 0}
      onChange={event => { const files = Array.from(event.target.files || []); event.target.value = ''; void add(files) }} />
    <Button type="button" variant="outline" className="min-h-11 w-full" disabled={disabled || batchPending || remaining === 0} onClick={() => input.current?.click()}>
      <ImagePlus className="h-4 w-4" />{batchPending ? 'Загружаем…' : 'Добавить фото'}
    </Button>
    {remaining === 0 && attached.length <= limit ? <p className="text-xs text-muted-foreground">Достигнут общий лимит референсов модели с учётом основных фото.</p> : null}
    {library.length > 0 && remaining > 0 ? <div className="space-y-2">
      <p className="text-xs text-muted-foreground">Из сохранённых — без повторной загрузки</p>
      <div className="max-h-64 space-y-2 overflow-y-auto">
        {library.map(file => <button key={file.id} type="button" aria-label={`Добавить дополнительное фото: ${file.name}`} disabled={disabled || batchPending}
          className="flex w-full min-w-0 items-center gap-2 rounded-xl border p-2 text-left text-xs disabled:opacity-50" onClick={() => void add([], file)}>
          <img src={file.preview_url || file.url} alt="" loading="lazy" className="h-12 w-12 shrink-0 rounded-lg object-cover" />
          <span className="min-w-0 flex-1 truncate">{file.name}</span><Plus className="h-5 w-5 shrink-0" />
        </button>)}
      </div>
    </div> : null}
    {error ? <p role="alert" className="text-xs text-destructive">{error}</p> : null}
  </section>
}
