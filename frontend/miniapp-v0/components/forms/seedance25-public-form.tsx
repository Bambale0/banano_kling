'use client'

import { normalizeRepeatPrompt } from '@/lib/repeat-prompt'

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { getInitData, uploadFile } from '@/lib/api'
import { clearPendingSeedance, readPendingSeedance, seedancePendingKey, type PendingSeedanceLaunch } from '@/lib/seedance-pending'
import {
  generateSeedance25,
  seedance25QuoteStatus,
  SeedanceApiError,
  quoteSeedance25Identity,
  type Seedance25GeneratePayload,
  type Seedance25QuoteResponse,
  SEEDANCE25_MAX_PROMPT_LENGTH,
  SEEDANCE25_IDENTITY_MAX_PROMPT_LENGTH,
  uploadSeedance25Video,
  type Seedance25GenerateResponse,
  type Seedance25OutputFormat,
  type Seedance25Resolution,
  type Seedance25Scenario,
} from '@/lib/seedance25-api'
import type { UploadedFile, VideoModel, VideoPromptPreset } from '@/lib/types'

const RATIOS = ['adaptive', '16:9', '9:16', '1:1', '4:3', '3:4', '21:9'] as const
const IMAGE_EXTS = new Set(['jpg', 'jpeg', 'png', 'webp', 'bmp', 'tiff', 'tif', 'gif'])
const VIDEO_EXTS = new Set(['mp4', 'mov'])
const AUDIO_EXTS = new Set(['wav', 'mp3'])

type PublicScenario = Seedance25Scenario | 'identity_transfer'

const SCENARIOS: Array<{
  id: PublicScenario
  icon: string
  title: string
  description: string
}> = [
  {
    id: 'text',
    icon: '✨',
    title: 'Видео по описанию',
    description: 'Создать ролик с нуля только по тексту',
  },
  {
    id: 'first_frame',
    icon: '🖼',
    title: 'Оживить фото',
    description: 'Фото станет первым кадром будущего видео',
  },
  {
    id: 'first_last',
    icon: '🎞',
    title: 'Между двумя кадрами',
    description: 'Задать, с чего видео начинается и чем заканчивается',
  },
  {
    id: 'multimodal',
    icon: '🧩',
    title: 'По референсам',
    description: 'Использовать фото, видео и аудио как ориентиры',
  },
  {
    id: 'identity_transfer',
    icon: '👤',
    title: 'Замена персонажа',
    description: 'Внешность с ваших фото, движения и сцена из видео',
  },
]

interface Props {
  model?: VideoModel
  credits: number
  isAdmin: boolean
  promptPreset?: VideoPromptPreset | null
  onPromptPresetConsumed?: () => void
  onQueued?: (result: Seedance25GenerateResponse) => void | Promise<void>
  onSavedReference?: (file: UploadedFile) => void
}

interface RefItem {
  file: UploadedFile
  duration?: number
}

function ext(name: string) {
  return String(name || '').split('.').pop()?.toLowerCase() || ''
}

function splitSources(raw: string, limit: number) {
  const values = raw
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
  const unique = [...new Set(values)]
  if (unique.length > limit) throw new Error(`Максимум ${limit} ссылок/Asset ID`)
  for (const value of unique) {
    if (!value.startsWith('asset://') && !/^https?:\/\//i.test(value)) {
      throw new Error(`Некорректный URL/Asset ID: ${value}`)
    }
  }
  return unique
}

function fileDuration(file: File, kind: 'video' | 'audio'): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const media = document.createElement(kind)
    media.preload = 'metadata'
    media.onloadedmetadata = () => {
      const duration = Number(media.duration || 0)
      URL.revokeObjectURL(url)
      resolve(duration || null)
    }
    media.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(null)
    }
    media.src = url
  })
}

function Option({ active, children, onClick }: { active?: boolean; children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={Boolean(active)}
      onClick={onClick}
      className={`rounded-xl border px-3 py-2.5 text-xs font-medium transition ${
        active
          ? 'border-cyan/60 bg-cyan/15 text-cyan shadow-[0_0_0_1px_rgba(34,211,238,0.08)]'
          : 'border-border/50 bg-secondary/35 text-muted-foreground hover:border-border hover:text-foreground'
      }`}
    >
      {children}
    </button>
  )
}

function ScenarioCard({
  active,
  icon,
  title,
  description,
  onClick,
}: {
  active: boolean
  icon: string
  title: string
  description: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`min-h-[88px] rounded-2xl border p-3 text-left transition ${
        active
          ? 'border-cyan/60 bg-cyan/10 shadow-[0_0_0_1px_rgba(34,211,238,0.08)]'
          : 'border-border/45 bg-secondary/25 hover:border-border/80 hover:bg-secondary/40'
      }`}
    >
      <div className="flex items-start gap-2.5">
        <span className="text-lg leading-none">{icon}</span>
        <div className="min-w-0">
          <div className={`text-sm font-semibold ${active ? 'text-cyan' : 'text-foreground'}`}>{title}</div>
          <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{description}</div>
        </div>
      </div>
    </button>
  )
}

function Toggle({
  value,
  label,
  hint,
  onChange,
}: {
  value: boolean
  label: string
  hint: string
  onChange: (value: boolean) => void
}) {
  return (
    <button
      type="button"
      aria-pressed={value}
      onClick={() => onChange(!value)}
      className={`flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-3 text-left transition ${
        value ? 'border-cyan/45 bg-cyan/8' : 'border-border/45 bg-secondary/20'
      }`}
    >
      <span className="min-w-0">
        <span className="block text-sm font-medium text-foreground">{label}</span>
        <span className="mt-0.5 block text-[11px] leading-relaxed text-muted-foreground">{hint}</span>
      </span>
      <span
        className={`relative h-6 w-11 shrink-0 rounded-full transition ${value ? 'bg-cyan/70' : 'bg-secondary'}`}
        aria-hidden="true"
      >
        <span
          className={`absolute top-1 h-4 w-4 rounded-full bg-foreground transition ${value ? 'left-6' : 'left-1'}`}
        />
      </span>
    </button>
  )
}

