'use client'

import { useEffect, useRef, useState } from 'react'

type Model = {
  id: string
  label: string
  type: 'image' | 'video'
  price?: string
  enabled?: boolean
  unavailable_reason?: string | null
  qualities?: string[]
  quality_costs?: Record<string, string>
  requires_reference?: boolean
  prices_by_duration?: Record<string, string>
  ratios: string[]
  durations?: number[]
  max_references?: number
  max_video_references?: number
  max_audio_references?: number
  max_file_references?: number
  max_link_references?: number
  requires_image?: boolean
  requires_audio?: boolean
  supports_layers?: boolean
  supports_output_format?: boolean
  supports_background?: boolean
  supports_nsfw_checker?: boolean
  layers_max_images?: { min: number; max: number; default: number }
  layers_formats?: string[]
  supported_modes?: string[]
}
type OmniAsset = {
  asset_id: string
  kind: 'audio' | 'character'
  name: string
}
type Task = {
  task_id: string
  type: 'image' | 'video'
  model: string
  status: 'pending' | 'completed' | 'failed'
  result_url: string | null
  created_at_epoch: number
  bundle_url?: string | null
  output_count?: number | null
  outputs?: string[]
  cost?: string
  result_seconds?: string | null
}

export function WebGenerationPanel({ onBalanceChanged, onTaskChanged }: {
  onBalanceChanged: () => void
  onTaskChanged: () => void
}) {
  const [models, setModels] = useState<Model[]>([])
  const [modelId, setModelId] = useState('')
  const [prompt, setPrompt] = useState('')
  const [ratio, setRatio] = useState('')
  const [duration, setDuration] = useState(5)
  const [quality, setQuality] = useState('')
  const [maxImages, setMaxImages] = useState(30)
  const [textRecognition, setTextRecognition] = useState(false)
  const [outputFormat, setOutputFormat] = useState('png')
  const [background, setBackground] = useState('auto')
  const [nsfwChecker, setNsfwChecker] = useState(false)
  const [wanScenario, setWanScenario] = useState('text')
  const [omniAssets, setOmniAssets] = useState<OmniAsset[]>([])
  const [omniAudioAsset, setOmniAudioAsset] = useState('')
  const [omniCharacterAssets, setOmniCharacterAssets] = useState<string[]>([])
  const [omniSeed, setOmniSeed] = useState('')
  const [quote, setQuote] = useState<{ price: string; key: string } | null>(null)
  const [quoteError, setQuoteError] = useState('')
  const [busy, setBusy] = useState(false)
  const [activeTask, setActiveTask] = useState<Task | null>(null)
  const [references, setReferences] = useState<{ id: string; name: string }[]>([])
  const [videoReferences, setVideoReferences] = useState<{ id: string; name: string }[]>([])
  const [audioReferences, setAudioReferences] = useState<{ id: string; name: string }[]>([])
  const [documentReferences, setDocumentReferences] = useState<{ id: string; name: string }[]>([])
  const [webpageReference, setWebpageReference] = useState<{ id: string; name: string } | null>(null)
  const [webpageUrl, setWebpageUrl] = useState('')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const idempotencyKey = useRef('')

  useEffect(() => {
    const controller = new AbortController()
    void fetch('/mini-app/api/web-auth/web-generation/models', {
      credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
    }).then(async response => {
      if (!response.ok) throw new Error('Model catalog failed')
      return await response.json() as { ok?: boolean; enabled?: boolean; models?: Model[] }
    }).then(data => {
      if (!controller.signal.aborted && data.ok && data.enabled && data.models?.length) {
        setModels(data.models)
        const first = data.models.find(entry => entry.enabled !== false)
        if (!first) {
          setError('Пока ни одна модель не активирована для веб-генерации.')
          return
        }
        setModelId(first.id)
        setRatio(first.ratios.includes('1:1') ? '1:1' : first.ratios[0])
        setDuration(first.durations?.includes(5) ? 5 : first.durations?.[0] || 5)
        setQuality(first.qualities?.includes('2K') ? '2K' : first.qualities?.[0] || '')
      }
    }).catch(() => {
      if (!controller.signal.aborted) setError('Не удалось загрузить модели и их актуальные цены.')
    })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const refreshAssets = () => {
      void fetch('/mini-app/api/web-auth/web-omni/assets', {
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      }).then(async response => {
        if (!response.ok) throw new Error('Omni assets unavailable')
        return response.json() as Promise<{ ok?: boolean; assets?: OmniAsset[] }>
      }).then(result => {
        if (!controller.signal.aborted && result.ok && Array.isArray(result.assets)) {
          setOmniAssets(result.assets)
        }
      }).catch(() => { /* Omni IDs are optional for video generation. */ })
    }
    refreshAssets()
    window.addEventListener('neuromix:omni-assets-updated', refreshAssets)
    return () => {
      controller.abort()
      window.removeEventListener('neuromix:omni-assets-updated', refreshAssets)
    }
  }, [])

  const uploadReference = async (file: File, kind: 'image' | 'video' | 'audio' | 'file') => {
    const current = kind === 'video' ? videoReferences : kind === 'audio' ? audioReferences
      : kind === 'file' ? documentReferences : references
    const maximum = kind === 'video' ? (model?.max_video_references || 0)
      : kind === 'audio' ? (model?.max_audio_references || 0)
        : kind === 'file' ? (model?.max_file_references || 0)
          : (model?.max_references || 0)
    if (uploading || current.length >= maximum) return
    setUploading(true)
    setError('')
    try {
      const body = new FormData()
      body.append(kind, file)
      const response = await fetch('/mini-app/api/web-auth/web-generation/reference', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', body,
      })
      const data = await response.json() as {
        ok?: boolean; reference_id?: string; error?: string
      }
      if (!response.ok || !data.ok || !data.reference_id) {
        throw new Error(data.error || 'Не удалось загрузить референс.')
      }
      const append = (previous: { id: string; name: string }[]) =>
        previous.some(item => item.id === data.reference_id)
          ? previous : [...previous, { id: data.reference_id!, name: file.name }]
      if (kind === 'video') setVideoReferences(append)
      else if (kind === 'audio') setAudioReferences(append)
      else if (kind === 'file') setDocumentReferences(append)
      else setReferences(append)
      idempotencyKey.current = ''
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Не удалось загрузить референс.')
    } finally {
      setUploading(false)
    }
  }

  const importWebpage = async () => {
    if (uploading || !webpageUrl.trim()) return
    setUploading(true)
    setError('')
    try {
      const response = await fetch('/mini-app/api/web-auth/web-generation/link', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: webpageUrl.trim() }),
      })
      const result = await response.json() as {
        ok?: boolean; reference_id?: string; error?: string
      }
      if (!response.ok || !result.ok || !result.reference_id) {
        throw new Error(result.error || 'Не удалось подтвердить ссылку.')
      }
      setWebpageReference({ id: result.reference_id, name: webpageUrl.trim() })
      idempotencyKey.current = ''
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Не удалось импортировать ссылку.')
    } finally {
      setUploading(false)
    }
  }

  const model = models.find(item => item.id === modelId)
  const isWan3 = modelId === 'wan_3' || modelId === 'wan_3_prime'
  const isOmni = modelId === 'gemini_omni'
  const referencesIds = references.map(item => item.id)
  const videoIds = videoReferences.map(item => item.id)
  const audioIds = audioReferences.map(item => item.id)
  const documentIds = documentReferences.map(item => item.id)
  const linkIds = webpageReference ? [webpageReference.id] : []
  const quoteKey = JSON.stringify({
    model: modelId, prompt: prompt.trim(), aspect_ratio: ratio,
    duration, quality, reference_ids: referencesIds,
    video_reference_ids: videoIds, audio_reference_ids: audioIds,
    ...(isWan3 ? {
      wan_scenario: wanScenario,
      file_reference_ids: documentIds, link_reference_ids: linkIds,
    } : {}),
    ...(isOmni ? {
      omni_audio_asset_ids: omniAudioAsset ? [omniAudioAsset] : [],
      omni_character_asset_ids: omniCharacterAssets,
      ...(omniSeed.trim() ? { omni_seed: Number(omniSeed) } : {}),
    } : {}),
    ...(model?.supports_layers ? {
      max_images: maxImages,
      text_recognition: textRecognition,
      output_format: outputFormat,
    } : {}),
    ...(model?.id === 'seedream_55' ? {
      output_format: outputFormat,
      background,
    } : {}),
    ...(model?.supports_nsfw_checker ? { nsfw_checker: nsfwChecker } : {}),
  })
  const quoteReady = Boolean(quote && quote.key === quoteKey)
  const price = quoteReady
    ? quote!.price
    : model?.quality_costs?.[quality]
      || model?.prices_by_duration?.[String(duration)]
      || model?.price || ''

  useEffect(() => {
    if (!model || model.enabled === false || prompt.trim().length < 2
      || (model.requires_reference && !references.length)
      || (model.requires_image && !references.length)
      || (model.requires_audio && !audioReferences.length)
      || (model.id.startsWith('motion_control_') && (!references.length || !videoReferences.length))
      || (isWan3 && (
        (wanScenario === 'file' && !documentIds.length)
        || (wanScenario === 'link' && !linkIds.length)
        || (wanScenario === 'edit' && !videoIds.length)
        || (wanScenario === 'first_frame' && referencesIds.length !== 1)
        || (wanScenario === 'first_last' && referencesIds.length !== 2)
        || (wanScenario === 'reference' && !(referencesIds.length || videoIds.length || audioIds.length))
      ))) {
      return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      void fetch('/mini-app/api/web-auth/web-generation/quote', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          model: modelId, prompt: prompt.trim(), aspect_ratio: ratio,
          duration, quality: quality || undefined, reference_ids: referencesIds,
          ...(videoIds.length ? { video_reference_ids: videoIds } : {}),
          ...(audioIds.length ? { audio_reference_ids: audioIds } : {}),
          ...(isWan3 ? {
            wan_scenario: wanScenario,
            ...(documentIds.length ? { file_reference_ids: documentIds } : {}),
            ...(linkIds.length ? { link_reference_ids: linkIds } : {}),
          } : {}),
          ...(isOmni ? {
            omni_audio_asset_ids: omniAudioAsset ? [omniAudioAsset] : [],
            omni_character_asset_ids: omniCharacterAssets,
            ...(omniSeed.trim() ? { omni_seed: Number(omniSeed) } : {}),
          } : {}),
          ...(model.supports_layers ? {
            max_images: maxImages,
            text_recognition: textRecognition,
            output_format: outputFormat,
          } : {}),
          ...(model.id === 'seedream_55' ? {
            output_format: outputFormat,
            background,
          } : {}),
          ...(model.supports_nsfw_checker ? { nsfw_checker: nsfwChecker } : {}),
        }),
      }).then(async response => {
        const result = await response.json() as { ok?: boolean; price?: string }
        if (!response.ok || !result.ok || !result.price) throw new Error('Cannot quote')
        if (!controller.signal.aborted) {
          setQuote({ price: result.price, key: quoteKey })
          setQuoteError('')
        }
      }).catch(() => {
        if (!controller.signal.aborted) setQuoteError('Не удалось рассчитать актуальную стоимость.')
      })
    }, 250)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
    // Exact serialized input key contains all required quote dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quoteKey, model?.enabled, model?.requires_reference])

  const checkTask = async (taskId: string) => {
    try {
      const response = await fetch('/mini-app/api/web-auth/task/' + encodeURIComponent(taskId), {
        credentials: 'same-origin', cache: 'no-store',
      })
      if (!response.ok) return
      const data = await response.json() as { ok?: boolean; task?: Task }
      if (!data.ok || !data.task) return
      setActiveTask(data.task)
      if (data.task.status !== 'pending') {
        onBalanceChanged()
        onTaskChanged()
      }
    } catch {
      // A network error never changes a server-side paid task state.
    }
  }

  useEffect(() => {
    if (!activeTask || activeTask.status !== 'pending') return
    const timer = window.setInterval(() => { void checkTask(activeTask.task_id) }, 8000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTask?.task_id, activeTask?.status])

  const createTask = async (event: React.FormEvent) => {
    event.preventDefault()
    if (busy || !model || !quoteReady || prompt.trim().length < 2) return
    setBusy(true)
    setError('')
    if (!idempotencyKey.current) idempotencyKey.current = crypto.randomUUID().replace(/-/g, '')
    try {
      const response = await fetch('/mini-app/api/web-auth/web-generation/create', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_key: idempotencyKey.current, model: modelId,
          prompt: prompt.trim(), aspect_ratio: ratio, duration,
          reference_ids: referencesIds, quality: quality || undefined,
          ...(videoIds.length ? { video_reference_ids: videoIds } : {}),
          ...(audioIds.length ? { audio_reference_ids: audioIds } : {}),
          ...(isWan3 ? {
            wan_scenario: wanScenario,
            ...(documentIds.length ? { file_reference_ids: documentIds } : {}),
            ...(linkIds.length ? { link_reference_ids: linkIds } : {}),
          } : {}),
          ...(isOmni ? {
            omni_audio_asset_ids: omniAudioAsset ? [omniAudioAsset] : [],
            omni_character_asset_ids: omniCharacterAssets,
            ...(omniSeed.trim() ? { omni_seed: Number(omniSeed) } : {}),
          } : {}),
          ...(model.supports_layers ? {
            max_images: maxImages,
            text_recognition: textRecognition,
            output_format: outputFormat,
          } : {}),
          ...(model.id === 'seedream_55' ? {
            output_format: outputFormat,
            background,
          } : {}),
          ...(model.supports_nsfw_checker ? { nsfw_checker: nsfwChecker } : {}),
          expected_price: quote!.price,
        }),
      })
      const data = await response.json() as {
        ok?: boolean; task_id?: string; status?: 'pending'; error?: string
      }
      if (!response.ok || !data.ok || !data.task_id) {
        throw new Error(data.error || 'Не удалось создать задачу.')
      }
      setActiveTask({
        task_id: data.task_id, type: model.type, model: model.id,
        status: 'pending', result_url: null, created_at_epoch: Math.floor(Date.now() / 1000),
      })
      idempotencyKey.current = ''
      onBalanceChanged()
      onTaskChanged()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Не удалось создать задачу.')
    } finally {
      setBusy(false)
    }
  }

  return <section className="space-y-4 border border-[#a48350]/40 p-5" aria-label="Веб-генерация">
    <h2 className="text-xl font-bold">Создать фото или видео</h2>
    <p className="text-sm text-[#bcb7af]">Цена берётся с сервера.
      Средства резервируются на время выполнения, при ошибке возвращаются.</p>
    <form className="space-y-3" onSubmit={event => void createTask(event)}>
      <label className="block text-sm text-[#d7c0a2]" htmlFor="web-model">Модель</label>
      <select id="web-model" value={modelId} disabled={busy || !models.length}
        onChange={event => {
          const next = models.find(item => item.id === event.target.value)
          setModelId(event.target.value)
          setRatio(next?.ratios.includes('1:1') ? '1:1' : next?.ratios[0] || '16:9')
          setDuration(next?.durations?.includes(5) ? 5 : next?.durations?.[0] || 5)
          setQuality(next?.qualities?.includes('2K') ? '2K' : next?.qualities?.[0] || '')
          setMaxImages(next?.layers_max_images?.default || 30)
          setTextRecognition(false)
          setOutputFormat(next?.layers_formats?.[0] || 'png')
          setBackground('auto')
          setNsfwChecker(false)
          setWanScenario('text')
          setOmniAudioAsset('')
          setOmniCharacterAssets([])
          setOmniSeed('')
          setReferences(previous => previous.slice(0, next?.max_references || 0))
          setVideoReferences(previous => previous.slice(0, next?.max_video_references || 0))
          setAudioReferences(previous => previous.slice(0, next?.max_audio_references || 0))
          setDocumentReferences([])
          setWebpageReference(null)
          setWebpageUrl('')
          setQuote(null)
          idempotencyKey.current = ''
        }} className="min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white">
        {models.map(item => <option key={item.id} value={item.id}
          disabled={item.enabled === false}>
          {item.label} ({item.type === 'image' ? 'фото' : 'видео'})
          {item.enabled === false ? ' — пока недоступно' : ''}
        </option>)}
      </select>
      <p className="text-xs text-[#adaba4]">Все модели общего каталога показаны.
        Веб-запуск доступен только там, где подтверждены контракт, цена и доставка.</p>
      {model?.qualities?.length ? <div>
        <label className="block text-sm text-[#d7c0a2]" htmlFor="web-quality">Качество</label>
        <select id="web-quality" value={quality} disabled={busy}
          onChange={event => {
            setQuality(event.target.value)
            idempotencyKey.current = ''
          }}
          className="mt-2 min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white">
          {model.qualities.map(item => <option key={item} value={item}>{item}</option>)}
        </select>
      </div> : null}
      {model?.supports_output_format && !model?.supports_layers ? <div className="space-y-2">
        <label className="block text-sm text-[#d7c0a2]" htmlFor="web-seedream-format">
          Формат результата Seedream
        </label>
        <select id="web-seedream-format" value={outputFormat} disabled={busy}
          onChange={event => {
            setOutputFormat(event.target.value)
            if (event.target.value === 'jpeg' && background === 'transparent') setBackground('auto')
            idempotencyKey.current = ''
          }}
          className="min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white">
          <option value="png">PNG</option>
          <option value="jpeg">JPEG</option>
        </select>
      </div> : null}
      {model?.supports_background ? <div className="space-y-2">
        <label className="block text-sm text-[#d7c0a2]" htmlFor="web-seedream-background">
          Фон Seedream
        </label>
        <select id="web-seedream-background" value={background} disabled={busy}
          onChange={event => {
            setBackground(event.target.value)
            if (event.target.value === 'transparent') setOutputFormat('png')
            idempotencyKey.current = ''
          }}
          className="min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white">
          <option value="auto">Авто</option>
          <option value="opaque">Непрозрачный</option>
          <option value="transparent">Прозрачный (PNG)</option>
        </select>
      </div> : null}
      {model?.supports_nsfw_checker ? <label className="flex min-h-11 items-center gap-3 text-sm text-[#d7c0a2]">
        <input type="checkbox" checked={nsfwChecker} disabled={busy}
          onChange={event => { setNsfwChecker(event.target.checked); idempotencyKey.current = '' }} />
        Проверять NSFW
      </label> : null}
      {isOmni ? <fieldset className="space-y-3 border border-[#a48350]/40 p-3">
        <legend className="px-1 text-sm font-semibold text-[#f0c779]">
          Gemini Omni — видео, голоса и персонажи
        </legend>
        <label className="block text-sm text-[#d7c0a2]">
          Audio ID (необязательно)
          <select value={omniAudioAsset} disabled={busy}
            onChange={event => { setOmniAudioAsset(event.target.value); idempotencyKey.current = '' }}
            className="mt-1 min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white">
            <option value="">Без своего Audio ID</option>
            {omniAssets.filter(asset => asset.kind === 'audio').map(asset =>
              <option key={asset.asset_id} value={asset.asset_id}>{asset.name}</option>)}
          </select>
        </label>
        <div className="space-y-1 text-sm text-[#d7c0a2]">
          Character ID (до 3, необязательно)
          {omniAssets.filter(asset => asset.kind === 'character').map(asset =>
            <label key={asset.asset_id} className="flex min-h-10 items-center gap-2 text-sm">
              <input type="checkbox" disabled={busy || (
                omniCharacterAssets.length >= 3 && !omniCharacterAssets.includes(asset.asset_id)
              )} checked={omniCharacterAssets.includes(asset.asset_id)}
                onChange={event => {
                  setOmniCharacterAssets(previous => event.target.checked
                    ? [...previous, asset.asset_id] : previous.filter(id => id !== asset.asset_id))
                  idempotencyKey.current = ''
                }} />
              {asset.name}
            </label>)}
        </div>
        <label className="block text-sm text-[#d7c0a2]">
          Seed (необязательно)
          <input type="number" min={0} max={2147483647} step={1} value={omniSeed}
            disabled={busy} onChange={event => {
              setOmniSeed(event.target.value)
              idempotencyKey.current = ''
            }}
            className="mt-1 min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white" />
        </label>
        <p className="text-xs text-[#b4aea1]">
          Для использования своего голоса или персонажа сначала создайте и оплатите
          ID в разделе выше. Для Gemini Omni доступен один входной видеореференс.
        </p>
      </fieldset> : null}
      {isWan3 && model?.supported_modes ? <div className="space-y-2">
        <label className="block text-sm text-[#d7c0a2]" htmlFor="web-wan-scenario">
          Сценарий Wan 3.0
        </label>
        <select id="web-wan-scenario" value={wanScenario} disabled={busy}
          onChange={event => {
            setWanScenario(event.target.value)
            setReferences([])
            setVideoReferences([])
            setAudioReferences([])
            setDocumentReferences([])
            setWebpageReference(null)
            idempotencyKey.current = ''
          }}
          className="min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white">
          {model.supported_modes.map(item => <option key={item} value={item}>{
            item === 'text' ? 'Текст → видео'
              : item === 'first_frame' ? 'Первый кадр → видео (1 фото)'
                : item === 'first_last' ? 'Первый и последний кадр (2 фото)'
                  : item === 'edit' ? 'Редактирование исходного видео'
                    : item === 'file' ? 'Документ → видео'
                      : item === 'link' ? 'Веб-страница → видео'
                        : 'Фото, видео и аудио → видео'
          }</option>)}
        </select>
        <p className="text-xs text-[#adaba4]">
          Длительность входного видео измеряется на сервере. При выборе
          «Авто» резервируются средства за максимум 30 секунд, после
          обработки остаток возвращается по фактической длительности.
          Файлы и публичные страницы проверяются на сервере до списания.
        </p>
      </div> : null}
      {isWan3 && wanScenario === 'file' ? <div className="space-y-2">
        <label htmlFor="web-wan-document" className="block text-sm text-[#d7c0a2]">
          Документ-референс (PDF, TXT, DOCX, XLSX, PPTX)
        </label>
        <input id="web-wan-document" type="file"
          accept=".pdf,.txt,.md,.doc,.xls,.ppt,.docx,.xlsx,.pptx,.pages,.numbers,.key"
          disabled={busy || uploading || documentReferences.length >= 1}
          onChange={event => {
            const file = event.target.files?.[0]
            if (file) void uploadReference(file, 'file')
            event.target.value = ''
          }} className="block max-w-full text-xs text-[#d9c7ae]" />
        {documentReferences.map(item => <div key={item.id} className="flex items-center gap-2 text-sm">
          <span className="min-w-0 flex-1 truncate">{item.name}</span>
          <button type="button" className="text-[#f1c77a] underline"
            onClick={() => { setDocumentReferences([]); idempotencyKey.current = '' }}>
            Убрать
          </button>
        </div>)}
      </div> : null}
      {isWan3 && wanScenario === 'link' ? <div className="space-y-2">
        <label htmlFor="web-wan-link" className="block text-sm text-[#d7c0a2]">
          Ссылка на публичную HTTPS-страницу
        </label>
        <input id="web-wan-link" type="url" value={webpageUrl}
          placeholder="https://example.org/article" disabled={busy || uploading}
          onChange={event => {
            setWebpageUrl(event.target.value)
            setWebpageReference(null)
            idempotencyKey.current = ''
          }}
          className="min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white" />
        <button type="button" disabled={busy || uploading || !webpageUrl.trim()}
          onClick={() => void importWebpage()}
          className="min-h-10 border border-[#b89454] px-3 text-sm text-[#f1c77a] disabled:opacity-50">
          Проверить и привязать страницу
        </button>
        {webpageReference ? <p className="text-xs text-[#d7c0a2]">
          Привязана: {webpageReference.name}
        </p> : null}
      </div> : null}
      {model?.supports_layers ? <fieldset className="space-y-3 border border-[#a48350]/40 p-3">
        <legend className="px-1 text-sm font-semibold text-[#f0c779]">Разделение на слои</legend>
        <label className="block space-y-2 text-sm text-[#d7c0a2]">
          Максимум изображений (включая основу)
          <input type="number" min={model.layers_max_images?.min || 2}
            max={model.layers_max_images?.max || 100}
            step={1} value={maxImages} disabled={busy}
            onChange={event => {
              const value = Number(event.target.value)
              setMaxImages(Number.isInteger(value) ? value : 30)
              idempotencyKey.current = ''
            }}
            className="mt-2 min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white" />
        </label>
        <label className="block space-y-2 text-sm text-[#d7c0a2]">
          Формат слоёв
          <select value={outputFormat} disabled={busy}
            onChange={event => { setOutputFormat(event.target.value); idempotencyKey.current = '' }}
            className="mt-2 min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white">
            {(model.layers_formats || ['png']).map(item => <option key={item} value={item}>{item.toUpperCase()}</option>)}
          </select>
        </label>
        <label className="flex min-h-11 items-center gap-3 text-sm text-[#d7c0a2]">
          <input type="checkbox" checked={textRecognition} disabled={busy}
            onChange={event => { setTextRecognition(event.target.checked); idempotencyKey.current = '' }} />
          Распознавать текст на слоях
        </label>
        <p className="text-xs text-[#b4aea1]">
          Резервируем максимум, после получения готовых слоёв возвращаем стоимость неиспользованных изображений.
        </p>
      </fieldset> : null}
      {model?.supported_modes?.length && model.supported_modes.length < 3
        ? <p className="text-xs text-[#adaba4]">В этой веб-версии доступны режимы: {
          model.supported_modes.map(mode => mode === 'video_text' ? 'Текст → видео'
            : mode === 'video_images' ? 'Фото → видео' : mode).join(', ')
        }. Остальные режимы пока не включены.</p> : null}
      <label className="block text-sm text-[#d7c0a2]" htmlFor="web-prompt">Описание</label>
      <textarea id="web-prompt" value={prompt} maxLength={model?.supports_layers ? 2000 : 2500} rows={4}
        onChange={event => { setPrompt(event.target.value); idempotencyKey.current = '' }}
        disabled={busy} required className="w-full border border-[#a48350] bg-[#151b1b] p-3 text-white"
        placeholder="Опишите изображение или видео…" />
      <div className="space-y-2">
        <label htmlFor="web-generation-reference" className="block text-sm text-[#d7c0a2]">
          Референсы (до {model?.max_references || 0} изображений)
        </label>
        <input id="web-generation-reference" type="file"
          accept="image/png,image/jpeg,image/webp"
          disabled={busy || uploading || references.length >= (model?.max_references || 0)}
          onChange={event => {
            const file = event.target.files?.[0]
            if (file) void uploadReference(file, 'image')
            event.target.value = ''
          }} className="block max-w-full text-xs text-[#d9c7ae]" />
        {uploading ? <p role="status" className="text-sm text-[#d9c7ae]">Сохраняем референс в S3…</p> : null}
        {references.length > 0 ? <ul className="space-y-1">
          {references.map(item => <li key={item.id}
            className="flex flex-wrap items-center justify-between gap-2 text-sm text-[#d9c7ae]">
            <span className="min-w-0 truncate">{item.name}</span>
            <button type="button" disabled={busy || uploading}
              className="min-h-9 border border-[#a48350]/60 px-2 text-[#f1c77a]"
              onClick={() => {
                setReferences(previous => previous.filter(ref => ref.id !== item.id))
                idempotencyKey.current = ''
              }}>Убрать</button>
          </li>)}
        </ul> : null}
      </div>
      {model?.max_video_references ? <div className="space-y-2">
        <label htmlFor="web-generation-video-ref" className="block text-sm text-[#d7c0a2]">
          Видео-референс (до {model.max_video_references})
        </label>
        <input id="web-generation-video-ref" type="file"
          accept="video/mp4,video/webm" disabled={
            busy || uploading || videoReferences.length >= model.max_video_references
          } onChange={event => {
            const file = event.target.files?.[0]
            if (file) void uploadReference(file, 'video')
            event.target.value = ''
          }} className="block max-w-full text-xs text-[#d9c7ae]" />
        {videoReferences.map(item => <div key={item.id} className="flex items-center gap-2 text-sm">
          <span className="min-w-0 flex-1 truncate">{item.name}</span>
          <button type="button" className="text-[#f1c77a] underline"
            onClick={() => { setVideoReferences(previous => previous.filter(x => x.id !== item.id)); idempotencyKey.current = '' }}>
            Убрать
          </button>
        </div>)}
      </div> : null}
      {model?.max_audio_references ? <div className="space-y-2">
        <label htmlFor="web-generation-audio-ref" className="block text-sm text-[#d7c0a2]">
          Аудио-референс (до {model.max_audio_references})
        </label>
        <input id="web-generation-audio-ref" type="file"
          accept="audio/mpeg,audio/wav,audio/ogg" disabled={
            busy || uploading || audioReferences.length >= model.max_audio_references
          } onChange={event => {
            const file = event.target.files?.[0]
            if (file) void uploadReference(file, 'audio')
            event.target.value = ''
          }} className="block max-w-full text-xs text-[#d9c7ae]" />
        {audioReferences.map(item => <div key={item.id} className="flex items-center gap-2 text-sm">
          <span className="min-w-0 flex-1 truncate">{item.name}</span>
          <button type="button" className="text-[#f1c77a] underline"
            onClick={() => { setAudioReferences(previous => previous.filter(x => x.id !== item.id)); idempotencyKey.current = '' }}>
            Убрать
          </button>
        </div>)}
      </div> : null}
      <div className="flex flex-wrap gap-3">
        <label className="flex-1 space-y-2 text-sm text-[#d7c0a2]">
          Формат
          <select value={ratio} disabled={busy}
            onChange={event => { setRatio(event.target.value); idempotencyKey.current = '' }}
            className="mt-2 min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white">
            {(model?.ratios || []).map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        {model?.type === 'video' ? <label className="flex-1 space-y-2 text-sm text-[#d7c0a2]">
          Длительность
          <select value={duration} disabled={busy}
            onChange={event => { setDuration(Number(event.target.value)); idempotencyKey.current = '' }}
            className="mt-2 min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white">
            {(model.durations || [5]).map(item => <option key={item} value={item}>{
              item === -1 ? 'Авто (макс. резерв 30 сек.)' : item + ' сек.'
            }</option>)}
          </select>
        </label> : null}
      </div>
      {quoteError ? <p role="alert" className="text-sm text-red-300">{quoteError}</p> : null}
      <button type="submit" disabled={
        busy || uploading || !model || !quoteReady || prompt.trim().length < 2
      } className="min-h-11 w-full border border-[#b89454] bg-[#d5ab63] p-2 font-bold text-[#17120d] disabled:opacity-50">
        {busy ? 'Создаём задачу…'
          : quoteReady ? 'Создать за ' + price + ' кредитов'
            : 'Ожидаем расчёта цены'}
      </button>
    </form>
    {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
    {activeTask ? <div className="space-y-2 border border-[#a48350]/40 p-3">
      <p role="status" className="text-sm">Задача: {
        activeTask.status === 'pending' ? 'генерируется' :
        activeTask.status === 'completed' ? 'готова' : 'ошибка, резерв возвращён'
      }</p>
      {activeTask.result_seconds ? <p className="text-sm text-[#d9c7ae]">
        Длительность результата: {activeTask.result_seconds} сек.
        {activeTask.cost ? ' Списано: ' + activeTask.cost + ' кредитов.' : ''}
      </p> : null}
      {activeTask.output_count ? <p className="text-sm text-[#d9c7ae]">
        Сохранено слоёв и изображений: {activeTask.output_count}.
        {activeTask.cost ? ' Итоговое списание: ' + activeTask.cost + ' кредитов.' : ''}
      </p> : null}
      {activeTask.result_url ? <a href={activeTask.result_url}
        target="_blank" rel="noopener noreferrer"
        className="text-sm text-[#f3cf92] underline">Открыть готовый результат</a> : null}
      {activeTask.bundle_url ? <a href={activeTask.bundle_url}
        target="_blank" rel="noopener noreferrer"
        className="ml-2 text-sm text-[#f3cf92] underline">Скачать все слои ZIP</a> : null}
      <button type="button" onClick={() => void checkTask(activeTask.task_id)}
        className="ml-2 min-h-11 border border-[#8c7658] px-4 text-sm text-white">
        Проверить статус
      </button>
    </div> : null}
  </section>
}
