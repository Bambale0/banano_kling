'use client'

import { useEffect, useRef, useState } from 'react'
import {
  fetchVkGenerationClaim,
  fetchVkModelCatalog,
  generateVkImage,
  generateVkVideo,
  repeatVkTrend,
  uploadVkImage,
  type VkImageRequest,
  type VkVideoRequest,
  type VkNativeModelCatalog,
  type VkTrendRequest,
  type VkPublicTrend,
} from '@/lib/shared-account-api'

type QuotePayload =
  | { mode: 'trend'; data: VkTrendRequest }
  | { mode: 'image'; data: VkImageRequest }
  | { mode: 'video'; data: VkVideoRequest }

function newClientRequestId(): string {
  const bytes = new Uint8Array(16)
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes)
  } else {
    throw new Error('Защищённый генератор идентификаторов недоступен. Обновите WebView.')
  }
  return 'vk_' + Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}

export function VkGenerationPanel({
  trend, onFinished, onClose, kind = 'photo',
}: {
  kind?: 'photo' | 'video'
  trend?: VkPublicTrend
  onFinished?: () => void
  onClose: () => void
}) {
  const [model, setModel] = useState('')
  const [prompt, setPrompt] = useState('')
  const [aspect, setAspect] = useState('')
  const [resolution, setResolution] = useState('')
  const [duration, setDuration] = useState('')
  const [userValues, setUserValues] = useState<Record<string, string>>({})
  const [files, setFiles] = useState<File[]>([])
  const [cost, setCost] = useState<number | null>(null)
  const [quoted, setQuoted] = useState<QuotePayload | null>(null)
  const [clientRequestId, setClientRequestId] = useState('')
  const [taskId, setTaskId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const epoch = useRef(0)
  const [catalog, setCatalog] = useState<VkNativeModelCatalog | null>(null)
  const [catalogError, setCatalogError] = useState('')
  const [catalogLoading, setCatalogLoading] = useState(!trend)

  useEffect(() => {
    if (trend) return
    const controller = new AbortController()
    fetchVkModelCatalog(controller.signal).then(data => {
      if (controller.signal.aborted) return
      if (kind === 'video') {
        const first = data.video_models.find(item =>
          item.ratios.length > 0 && Array.isArray(item.durations)
          && item.durations.length > 0 && item.scenarios.length > 0,
        )
        if (!first) {
          setCatalogError('ВК-генератор пока не предоставляет доступных моделей видео.')
          return
        }
        setCatalog(data)
        setModel(first.id)
        setAspect(first.ratios[0])
        setDuration(String(first.durations![0]))
      } else {
        const first = data.photo_models[0]
        if (!first || !first.ratios.length || !first.resolutions.length) {
          setCatalogError('ВК-генератор пока не предоставляет доступных моделей.')
          return
        }
        setCatalog(data)
        setModel(first.id)
        setAspect(first.ratios[0])
        setResolution(first.resolutions[0])
      }
    }).catch(cause => {
      if (!controller.signal.aborted) setCatalogError(
        cause instanceof Error ? cause.message : 'Не удалось загрузить модели ВКонтакте.',
      )
    }).finally(() => {
      if (!controller.signal.aborted) setCatalogLoading(false)
    })
    return () => controller.abort()
  }, [trend, kind])

  const selectedPhotoModel = catalog?.photo_models.find(item => item.id === model)
  const selectedVideoModel = catalog?.video_models.find(item => item.id === model)
  const selectedModel = kind === 'video' ? selectedVideoModel : selectedPhotoModel
  const referenceLimit = trend ? 4 : kind === 'video'
    ? selectedVideoModel?.scenarios.includes('imgtxt') ? selectedVideoModel.max_image_references : 0
    : selectedPhotoModel?.max_references ?? 0

  const invalidate = () => {
    epoch.current += 1
    setCost(null)
    setQuoted(null)
    setClientRequestId('')
    setTaskId(null)
    setError('')
  }

  const quote = async () => {
    if (busy) return
    const runId = ++epoch.current
    setBusy(true)
    setError('')
    setCost(null)
    setQuoted(null)
    setTaskId(null)
    try {
      if (!trend && (!selectedModel || catalogLoading)) {
        throw new Error('Нет подтверждённых моделей ВКонтакте.')
      }
      if (files.length > referenceLimit) throw new Error('Выберите не более ' + referenceLimit + ' фотографий.')
      if (kind === 'video' && !trend && (
        !selectedVideoModel?.durations?.includes(Number(duration))
        || !selectedVideoModel.ratios.includes(aspect)
      )) throw new Error('Выберите доступные параметры видео.')
      if (trend && !files.length) throw new Error('Для повтора тренда загрузите своё фото.')
      if (!trend && !prompt.trim()) throw new Error('Введите промпт для создания изображения.')
      const references: string[] = []
      for (const file of files) {
        const url = await uploadVkImage(file)
        references.push(url)
      }
      const request: QuotePayload = trend
        ? { mode: 'trend', data: {
          trend_id: trend.id, reference_urls: references, user_values: userValues,
        }}
        : kind === 'video'
          ? { mode: 'video', data: {
            model, prompt: prompt.trim(), aspect, duration: Number(duration), reference_photos: references,
          }}
          : { mode: 'image', data: {
            model, prompt: prompt.trim(), aspect, resolution, reference_photos: references,
          }}
      const result = request.mode === 'trend'
        ? await repeatVkTrend({ ...request.data, quote_only: true })
        : request.mode === 'video'
          ? await generateVkVideo({ ...request.data, quote_only: true })
          : await generateVkImage({ ...request.data, quote_only: true })
      if (runId !== epoch.current) return
      if (!Number.isFinite(result.cost) || result.cost <= 0) {
        throw new Error('Сервер не смог рассчитать стоимость.')
      }
      setCost(result.cost)
      setQuoted(request)
      setClientRequestId(newClientRequestId())
    } catch (failure) {
      if (runId === epoch.current) setError(
        failure instanceof Error ? failure.message : 'Не удалось рассчитать цену.',
      )
    } finally {
      if (runId === epoch.current) setBusy(false)
    }
  }

  const run = async () => {
    if (busy || cost === null || !quoted || !clientRequestId || taskId !== null) return
    const runId = epoch.current
    setBusy(true)
    setError('')
    try {
      const result = quoted.mode === 'trend'
        ? await repeatVkTrend({ ...quoted.data, client_request_id: clientRequestId, expected_cost: cost })
        : quoted.mode === 'video'
          ? await generateVkVideo({ ...quoted.data, client_request_id: clientRequestId, expected_cost: cost })
          : await generateVkImage({ ...quoted.data, client_request_id: clientRequestId, expected_cost: cost })
      if (runId !== epoch.current) return
      if (!Number.isSafeInteger(result.task_id) || result.task_id <= 0) {
        throw new Error('Сервер не подтвердил создание задачи. Проверьте историю.')
      }
      setTaskId(result.task_id)
      setCost(null)
      onFinished?.()
    } catch {
      if (runId !== epoch.current) return
      // Provider charge/task may have committed before a BFF/WebView timeout.
      // Reconcile the SAME native idempotency claim, never auto-submit again.
      try {
        const claim = await fetchVkGenerationClaim(clientRequestId)
        if (runId !== epoch.current) return
        if (claim.found && claim.task_type === (quoted.mode === 'video' ? 'video' : 'photo')
          && Number.isSafeInteger(claim.task_id) && (claim.task_id || 0) > 0) {
          setTaskId(claim.task_id!)
          setCost(null)
          onFinished?.()
          return
        }
      } catch {
        // An unavailable read does not prove the paid task never existed.
      }
      if (runId === epoch.current) setError(
        'Статус генерации пока неясен. Проверьте «Мои работы». '
        + 'Повторная отправка использует тот же запрос и не создаёт новый ключ списания.',
      )
    } finally {
      if (runId === epoch.current) setBusy(false)
    }
  }

  return <section aria-label={trend ? 'Повтор тренда' : kind === 'video' ? 'Создание видео' : 'Создание фото'} className="space-y-3 rounded-2xl border border-primary/30 bg-card p-4">
    <div className="flex items-start justify-between gap-2">
      <h3 className="text-base font-semibold">{trend ? 'Повтор «' + trend.title + '»' : kind === 'video' ? 'Создать видео во ВКонтакте' : 'Создать фото во ВКонтакте'}</h3>
      <button type="button" onClick={onClose} disabled={busy} className="text-sm underline">Закрыть</button>
    </div>
    {!trend ? <>
      <label className="block space-y-1 text-sm">Модель
        <select aria-label="Модель" value={model} disabled={busy} onChange={event => {
          invalidate()
          setModel(event.target.value)
          if (kind === 'video') {
            const item = catalog?.video_models.find(value => value.id === event.target.value)
            setAspect(item?.ratios[0] ?? '')
            setDuration(String(item?.durations?.[0] ?? ''))
          } else {
            const item = catalog?.photo_models.find(value => value.id === event.target.value)
            setAspect(item?.ratios[0] ?? '')
            setResolution(item?.resolutions[0] ?? '')
          }
        }}
          className="w-full rounded-lg border border-border bg-background p-2">
          {(kind === 'video' ? catalog?.video_models.filter(item =>
            item.ratios.length > 0 && Array.isArray(item.durations)
            && item.durations.length > 0 && item.scenarios.length > 0,
          ) : catalog?.photo_models)?.map(item =>
            <option value={item.id} key={item.id}>{item.label}</option>)}
        </select>
      </label>
      <label className="block space-y-1 text-sm">Промпт
        <textarea aria-label="Промпт" value={prompt} disabled={busy} onChange={event => { invalidate(); setPrompt(event.target.value) }}
          maxLength={40000} rows={3} className="w-full rounded-lg border border-border bg-background p-2" />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="block space-y-1 text-sm">Формат
          <select aria-label="Формат" value={aspect} disabled={busy} onChange={event => { invalidate(); setAspect(event.target.value) }}
            className="w-full rounded-lg border border-border bg-background p-2">
            {selectedModel?.ratios.map(value => <option key={value}>{value}</option>)}
          </select>
        </label>
        {kind === 'video'
          ? <label className="block space-y-1 text-sm">Длительность
            <select aria-label="Длительность" value={duration} disabled={busy}
              onChange={event => { invalidate(); setDuration(event.target.value) }}
              className="w-full rounded-lg border border-border bg-background p-2">
              {selectedVideoModel?.durations?.map(value => <option key={value} value={String(value)}>{value} с</option>)}
            </select>
          </label>
          : <label className="block space-y-1 text-sm">Качество
            <select aria-label="Качество" value={resolution} disabled={busy}
              onChange={event => { invalidate(); setResolution(event.target.value) }}
              className="w-full rounded-lg border border-border bg-background p-2">
              {selectedPhotoModel?.resolutions.map(value => <option key={value}>{value}</option>)}
            </select>
          </label>}
      </div>
    </> : <>
      <p className="text-sm text-muted-foreground">Промпт автора сохраняется приватным. Изменяются только выбранные вами поля и фотографии.</p>
      {(trend.user_fields || []).map(field => <label key={field.key} className="block space-y-1 text-sm">
        {field.label}
        <input aria-label={field.label} value={userValues[field.key] || ''} disabled={busy}
          type={(field.type || field.field_type) === 'date' ? 'date' : (field.type || field.field_type) === 'number' ? 'number' : 'text'}
          maxLength={field.max_length || 400}
          required={field.required !== false}
          onChange={event => { invalidate(); setUserValues(prev => ({ ...prev, [field.key]: event.target.value })) }}
          className="w-full rounded-lg border border-border bg-background p-2" />
      </label>)}
    </>}
    {catalogError && !trend ? <p role="alert" className="text-sm text-destructive">{catalogError}</p> : null}
    <label className="block space-y-1 text-sm">Фото-референсы
      <input aria-label="Фото-референсы" type="file" disabled={busy || referenceLimit === 0} multiple accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
        onChange={event => { invalidate(); setFiles(Array.from(event.target.files || [])) }}
        className="block w-full text-xs" />
    </label>
    <p className="text-xs text-muted-foreground">
      До {referenceLimit} фото, каждое до 12 МБ. Стоимость рассчитывает VK-сервер перед списанием.
      {kind === 'video' ? ' Видеофайлы пока нельзя использовать как референсы.' : ''}
    </p>
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    {taskId !== null ? <p role="status" className="text-sm font-semibold">Задача #{taskId} создана. Следите за результатом в «Мои работы».</p>
      : cost !== null && quoted ? <button type="button" onClick={() => void run()} disabled={busy}
          className="w-full rounded-xl bg-primary px-4 py-3 font-semibold text-primary-foreground">
          {busy ? 'Создаём задачу…' : 'Создать за ' + cost + ' 🍌'}
        </button> : <button type="button" onClick={() => void quote()} disabled={busy || (!trend && (catalogLoading || !selectedModel))}
          className="w-full rounded-xl bg-primary px-4 py-3 font-semibold text-primary-foreground">
          {busy ? 'Рассчитываем…' : 'Рассчитать стоимость'}
        </button>}
  </section>
}