function FileRow({ item, role, onRemove }: { item: RefItem; role?: string; onRemove: () => void }) {
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-xl border border-border/40 bg-background/45 px-3 py-2 text-xs">
      <span className="min-w-0 flex-1 text-foreground">{role ? <span className="mb-0.5 block text-[10px] text-cyan">{role}</span> : null}<span className="block truncate">{item.file.name}</span></span>
      {item.duration ? <span className="shrink-0 text-muted-foreground">{item.duration.toFixed(1)}с</span> : null}
      <button type="button" onClick={onRemove} className="shrink-0 px-1 text-destructive" aria-label="Удалить файл">×</button>
    </div>
  )
}

function UploadButton({
  label,
  accept,
  multiple = false,
  disabled,
  onFiles,
}: {
  label: string
  accept: string
  multiple?: boolean
  disabled?: boolean
  onFiles: (files: File[]) => void
}) {
  return (
    <label
      className={`flex cursor-pointer items-center justify-center rounded-xl border border-dashed border-cyan/35 bg-cyan/5 px-3 py-3 text-xs font-medium text-cyan transition hover:bg-cyan/10 ${
        disabled ? 'pointer-events-none opacity-50' : ''
      }`}
    >
      {label}
      <input
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        className="sr-only"
        onChange={(event) => {
          const files = Array.from(event.target.files || [])
          if (files.length) onFiles(files)
          event.currentTarget.value = ''
        }}
      />
    </label>
  )
}

function SectionTitle({ eyebrow, title, hint }: { eyebrow?: string; title: string; hint?: string }) {
  return (
    <div>
      {eyebrow ? <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan/80">{eyebrow}</div> : null}
      <h4 className="text-sm font-semibold text-foreground">{title}</h4>
      {hint ? <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

export function Seedance25PublicForm({ model, credits, isAdmin, promptPreset, onPromptPresetConsumed, onQueued, onSavedReference }: Props) {
  const [scenario, setScenario] = useState<PublicScenario>('multimodal')
  const identityTransfer = scenario === 'identity_transfer'
  const referenceScenario = scenario === 'multimodal' || identityTransfer
  const [resolution, setResolution] = useState<Seedance25Resolution>('720p')
  const [ratio, setRatio] = useState<(typeof RATIOS)[number]>('adaptive')
  const [duration, setDuration] = useState(5)
  const [videoEditing, setVideoEditing] = useState(false)
  const sourceSettings = identityTransfer || videoEditing
  const [outputFormat, setOutputFormat] = useState<Seedance25OutputFormat>('mp4')
  const [generateAudio, setGenerateAudio] = useState(true)
  const [returnLastFrame, setReturnLastFrame] = useState(false)
  const [webSearch, setWebSearch] = useState(false)
  const [nsfwChecker, setNsfwChecker] = useState(false)
  const [prompt, setPrompt] = useState('')
  const promptLength = Array.from(prompt.trim()).length
  const promptLimit = identityTransfer ? SEEDANCE25_IDENTITY_MAX_PROMPT_LENGTH : SEEDANCE25_MAX_PROMPT_LENGTH

  const [firstFrame, setFirstFrame] = useState<RefItem | null>(null)
  const [lastFrame, setLastFrame] = useState<RefItem | null>(null)
  const [images, setImages] = useState<RefItem[]>([])
  const [videos, setVideos] = useState<RefItem[]>([])
  const [audios, setAudios] = useState<RefItem[]>([])

  const [firstSource, setFirstSource] = useState('')
  const [lastSource, setLastSource] = useState('')
  const [imageSources, setImageSources] = useState('')
  const [videoSources, setVideoSources] = useState('')
  const [audioSources, setAudioSources] = useState('')

  const [uploading, setUploading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [queued, setQueued] = useState<Seedance25GenerateResponse | null>(null)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const pendingKey = typeof getInitData === 'function' ? seedancePendingKey(getInitData()) : null
  const [pendingLaunch, setPendingLaunch] = useState<PendingSeedanceLaunch | null>(null)
  useEffect(() => {
    if (pendingKey) setPendingLaunch(readPendingSeedance(localStorage, pendingKey))
  }, [pendingKey])
  const finishPending = (quoteId: string) => {
    if (!mounted.current) return
    if (pendingKey && clearPendingSeedance(localStorage, pendingKey, quoteId)) {
      setPendingLaunch((current) => current?.quoteId === quoteId ? null : current)
    }
  }
  useEffect(() => {
    if (!pendingLaunch || submitting) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const recover = async () => {
      try {
        let result = await seedance25QuoteStatus(pendingLaunch.quoteId)
        if (result.status === 'quoted') result = await generateSeedance25(pendingLaunch.payload)
        if (cancelled) return
        if ('task_id' in result) {
          finishPending(pendingLaunch.quoteId)
          setQueued(result as Seedance25GenerateResponse)
          await onQueued?.(result as Seedance25GenerateResponse)
          return
        }
        if (['rejected', 'provider_failed'].includes(result.status)) {
          finishPending(pendingLaunch.quoteId)
          setError('Провайдер отклонил задачу. Для нового запуска проверьте новый расчёт.')
          return
        }
      } catch (value) {
        if (cancelled) return
        if (value instanceof SeedanceApiError && ['video_quote_changed', 'video_quote_missing', 'video_rejected', 'video_not_reserved', 'video_input_invalid'].includes(value.code || '')) {
          finishPending(pendingLaunch.quoteId)
          setError(value.message)
          return
        }
      }
      if (!cancelled) timer = setTimeout(() => void recover(), 3000)
    }
    void recover()
    return () => { cancelled = true; if (timer) clearTimeout(timer) }
  // Recovery owns the original immutable launch; form edits do not replace it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingLaunch, submitting, pendingKey])


  const [sourceFeedGenId, setSourceFeedGenId] = useState<number | null>(null)
  useEffect(() => {
    if (!promptPreset?.seedance25IdentityTransfer) return
    setScenario('identity_transfer')
    setVideoEditing(false)
    setPrompt(normalizeRepeatPrompt(promptPreset).prompt || '')
    setResolution(promptPreset.seedance25Resolution || '720p')
    setImages([...(promptPreset.initialStartImage || []), ...(promptPreset.initialPhotoReferences || [])].map((file) => ({ file })))
    setVideos((promptPreset.initialVideoReferences || []).map((file) => ({ file })))
    setImageSources('')
    setVideoSources('')
    setSourceFeedGenId(promptPreset.sourceFeedGenId || null)
    setError(null)
    onPromptPresetConsumed?.()
  }, [promptPreset, onPromptPresetConsumed])

  const [quoteState, setQuoteState] = useState<{ key: string; quote?: Seedance25QuoteResponse; error?: string } | null>(null)
  const [quoteAttempt, setQuoteAttempt] = useState(0)
  const identityRefs = useMemo(() => {
    try {
      const photos = [...new Set([...images.map((item) => item.file.url), ...splitSources(imageSources, 30)])]
      const sources = [...new Set([...videos.map((item) => item.file.url), ...splitSources(videoSources, 10)])]
      let issue = ''
      if (!photos.length) issue = 'Добавьте 1–3 фото одного человека'
      else if (photos.length > 3) issue = 'Для замены персонажа оставьте не больше 3 фото одного человека. Все фото сохранены.'
      else if (sources.length !== 1) issue = 'Добавьте ровно одно исходное видео'
      else if (videos.some((item) => item.duration != null && (item.duration < 4 || item.duration > 30))) issue = 'Исходное видео должно длиться 4–30 секунд'
      return { photos, sources, issue }
    } catch (value) {
      return { photos: [], sources: [], issue: value instanceof Error ? value.message : 'Проверьте ссылки на референсы' }
    }
  }, [images, videos, imageSources, videoSources])
  const hasVideoReference = referenceScenario && (videos.length > 0 || videoSources.trim().length > 0)
  const needsMeasuredQuote = hasVideoReference && (duration > 0 || sourceSettings)
  const quotePayload = useMemo<Seedance25GeneratePayload>(() => ({
    scenario: 'multimodal', identityTransfer, videoEditing: !identityTransfer && videoEditing,
    sourceFeedGenId: identityTransfer ? sourceFeedGenId : null,
    prompt: prompt.trim(), ratio: sourceSettings ? 'adaptive' : ratio,
    duration: sourceSettings ? -1 : duration, resolution, outputFormat,
    generateAudio, returnLastFrame, webSearch, nsfwChecker,
    firstFrameUrl: null, lastFrameUrl: null,
    referenceAudios: identityTransfer ? [] : [...new Set([...audios.map((item) => item.file.url), ...audioSources.split(/\r?\n/).map((x) => x.trim()).filter(Boolean)])],
    referenceImages: identityRefs.photos, referenceVideos: identityRefs.sources,
  }), [identityRefs, identityTransfer, videoEditing, sourceFeedGenId, prompt, sourceSettings, ratio,
    duration, resolution, outputFormat, generateAudio, returnLastFrame, webSearch, nsfwChecker, audios, audioSources])
  const quoteKey = JSON.stringify(quotePayload)
  const measuredQuote = needsMeasuredQuote && quoteState?.key === quoteKey ? quoteState.quote : undefined
  const identityQuote = identityTransfer ? measuredQuote : undefined
  const quoteError = needsMeasuredQuote && quoteState?.key === quoteKey ? quoteState.error : undefined
  useEffect(() => {
    if (!needsMeasuredQuote || (identityTransfer && identityRefs.issue)) return
    let cancelled = false
    setQuoteState(null)
    const timer = window.setTimeout(() => { void quoteSeedance25Identity(quotePayload).then((quote) => {
      if (!cancelled) setQuoteState({ key: quoteKey, quote })
    }).catch((value) => {
      if (!cancelled) setQuoteState({ key: quoteKey, error: value instanceof Error ? value.message : 'Не удалось рассчитать стоимость' })
    })
    }, 250)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [needsMeasuredQuote, identityTransfer, identityRefs.issue, quotePayload, quoteKey, quoteAttempt])

  const knownVideoSeconds = useMemo(
    () => videos.reduce((sum, item) => sum + (item.duration || 0), 0),
    [videos],
  )
  const basePrice = useMemo(() => {
    const seconds = videoEditing || duration === -1 ? 5 : duration
    const quotedCost = model?.quality_duration_costs?.[resolution]?.[seconds.toString()]
    if (typeof quotedCost === 'number' && Number.isFinite(quotedCost)) return quotedCost
    const perSecond = Number(model?.quality_costs?.[resolution] || 0)
    return perSecond ? Math.round(perSecond * seconds * 2) / 2 : 0
  }, [duration, videoEditing, model?.quality_costs, model?.quality_duration_costs, resolution])
  const price = needsMeasuredQuote ? measuredQuote?.cost ?? 0 : hasVideoReference ? basePrice * 2 : basePrice
  const canAfford = isAdmin || !price || credits >= price
  const promptStep = scenario === 'text' ? 2 : 3
  const settingsStep = promptStep + 1
  const promptPlaceholder = identityTransfer
    ? 'Необязательно: уточните детали результата. Внешность берём с фото, движения, камеру и сцену — из исходного видео.'
    : scenario === 'text'
    ? 'Например: девушка идёт по ночному Токио, лёгкий дождь, камера плавно следует сзади, мягкий неон...'
    : 'Опишите, что должно происходить в ролике: действия, движение камеры, настроение, свет и важные детали...'

  const runUpload = async (fn: () => Promise<void>) => {
    setUploading(true)
    setError(null)
    try {
      await fn()
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Не удалось загрузить файл')
    } finally {
      setUploading(false)
    }
  }

  const uploadImage = async (file: File, target: 'first' | 'last' | 'refs') => {
    if (!IMAGE_EXTS.has(ext(file.name))) throw new Error('Поддерживаются JPEG, PNG, WEBP, BMP, TIFF и GIF')
    if (file.size > 30 * 1024 * 1024) throw new Error('Фото должно быть не больше 30 MB')
    const uploaded = await uploadFile('seedance25_image_reference' as any, file)
    onSavedReference?.(uploaded)
    const item = { file: uploaded }
    if (target === 'first') setFirstFrame(item)
    else if (target === 'last') setLastFrame(item)
    else setImages((current) => [...current, item].slice(0, 30))
  }

  const uploadVideo = async (file: File) => {
    if (!VIDEO_EXTS.has(ext(file.name))) throw new Error('Видео должно быть MP4 или MOV')
    if (file.size > 200 * 1024 * 1024) throw new Error('Видео должно быть не больше 200 MB')
    if (identityTransfer && videos.length + splitSources(videoSources, 10).length >= 1) throw new Error('Для замены персонажа нужно ровно одно исходное видео')
    if (videos.length >= 10) throw new Error('Можно добавить максимум 10 видео-референсов')
    const seconds = await fileDuration(file, 'video')
    if (identityTransfer && seconds && (seconds < 4 || seconds > 30)) throw new Error('Исходное видео должно длиться 4–30 секунд')
    if (seconds && (seconds < 2 || seconds > 30)) throw new Error('Одно видео должно длиться от 2 до 30 секунд')
    if (seconds && knownVideoSeconds + seconds > 30.01) throw new Error('Суммарная длительность видео-референсов — максимум 30 секунд')
    const uploaded = await uploadSeedance25Video(file)
    onSavedReference?.(uploaded)
    setVideos((current) => [...current, { file: uploaded, duration: seconds || undefined }].slice(0, 10))
  }

  const uploadAudio = async (file: File) => {
    if (!AUDIO_EXTS.has(ext(file.name))) throw new Error('Аудио должно быть WAV или MP3')
    if (file.size > 15 * 1024 * 1024) throw new Error('Аудио должно быть не больше 15 MB')
    if (audios.length >= 10) throw new Error('Можно добавить максимум 10 аудио-референсов')
    const seconds = await fileDuration(file, 'audio')
    if (seconds && (seconds < 2 || seconds > 30)) throw new Error('Аудио должно длиться от 2 до 30 секунд')
    const uploaded = await uploadFile('seedance25_audio_reference' as any, file)
    onSavedReference?.(uploaded)
    setAudios((current) => [...current, { file: uploaded, duration: seconds || undefined }].slice(0, 10))
  }

  const chooseScenario = (next: PublicScenario) => {
    setVideoEditing(false)
    setScenario(next)
    if (next !== 'identity_transfer') setSourceFeedGenId(null)
    setError(null)
    // Identity and ordinary references share the same ordered inputs. Hidden
    // frame/audio inputs remain available on return and are never submitted here.
    if (next === 'identity_transfer' || scenario === 'identity_transfer') return
    if (next === 'text') {
      setFirstFrame(null)
      setLastFrame(null)
      setImages([])
      setVideos([])
      setAudios([])
      setFirstSource('')
      setLastSource('')
      setImageSources('')
      setVideoSources('')
      setAudioSources('')
    } else if (next === 'first_frame') {
      setLastFrame(null)
      setImages([])
      setVideos([])
      setAudios([])
      setLastSource('')
      setImageSources('')
      setVideoSources('')
      setAudioSources('')
    } else if (next === 'first_last') {
      setImages([])
      setVideos([])
      setAudios([])
      setImageSources('')
      setVideoSources('')
      setAudioSources('')
    } else {
      setFirstFrame(null)
      setLastFrame(null)
      setFirstSource('')
      setLastSource('')
    }
  }

  const submit = async () => {
    setError(null)
    setQueued(null)
    try {
      if (promptLength > promptLimit) throw new Error(`Промпт — максимум ${promptLimit} символов`)
      if (!identityTransfer && duration === -1 && !isAdmin) throw new Error('Автоматическая длительность доступна только администратору')

      const first = firstSource.trim() || firstFrame?.file.url || null
      const last = lastSource.trim() || lastFrame?.file.url || null
      const refImages = [...images.map((item) => item.file.url), ...splitSources(imageSources, 30)]
      const refVideos = [...videos.map((item) => item.file.url), ...splitSources(videoSources, 10)]
      const refAudios = identityTransfer ? [] : [...audios.map((item) => item.file.url), ...splitSources(audioSources, 10)]

      if (scenario === 'text' && !prompt.trim()) throw new Error('Опишите, какое видео нужно создать')
      if (scenario === 'first_frame' && !first) throw new Error('Добавьте фото для первого кадра')
      if (scenario === 'first_last' && (!first || !last)) throw new Error('Добавьте первый и последний кадры')
      if (scenario === 'multimodal' && !refImages.length && !refVideos.length && !refAudios.length) {
        throw new Error('Добавьте хотя бы один референс')
      }
      if (identityTransfer) {
        if (identityRefs.issue) throw new Error(identityRefs.issue)
        if (!identityQuote) throw new Error(quoteError || 'Дождитесь расчёта стоимости по исходному видео')
      }
      if (videoEditing) {
        if (scenario !== 'multimodal' || new Set(refVideos).size !== 1) throw new Error('Для редактирования добавьте ровно одно исходное видео')
        if (videos.some((item) => item.duration != null && (item.duration < 4 || item.duration > 30))) throw new Error('Исходное видео для редактирования должно длиться 4–30 секунд')
      }
      if (needsMeasuredQuote && !measuredQuote?.quote_hash) throw new Error(quoteError || 'Дождитесь точного расчёта по видео')
      if (!canAfford) throw new Error(`Недостаточно бананов. Нужно ${price}🍌`)

      setSubmitting(true)
      const launchPayload: Seedance25GeneratePayload = {
        scenario: identityTransfer ? 'multimodal' : scenario,
        identityTransfer,
        sourceFeedGenId: identityTransfer ? sourceFeedGenId : null,
        identityQuote: identityQuote?.seedance25_identity_quote,
        videoQuoteHash: measuredQuote?.quote_hash,
        videoQuoteId: measuredQuote?.quote_id,
        prompt: prompt.trim(),
        ratio: sourceSettings ? 'adaptive' : ratio,
        duration: sourceSettings ? -1 : duration,
        videoEditing: !identityTransfer && videoEditing,
        resolution,
        outputFormat,
        generateAudio,
        returnLastFrame,
        webSearch,
        nsfwChecker,
        firstFrameUrl: scenario === 'first_frame' || scenario === 'first_last' ? first : null,
        lastFrameUrl: scenario === 'first_last' ? last : null,
        referenceImages: referenceScenario ? [...new Set(refImages)].slice(0, 30) : [],
        referenceVideos: referenceScenario ? [...new Set(refVideos)].slice(0, 10) : [],
        referenceAudios: scenario === 'multimodal' ? [...new Set(refAudios)].slice(0, 10) : [],
      }
      if (needsMeasuredQuote) {
        if (!pendingKey || !measuredQuote?.quote_id) throw new Error('Откройте Mini App из Telegram для безопасного запуска')
        const pending = { quoteId: measuredQuote.quote_id, payload: launchPayload }
        localStorage.setItem(pendingKey, JSON.stringify(pending))
        setPendingLaunch(pending)
      }
      const result = await generateSeedance25(launchPayload)
      if (!mounted.current) return
      if (launchPayload.videoQuoteId) finishPending(launchPayload.videoQuoteId)
      setQueued(result)
      await onQueued?.(result)
    } catch (value) {
      if (!mounted.current) return
      if (value instanceof SeedanceApiError && ['video_quote_changed', 'video_quote_missing', 'video_rejected', 'video_not_reserved', 'video_input_invalid'].includes(value.code || '') && measuredQuote?.quote_id) {
        finishPending(measuredQuote.quote_id)
      }
      setError(value instanceof Error ? value.message : 'Не удалось запустить Seedance 2.5')
      if (needsMeasuredQuote) {
        // A changed tariff or source must be reviewed before another explicit launch.
        setQuoteState(null)
        setQuoteAttempt((value) => value + 1)
      }
    } finally {
      if (mounted.current) setSubmitting(false)
    }
  }

  return (
    <div className="glass min-w-0 space-y-5 overflow-hidden rounded-2xl border border-cyan/25 p-3 sm:p-4">
      <div className="rounded-2xl border border-cyan/25 bg-gradient-to-br from-cyan/10 via-cyan/5 to-transparent p-4">
        <div className="flex items-center gap-2">
          <span className="rounded-full border border-gold/40 bg-gold/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.14em] text-gold">NEW</span>
          <h3 className="font-serif text-xl font-semibold text-foreground">Seedance 2.5</h3>
        </div>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          Создавайте видео с нуля, оживляйте фото или управляйте результатом с помощью фото, видео и аудио-референсов.
        </p>
      </div>

      <section className="space-y-3">
        <SectionTitle
          eyebrow="Шаг 1"
          title="Что хотите сделать?"
          hint="По умолчанию выбран режим по референсам; текстовый режим можно включить вручную"
        />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {SCENARIOS.map((item) => (
            <ScenarioCard
              key={item.id}
              active={scenario === item.id}
              icon={item.icon}
              title={item.title}
              description={item.description}
              onClick={() => chooseScenario(item.id)}
            />
          ))}
        </div>
      </section>

      {identityTransfer && sourceFeedGenId ? (
        <p className="rounded-xl border border-cyan/25 bg-cyan/5 p-3 text-xs leading-relaxed text-muted-foreground">
          Повтор замены персонажа: стоимость рассчитана заново. Для замены используйте свои фото и исходное видео. При выборе другого сценария начнётся новая генерация без скрытых настроек публикации.
        </p>
      ) : null}

      {(scenario === 'first_frame' || scenario === 'first_last') ? (
        <section className="space-y-3 rounded-2xl border border-border/45 bg-secondary/15 p-3 sm:p-4">
          <SectionTitle
            eyebrow="Шаг 2"
            title={scenario === 'first_last' ? 'Добавьте начало и финал' : 'Добавьте исходное фото'}
            hint={scenario === 'first_last'
              ? 'Модель построит движение между первым и последним кадром'
              : 'Изображение станет первым кадром ролика'}
          />

          <div className={`grid gap-3 ${scenario === 'first_last' ? 'sm:grid-cols-2' : ''}`}>
            <div className="space-y-2">
              <div className="text-xs font-medium text-foreground">{scenario === 'first_last' ? 'Первый кадр' : 'Фото'}</div>
              <UploadButton
                label={firstFrame ? 'Заменить фото' : '＋ Загрузить фото'}
                accept="image/*,.jpg,.jpeg,.png,.webp,.bmp,.tiff,.gif"
                disabled={uploading}
                onFiles={(files) => void runUpload(() => uploadImage(files[0], 'first'))}
              />
              {firstFrame ? <FileRow item={firstFrame} onRemove={() => setFirstFrame(null)} /> : null}
            </div>

            {scenario === 'first_last' ? (
              <div className="space-y-2">
                <div className="text-xs font-medium text-foreground">Последний кадр</div>
                <UploadButton
                  label={lastFrame ? 'Заменить фото' : '＋ Загрузить фото'}
                  accept="image/*,.jpg,.jpeg,.png,.webp,.bmp,.tiff,.gif"
                  disabled={uploading}
                  onFiles={(files) => void runUpload(() => uploadImage(files[0], 'last'))}
                />
                {lastFrame ? <FileRow item={lastFrame} onRemove={() => setLastFrame(null)} /> : null}
              </div>
            ) : null}
          </div>

          <details className="rounded-xl border border-border/35 bg-background/30 px-3 py-2">
            <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Использовать URL или Asset ID вместо файла</summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-xs text-muted-foreground">
                <span>{scenario === 'first_last' ? 'Первый кадр' : 'Фото'} — URL / asset://</span>
                <input
                  value={firstSource}
                  onChange={(event) => setFirstSource(event.target.value)}
                  className="w-full rounded-xl border border-border/50 bg-background/50 px-3 py-2 text-xs text-foreground outline-none focus:border-cyan/50"
                />
              </label>
              {scenario === 'first_last' ? (
                <label className="space-y-1 text-xs text-muted-foreground">
                  <span>Последний кадр — URL / asset://</span>
                  <input
                    value={lastSource}
                    onChange={(event) => setLastSource(event.target.value)}
                    className="w-full rounded-xl border border-border/50 bg-background/50 px-3 py-2 text-xs text-foreground outline-none focus:border-cyan/50"
                  />
                </label>
              ) : null}
            </div>
          </details>
        </section>
      ) : null}

      {isAdmin && scenario === 'multimodal' ? (
        <section className="space-y-2 rounded-xl border border-cyan/30 p-3">
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={videoEditing} onChange={(event) => setVideoEditing(event.target.checked)} />
            Редактировать видео
          </label>
          <p className="text-xs text-muted-foreground">Одно исходное видео, 4–30 секунд. Результат сохранит длительность и формат исходного видео. Для обычной генерации по референсам оставьте переключатель выключенным.</p>
        </section>
      ) : null}

      {referenceScenario ? (
        <section className="space-y-4 rounded-2xl border border-border/45 bg-secondary/15 p-3 sm:p-4">
          <SectionTitle
            eyebrow="Шаг 2"
            title={identityTransfer ? 'Фото человека + исходное видео' : 'Добавьте референсы'}
            hint={identityTransfer ? 'Прямая замена: 1–3 фото одного человека и одно исходное видео. Без промежуточных кадров; длительность и формат берутся из видео. Точность внешности зависит от результата модели.' : 'Можно сочетать фото, видео и аудио — модель использует их как ориентиры'}
          />

          {identityTransfer ? (
            <p className="rounded-xl border border-cyan/25 bg-cyan/5 p-3 text-xs leading-relaxed text-muted-foreground">
              Фото и видео сохраняются при переключении между «Замена персонажа» и «По референсам», в прежнем порядке. Аудио-референсы и первый/последний кадры в этом сценарии не используются и остаются в своих режимах.
            </p>
          ) : null}
          <div className={`grid gap-3 ${identityTransfer ? 'lg:grid-cols-2' : 'lg:grid-cols-3'}`}>
            <div className="space-y-2 rounded-xl border border-border/35 bg-background/30 p-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <div className="text-sm font-medium text-foreground">{identityTransfer ? '📷 Внешность персонажа' : '📷 Фото'}</div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">{identityTransfer ? '@Image1–@Image3 · один человек' : 'Внешность, стиль, объекты'}</div>
                </div>
                <span className="text-[11px] text-muted-foreground">{images.length}/{identityTransfer ? 3 : 30}</span>
              </div>
              <UploadButton
                label="＋ Добавить фото"
                multiple
                accept="image/*,.jpg,.jpeg,.png,.webp,.bmp,.tiff,.gif"
                disabled={uploading || images.length >= (identityTransfer ? 3 : 30)}
                onFiles={(files) => {
                  void runUpload(async () => {
                    const limit = identityTransfer ? 3 : 30
                    if (identityTransfer && files.length + images.length + splitSources(imageSources, 30).length > limit) throw new Error(`Можно добавить максимум ${limit} фото; выбранные файлы не загружены`)
                    const selected = identityTransfer ? files : files.slice(0, Math.max(0, limit - images.length))
                    for (const file of selected) await uploadImage(file, 'refs')
                  })
                }}
              />
              <div className="space-y-1">{images.map((item, index) => (
                <FileRow key={`${item.file.id}-${index}`} item={item} role={identityTransfer ? `@Image${index + 1} · внешность` : undefined} onRemove={() => setImages((current) => current.filter((_, i) => i !== index))} />
              ))}</div>
            </div>

            <div className="space-y-2 rounded-xl border border-gold/25 bg-gold/5 p-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <div className="text-sm font-medium text-foreground">{identityTransfer ? '🎬 Исходное видео' : '🎬 Видео'}</div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">{identityTransfer ? '@Video1 · движения и сцена' : 'Движение и динамика'}</div>
                </div>
                <span className="text-[11px] text-muted-foreground">{videos.length}/{identityTransfer ? 1 : 10}</span>
              </div>
              <UploadButton
                label={identityTransfer ? '＋ Загрузить исходное видео' : '＋ Добавить видео'}
                multiple={!identityTransfer}
                accept=".mp4,.mov,video/mp4,video/quicktime"
                disabled={uploading || videos.length >= (identityTransfer ? 1 : 10)}
                onFiles={(files) => {
                  void runUpload(async () => {
                    const limit = identityTransfer ? 1 : 10
                    if (identityTransfer && files.length + videos.length + splitSources(videoSources, 10).length > limit) throw new Error(`Можно добавить максимум ${limit} видео; выбранные файлы не загружены`)
                    const selected = identityTransfer ? files : files.slice(0, Math.max(0, limit - videos.length))
                    for (const file of selected) await uploadVideo(file)
                  })
                }}
              />
              <div className="rounded-lg border border-gold/20 bg-gold/5 px-2.5 py-2 text-[11px] leading-relaxed text-gold">
                Видео-референс увеличивает стоимость генерации ×2
              </div>
              <div className="text-[10px] leading-relaxed text-muted-foreground">
                {identityTransfer ? 'MP4/MOV · до 200 MB · 4–30с · одно видео' : 'MP4/MOV · до 200 MB · 2–30с · суммарно до 30с'}
                {knownVideoSeconds ? ` · выбрано ${knownVideoSeconds.toFixed(1)}с` : ''}
              </div>
              <div className="space-y-1">{videos.map((item, index) => (
                <FileRow key={`${item.file.id}-${index}`} item={item} role={identityTransfer ? `@Video${index + 1} · движения и сцена` : undefined} onRemove={() => setVideos((current) => current.filter((_, i) => i !== index))} />
              ))}</div>
            </div>

            {!identityTransfer ? <div className="space-y-2 rounded-xl border border-border/35 bg-background/30 p-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <div className="text-sm font-medium text-foreground">🎵 Аудио</div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">Звук, голос, ритм</div>
                </div>
                <span className="text-[11px] text-muted-foreground">{audios.length}/10</span>
              </div>
              <UploadButton
                label="＋ Добавить аудио"
                multiple
                accept=".wav,.mp3,audio/wav,audio/mpeg"
                disabled={uploading || audios.length >= 10}
                onFiles={(files) => {
                  const selected = files.slice(0, Math.max(0, 10 - audios.length))
                  void runUpload(async () => {
                    for (const file of selected) await uploadAudio(file)
                  })
                }}
              />
              <div className="text-[10px] leading-relaxed text-muted-foreground">WAV/MP3 · до 15 MB · 2–30с</div>
              <div className="space-y-1">{audios.map((item, index) => (
                <FileRow key={`${item.file.id}-${index}`} item={item} onRemove={() => setAudios((current) => current.filter((_, i) => i !== index))} />
              ))}</div>
            </div> : null}
          </div>

          <details className="rounded-xl border border-border/35 bg-background/30 px-3 py-2">
            <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Для продвинутых: добавить URL или Asset ID</summary>
            <div className="mt-3 grid gap-3">
              <label className="space-y-1 text-xs text-muted-foreground">
                <span>Фото — по одному URL / asset:// на строку</span>
                <textarea aria-label="Фото — по одному URL / asset:// на строку" rows={2} value={imageSources} onChange={(event) => setImageSources(event.target.value)} className="w-full rounded-xl border border-border/50 bg-background/50 px-3 py-2 text-xs text-foreground outline-none focus:border-cyan/50" />
              </label>
              <label className="space-y-1 text-xs text-muted-foreground">
                <span>Видео — по одному URL / asset:// на строку</span>
                <textarea aria-label="Видео — по одному URL / asset:// на строку" rows={2} value={videoSources} onChange={(event) => setVideoSources(event.target.value)} className="w-full rounded-xl border border-border/50 bg-background/50 px-3 py-2 text-xs text-foreground outline-none focus:border-cyan/50" />
              </label>
              {!identityTransfer ? <label className="space-y-1 text-xs text-muted-foreground">
                <span>Аудио — по одному URL / asset:// на строку</span>
                <textarea aria-label="Аудио — по одному URL / asset:// на строку" rows={2} value={audioSources} onChange={(event) => setAudioSources(event.target.value)} className="w-full rounded-xl border border-border/50 bg-background/50 px-3 py-2 text-xs text-foreground outline-none focus:border-cyan/50" />
              </label> : null}
              {identityTransfer ? <p className="text-xs text-muted-foreground">Ссылки на фото добавляются после загруженных фото, в порядке строк. Используйте ссылки только на свои фото и видео, ранее загруженные в приложение. Внешние ссылки и Asset ID в этом сценарии не поддерживаются.</p> : null}
            </div>
          </details>
        </section>
      ) : null}

      <section className="space-y-3">
        <SectionTitle
          eyebrow={`Шаг ${promptStep}`}
          title={identityTransfer ? 'Инструкция прямой замены' : 'Опишите результат'}
          hint={identityTransfer ? 'Можно оставить пустым. Полный промпт с @Image1 и @Video1 отправится без шаблона; короткие пожелания дополнят команду замены. Фото и исходное видео идут прямо в Seedance.' : scenario === 'text'
            ? 'Что происходит в кадре, как движется камера, какой свет и настроение'
            : 'Референсы задают основу, а текст объясняет, что именно с ними сделать'}
        />
        <div className="space-y-2">
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={6}
            placeholder={promptPlaceholder}
            aria-label="Промпт для Seedance 2.5"
            className="w-full resize-y rounded-2xl border border-border/50 bg-background/45 px-3 py-3 text-sm leading-relaxed text-foreground outline-none transition focus:border-cyan/50"
          />
          <div className="flex items-center justify-between gap-3 text-[11px] text-muted-foreground">
            <span>Совет: движение камеры пишите прямо здесь — например, «плавный наезд, без зума»</span>
            <span className={promptLength > promptLimit ? 'text-destructive' : ''}>{promptLength}/{promptLimit}</span>
          </div>
        </div>
      </section>

      <section className="space-y-4 rounded-2xl border border-border/45 bg-secondary/15 p-3 sm:p-4">
        <SectionTitle
          eyebrow={`Шаг ${settingsStep}`}
          title="Основные настройки"
          hint={identityTransfer ? 'Длительность и формат кадра определяются исходным видео. Цена рассчитывается по его проверенной длительности.' : 'Для первого запуска обычно достаточно 720p, 5 секунд и автоматического формата кадра'}
        />

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-2">
            <div className="text-xs font-medium text-foreground">Качество</div>
            <div className="grid grid-cols-2 gap-2">
              {(['480p', '720p'] as Seedance25Resolution[]).map((value) => {
                const rate = Number(model?.quality_costs?.[value] || 0)
                return (
                  <Option key={value} active={resolution === value} onClick={() => setResolution(value)}>
                    <span className="block">{value}</span>
                    <span className="mt-0.5 block text-[10px] font-normal opacity-70">{rate ? `${rate}🍌/с` : value === '720p' ? 'лучшее качество' : 'экономнее'}</span>
                  </Option>
                )
              })}
            </div>
          </div>

          <fieldset disabled={sourceSettings} className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-medium text-foreground">Длительность</div>
              <div className="rounded-lg bg-background/50 px-2 py-1 text-xs font-semibold text-cyan">{sourceSettings ? 'Как в исходном видео' : duration === -1 ? 'Авто' : `${duration} сек`}</div>
            </div>
            <div className="flex items-center gap-2">
              <button type="button" className="h-10 w-10 shrink-0 rounded-xl border border-border/50 text-lg" onClick={() => setDuration((value) => Math.max(4, value === -1 ? 5 : value - 1))}>−</button>
              <input type="range" min={4} max={30} value={sourceSettings ? identityQuote?.source_video_duration_seconds ?? (knownVideoSeconds || 5) : duration === -1 ? 5 : duration} onChange={(event) => setDuration(Number(event.target.value))} className="min-w-0 flex-1" aria-label="Длительность видео" />
              <button type="button" className="h-10 w-10 shrink-0 rounded-xl border border-border/50 text-lg" onClick={() => setDuration((value) => Math.min(30, value === -1 ? 5 : value + 1))}>+</button>
            </div>
            {isAdmin && !identityTransfer ? (
              <button type="button" onClick={() => setDuration(-1)} className={`text-[11px] ${duration === -1 ? 'text-cyan' : 'text-muted-foreground'}`}>
                {duration === -1 ? '✓ Автоматическая длительность включена' : 'Использовать Auto (админ)'}
              </button>
            ) : null}
          </fieldset>
        </div>

        <fieldset disabled={sourceSettings} className="space-y-2">
          <div className="text-xs font-medium text-foreground">Формат кадра{sourceSettings ? ' · как в исходном видео' : ''}</div>
          <div className="flex flex-wrap gap-2">
            {RATIOS.map((value) => (
              <Option key={value} active={(sourceSettings ? 'adaptive' : ratio) === value} onClick={() => setRatio(value)}>
                {value === 'adaptive' ? 'Авто' : value}
              </Option>
            ))}
          </div>
        </fieldset>

        <Toggle
          value={generateAudio}
          onChange={setGenerateAudio}
          label="🔊 Сгенерировать звук"
          hint="Модель попробует создать звук вместе с видео"
        />
      </section>

      <details className="rounded-2xl border border-border/45 bg-secondary/10 p-3 sm:p-4">
        <summary className="cursor-pointer text-sm font-semibold text-foreground">Дополнительные настройки</summary>
        <p className="mt-1 text-xs text-muted-foreground">Обычно их можно оставить как есть</p>
        <div className="mt-4 space-y-3">
          <div className="space-y-2">
            <div className="text-xs font-medium text-foreground">Формат файла</div>
            <div className="grid grid-cols-2 gap-2">
              {(['mp4', 'mov'] as Seedance25OutputFormat[]).map((value) => (
                <Option key={value} active={outputFormat === value} onClick={() => setOutputFormat(value)}>
                  {value.toUpperCase()}{value === 'mp4' ? ' · рекомендуется' : ''}
                </Option>
              ))}
            </div>
          </div>

          <Toggle
            value={returnLastFrame}
            onChange={setReturnLastFrame}
            label="🖼 Получить последний кадр отдельно"
            hint="После генерации бот дополнительно пришлёт финальный кадр изображения"
          />
          <Toggle
            value={webSearch}
            onChange={setWebSearch}
            label="🌐 Поиск в сети"
            hint="Разрешить модели использовать web search при генерации"
          />
          <Toggle
            value={nsfwChecker}
            onChange={setNsfwChecker}
            label="🛡 Дополнительная проверка контента"
            hint="Включить NSFW-проверку со стороны Kie"
          />
        </div>
      </details>

      <div className={`rounded-2xl border p-4 ${hasVideoReference ? 'border-gold/35 bg-gold/7' : 'border-cyan/25 bg-cyan/5'}`}>
        <div className="flex items-end justify-between gap-4">
          <div>
            <div className="text-xs text-muted-foreground">Стоимость генерации</div>
            <div className="mt-1 text-2xl font-bold text-foreground">{needsMeasuredQuote && !measuredQuote ? 'После проверки видео' : `${price || 0}🍌`}</div>
          </div>
          {!isAdmin ? <div className="text-right text-xs text-muted-foreground">Баланс<br /><span className="font-semibold text-foreground">{credits}🍌</span></div> : <div className="text-right text-xs text-cyan">Для админа<br /><span className="font-semibold">без списания</span></div>}
        </div>
        {needsMeasuredQuote || identityTransfer ? (
          <div className="mt-3 space-y-2 text-xs leading-relaxed text-muted-foreground" aria-live="polite">
            {identityTransfer && identityRefs.issue ? <p>{identityRefs.issue}</p> : quoteError ? (
              <><p className="text-destructive">{quoteError}</p><button type="button" className="text-cyan underline" onClick={() => setQuoteAttempt((value) => value + 1)}>Повторить расчёт</button></>
            ) : measuredQuote ? (
              <p>Видеорефы: {measuredQuote.input_seconds?.toFixed(2)}с + результат {measuredQuote.selected_output_seconds?.toFixed(2)}с. Цена фиксируется при запуске.</p>
            ) : <p>Проверяем длительность и рассчитываем стоимость…</p>}
          </div>
        ) : hasVideoReference ? (
          <div className="mt-3 rounded-xl border border-gold/20 bg-background/25 px-3 py-2 text-xs text-gold">
            🎬 Видео-референс: базовая цена {basePrice}🍌 × 2 = {price}🍌
          </div>
        ) : (
          <div className="mt-2 text-[11px] text-muted-foreground">Цена зависит от качества и длительности ролика</div>
        )}
      </div>

      {error ? <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</div> : null}
      {queued ? (
        <div className="rounded-xl border border-cyan/30 bg-cyan/5 p-3 text-sm">
          <strong>{queued.status === 'done' ? '✅ Видео готово' : queued.status === 'failed' ? 'Генерация завершилась ошибкой' : '✅ Видео поставлено в очередь'}</strong>
          <div className="mt-1 break-all font-mono text-xs text-muted-foreground">{queued.task_id}</div>
          <div className="mt-1 text-xs text-muted-foreground">{queued.admin_free ? 'Для администратора без списания.' : `Списано ${queued.cost}🍌.`} Результат придёт в Telegram.</div>
        </div>
      ) : null}

      <button
        type="button"
        disabled={submitting || !!pendingLaunch || uploading || (needsMeasuredQuote && !measuredQuote?.quote_hash) || (identityTransfer && (!!identityRefs.issue || !identityQuote)) || !canAfford || promptLength > promptLimit}
        onClick={() => void submit()}
        className="w-full rounded-2xl border border-cyan/50 bg-cyan/15 px-4 py-3.5 text-sm font-semibold text-cyan transition hover:bg-cyan/20 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {pendingLaunch && !submitting
          ? 'Проверяю ранее отправленный запуск…'
          : submitting
          ? 'Запускаю генерацию…'
          : uploading
            ? 'Загружаю файлы…'
            : identityTransfer && identityRefs.issue
              ? 'Добавьте фото и исходное видео'
            : needsMeasuredQuote && !measuredQuote
              ? identityTransfer && identityRefs.issue ? 'Добавьте фото и исходное видео' : quoteError ? 'Не удалось рассчитать стоимость' : 'Рассчитываю стоимость…'
            : !canAfford
              ? `Не хватает ${Math.max(0, price - credits)}🍌`
              : isAdmin
                ? '🚀 Создать видео'
                : `🚀 Создать видео · ${price || 0}🍌`}
      </button>
    </div>
  )
}
