'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '@/lib/app-context'
import { copyTextToClipboard } from '@/lib/clipboard'
import type { PromptItem, TrendGenerationSettings, TrendUserField } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { deactivatePrompt, fetchPromptLink, fetchPrompts, submitPrompt, uploadFile } from '@/lib/api'
import { updateTrendPreview } from '@/lib/trend-admin-api'
import { mediaAspectRatio, normalizeMiniAppMediaUrl, videoPreviewFrameUrl } from '@/lib/media-url'
import { TrendRunnerDialog } from '@/components/trend-runner-dialog'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import {
  Film,
  Flame,
  Check,
  Copy,
  ImagePlus,
  Loader2,
  Plus,
  Repeat2,
  Sparkles,
  Trash2,
  Upload,
  Pencil,
  X,
} from 'lucide-react'

type TrendKind = 'image' | 'video'
type TrendPreviewKind = 'image' | 'video'

const TREND_TAG = 'trend'
const VIDEO_TREND_TAG = 'trend-video'
const VIDEO_TREND_PREVIEW_MAX_BYTES = 200 * 1024 * 1024
const VIDEO_PREVIEW_EXTENSIONS = new Set(['mp4', 'mov', 'm4v', 'webm'])
const IMAGE_PREVIEW_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif', 'avif'])

function normalizedTags(trend: PromptItem) {
  return new Set((trend.tags || []).map((tag) => String(tag).trim().toLowerCase()))
}

function hasTrendTag(trend: PromptItem) {
  return normalizedTags(trend).has(TREND_TAG)
}

function hasVideoTag(trend: PromptItem) {
  return normalizedTags(trend).has(VIDEO_TREND_TAG)
}

const PINTEREST_TAGS = new Set(['pinterest', 'pinterest-repeat', 'repeat-pinterest'])

// Pinterest AI is intentionally excluded from the Trends showcase: it is
// reachable only via Services -> Pinterest AI, which launches the regular
// TrendRunnerDialog flow. Mirrors TrendRunnerDialog's isPinterestRepeatItem
// detection.
function isPinterestRepeatTrend(trend: PromptItem) {
  const tags = normalizedTags(trend)
  for (const tag of PINTEREST_TAGS) {
    if (tags.has(tag)) return true
  }
  return String(trend.title || '').toLowerCase().includes('pinterest')
}

function previewKindFromFile(file: File): TrendPreviewKind | null {
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  if (file.type.startsWith('video/') || VIDEO_PREVIEW_EXTENSIONS.has(extension)) return 'video'
  if (file.type.startsWith('image/') || IMAGE_PREVIEW_EXTENSIONS.has(extension)) return 'image'
  return null
}

function previewKindForTrend(trend: PromptItem, legacyVideoFallback = false): TrendPreviewKind {
  const explicit = String(trend.generation_settings?.preview_type || '').trim().toLowerCase()
  if (explicit === 'video' || explicit === 'image') return explicit

  const previewUrl = String(trend.preview_url || '').split('?', 1)[0].split('#', 1)[0]
  const extension = previewUrl.split('.').pop()?.toLowerCase() || ''
  if (VIDEO_PREVIEW_EXTENSIONS.has(extension)) return 'video'
  if (IMAGE_PREVIEW_EXTENSIONS.has(extension)) return 'image'
  return legacyVideoFallback ? 'video' : 'image'
}

export function TrendsTab() {
  const { state, trendToRun, setTrendToRun } = useApp()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const editFileInputRef = useRef<HTMLInputElement>(null)
  const previewUploadAttemptRef = useRef(0)
  const previewUploadPromiseRef = useRef<Promise<string | null> | null>(null)
  const editUploadAttemptRef = useRef(0)
  const editUploadPromiseRef = useRef<Promise<string | null> | null>(null)
  const [items, setItems] = useState<PromptItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [trendKind, setTrendKind] = useState<TrendKind>('image')
  const [previewKind, setPreviewKind] = useState<TrendPreviewKind>('image')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [promptText, setPromptText] = useState('')
  const [userFields, setUserFields] = useState<TrendUserField[]>([])
  const [model, setModel] = useState('banana_pro')
  const [videoDuration, setVideoDuration] = useState(5)
  const [trendRatio, setTrendRatio] = useState('1:1')
  const [imageQuality, setImageQuality] = useState('2K')
  const [previewUrl, setPreviewUrl] = useState('')
  const [uploadingPreview, setUploadingPreview] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [removingId, setRemovingId] = useState<number | null>(null)
  const [copiedId, setCopiedId] = useState<number | null>(null)
  const [editingTrend, setEditingTrend] = useState<PromptItem | null>(null)
  const [editPreviewUrl, setEditPreviewUrl] = useState('')
  const [uploadingEditPreview, setUploadingEditPreview] = useState(false)
  const [savingEdit, setSavingEdit] = useState(false)
  const [previewTrend, setPreviewTrend] = useState<PromptItem | null>(null)
  const [videoAspectRatios, setVideoAspectRatios] = useState<Record<number, string>>({})
  const [videoPreviewReady, setVideoPreviewReady] = useState<Record<number, boolean>>({})
  const [videoPreviewFailed, setVideoPreviewFailed] = useState<Record<number, boolean>>({})

  const isLive = state.mode === 'live'
  const isAdmin = state.user.isAdmin
  const availableModels = trendKind === 'video'
    ? state.videoModels.filter((item) => item.supports.includes('imgtxt'))
    : state.imageModels
  const selectedTrendImageModel = state.imageModels.find((item) => item.id === model)
  const selectedTrendVideoModel = state.videoModels.find((item) => item.id === model)
  const trendImageQualities =
    selectedTrendImageModel?.id === 'banana_pro' || selectedTrendImageModel?.id === 'banana_2'
      ? ['1K', '2K', '4K']
      : selectedTrendImageModel?.qualities?.length
        ? selectedTrendImageModel.qualities
        : ['basic']

  const videoModelIds = useMemo(
    () => new Set(state.videoModels.map((item) => item.id)),
    [state.videoModels],
  )

  const isVideoTrend = (trend: PromptItem) =>
    trend.category === 'video' ||
    hasVideoTag(trend) ||
    videoModelIds.has(String(trend.model || ''))

  const photoTrends = useMemo(() => items.filter((item) => !isVideoTrend(item)), [items, videoModelIds])
  const videoTrends = useMemo(() => items.filter((item) => isVideoTrend(item)), [items, videoModelIds])

  async function loadTrends() {
    if (!isLive) {
      setItems([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const trends = await fetchPrompts({ source: 'tag', tag: TREND_TAG, limit: 80 })
      setItems(trends.filter((trend) => hasTrendTag(trend) && !isPinterestRepeatTrend(trend)))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить тренды')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadTrends()
  }, [isLive])

  useEffect(() => {
    const models = trendKind === 'video' ? state.videoModels : state.imageModels
    if (!models.some((item) => item.id === model)) {
      setModel(models[0]?.id || (trendKind === 'video' ? 'v3_pro' : 'banana_pro'))
    }
  }, [model, state.imageModels, state.videoModels, trendKind])

  useEffect(() => {
    if (trendKind !== 'video' || !selectedTrendVideoModel) return
    setVideoDuration((current) => (
      selectedTrendVideoModel.durations.includes(current)
        ? current
        : selectedTrendVideoModel.durations[0] || 5
    ))
  }, [selectedTrendVideoModel, trendKind])

  useEffect(() => {
    const selectedModel = trendKind === 'video'
      ? state.videoModels.find((item) => item.id === model)
      : state.imageModels.find((item) => item.id === model)
    const ratios = selectedModel?.ratios || []
    if (ratios.length && !ratios.includes(trendRatio)) {
      setTrendRatio(ratios[0])
    }
    if (trendKind === 'image' && !trendImageQualities.includes(imageQuality)) {
      setImageQuality(trendImageQualities[0] || 'basic')
    }
  }, [
    imageQuality,
    model,
    state.imageModels,
    state.videoModels,
    trendImageQualities,
    trendKind,
    trendRatio,
  ])

  const changeTrendKind = (nextKind: TrendKind) => {
    if (nextKind === trendKind) return
    setTrendKind(nextKind)
  }

  const changePreviewKind = (nextKind: TrendPreviewKind) => {
    if (nextKind === previewKind) return
    setPreviewKind(nextKind)
    setPreviewUrl('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const resetForm = () => {
    setTrendKind('image')
    setPreviewKind('image')
    setTitle('')
    setDescription('')
    setPromptText('')
    setUserFields([])
    setModel(state.imageModels[0]?.id || 'banana_pro')
    setVideoDuration(5)
    setTrendRatio('1:1')
    setImageQuality('2K')
    setPreviewUrl('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const openEditTrend = (trend: PromptItem) => {
    setEditingTrend(trend)
    setEditPreviewUrl('')
    setError(null)
    if (editFileInputRef.current) editFileInputRef.current.value = ''
  }

  const applyTrend = (trend: PromptItem) => {
    setTrendToRun(trend)
  }

  const handlePreviewUpload = async (file?: File) => {
    if (!file) return
    const detectedKind = previewKindFromFile(file)
    if (!detectedKind || detectedKind !== previewKind) {
      setError(previewKind === 'video' ? 'Выберите видео MP4/WebM/MOV' : 'Выберите изображение JPG/PNG/WebP')
      return
    }
    if (detectedKind === 'video' && file.size > VIDEO_TREND_PREVIEW_MAX_BYTES) {
      setError('Промо-видео слишком большое, максимум 200MB')
      return
    }

    const attemptId = ++previewUploadAttemptRef.current
    const localPreviewUrl = URL.createObjectURL(file)
    setUploadingPreview(true)
    setError(null)
    setPreviewUrl((current) => {
      if (current.startsWith('blob:')) URL.revokeObjectURL(current)
      return localPreviewUrl
    })
    const uploadPromise = uploadFile(
      detectedKind === 'video' ? 'trend_video_preview' : 'image_reference',
      file,
    )
      .then((uploaded) => uploaded.url)
      .catch((e) => {
        if (previewUploadAttemptRef.current === attemptId) {
          setPreviewUrl((current) => current === localPreviewUrl ? '' : current)
          setError(e instanceof Error ? e.message : 'Не удалось загрузить preview')
        }
        return null
      })
    previewUploadPromiseRef.current = uploadPromise
    try {
      const uploadedUrl = await uploadPromise
      if (previewUploadAttemptRef.current !== attemptId) return
      if (uploadedUrl) setPreviewUrl(uploadedUrl)
    } finally {
      if (previewUploadAttemptRef.current === attemptId) {
        setUploadingPreview(false)
        previewUploadPromiseRef.current = null
      }
      URL.revokeObjectURL(localPreviewUrl)
    }
  }

  const handleEditPreviewUpload = async (file?: File) => {
    if (!file || !editingTrend) return
    const trend = editingTrend
    const detectedKind = previewKindFromFile(file)
    if (!detectedKind) {
      setError('Выберите изображение JPG/PNG/WebP или видео MP4/WebM/MOV')
      return
    }
    if (detectedKind === 'video' && file.size > VIDEO_TREND_PREVIEW_MAX_BYTES) {
      setError('Промо-видео слишком большое, максимум 200MB')
      return
    }

    const attemptId = ++editUploadAttemptRef.current
    const localPreviewUrl = URL.createObjectURL(file)
    setUploadingEditPreview(true)
    setError(null)
    setEditPreviewUrl((current) => {
      if (current.startsWith('blob:')) URL.revokeObjectURL(current)
      return localPreviewUrl
    })
    const uploadPromise = uploadFile(
      detectedKind === 'video' ? 'trend_video_preview' : 'image_reference',
      file,
    )
      .then(async (uploaded) => {
        const updated = await updateTrendPreview(trend.id, uploaded.url, detectedKind)
        return { uploadedUrl: uploaded.url, updated }
      })
      .catch((e) => {
        if (editUploadAttemptRef.current === attemptId) {
          setEditPreviewUrl((current) => current === localPreviewUrl ? '' : current)
          setError(e instanceof Error ? e.message : 'Не удалось обновить preview')
        }
        return null
      })
    editUploadPromiseRef.current = uploadPromise.then((result) => result?.uploadedUrl || null)
    try {
      const result = await uploadPromise
      if (editUploadAttemptRef.current !== attemptId) return
      if (result) {
        setEditPreviewUrl(result.uploadedUrl)
        setEditingTrend(result.updated)
        setItems((prev) => prev.map((item) => item.id === result.updated.id ? result.updated : item))
      }
    } finally {
      if (editUploadAttemptRef.current === attemptId) {
        setUploadingEditPreview(false)
        editUploadPromiseRef.current = null
      }
      URL.revokeObjectURL(localPreviewUrl)
    }
  }

  const addUserField = () => {
    setUserFields((current) => {
      if (current.length >= 6) return current
      const label = `Поле ${current.length + 1}`
      return [
        ...current,
        {
          key: label,
          label,
          type: 'text',
          required: true,
          placeholder: '',
          max_length: 80,
        },
      ]
    })
  }

  const updateUserField = (index: number, patch: Partial<TrendUserField>) => {
    setUserFields((current) =>
      current.map((field, fieldIndex) =>
        fieldIndex === index ? { ...field, ...patch } : field,
      ),
    )
  }

  const removeUserField = (index: number) => {
    setUserFields((current) => current.filter((_, fieldIndex) => fieldIndex !== index))
  }

  const handleCreate = async () => {
    if (!isAdmin || submitting) return
    if (!title.trim() || !promptText.trim() || !previewUrl || !model) {
      setError('Заполните название, preview, нейросеть и скрытый prompt')
      return
    }
    const normalizedUserFields = userFields.map((field) => {
      const label = field.label.trim()
      return {
        ...field,
        key: label,
        label,
        required: true,
        placeholder: String(field.placeholder || '').trim(),
        max_length: field.type === 'text' ? Math.max(1, Math.min(160, field.max_length || 80)) : undefined,
        min: field.type === 'number' ? field.min : undefined,
        max: field.type === 'number' ? field.max : undefined,
      }
    })
    if (normalizedUserFields.some((field) => !field.key)) {
      setError('Укажите название каждого пользовательского поля')
      return
    }
    if (normalizedUserFields.some((field) => field.key.includes('{{') || field.key.includes('}}'))) {
      setError('Название пользовательского поля не должно содержать фигурные скобки')
      return
    }
    if (new Set(normalizedUserFields.map((field) => field.key)).size !== normalizedUserFields.length) {
      setError('Названия пользовательских полей не должны повторяться')
      return
    }
    const missingTemplateField = normalizedUserFields.find(
      (field) => !promptText.includes(`{{${field.key}}}`),
    )
    if (missingTemplateField) {
      setError(`Добавьте {{${missingTemplateField.key}}} в скрытый prompt`)
      return
    }
    const invalidNumberRange = normalizedUserFields.find(
      (field) =>
        field.type === 'number' &&
        typeof field.min === 'number' &&
        typeof field.max === 'number' &&
        field.min > field.max,
    )
    if (invalidNumberRange) {
      setError(`Минимум поля «${invalidNumberRange.label}» больше максимума`)
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      let finalPreviewUrl = previewUrl
      if (finalPreviewUrl.startsWith('blob:') && previewUploadPromiseRef.current) {
        setError('Дожидаюсь сохранения preview на сервере…')
        const uploadedUrl = await previewUploadPromiseRef.current
        if (!uploadedUrl) {
          setError('Не удалось сохранить preview. Повторите загрузку файла.')
          return
        }
        finalPreviewUrl = uploadedUrl
        setPreviewUrl(uploadedUrl)
      }
      if (finalPreviewUrl.startsWith('blob:')) {
        setError('Preview еще не сохранен на сервере. Подождите несколько секунд и повторите.')
        return
      }

      const generationSettings: TrendGenerationSettings = trendKind === 'video'
        ? {
            kind: 'video',
            user_input: 'photo',
            model,
            ratio: trendRatio,
            preview_type: previewKind,
            user_fields: normalizedUserFields.length ? normalizedUserFields : undefined,
            scenario: 'imgtxt',
            duration: videoDuration,
            grok_mode: selectedTrendVideoModel?.grok_modes?.[0] || 'normal',
            grok_resolution: selectedTrendVideoModel?.grok_resolutions?.[0] || '480p',
            veo_generation_type:
              selectedTrendVideoModel?.veo_generation_types?.find((value) =>
                value.toUpperCase().includes('IMAGE'),
              ) ||
              selectedTrendVideoModel?.veo_generation_types?.[0] ||
              'IMAGE_2_VIDEO',
            veo_translation: true,
            veo_resolution: selectedTrendVideoModel?.veo_resolutions?.[0] || '720p',
            veo_seed: null,
            veo_watermark: '',
            kling_negative_prompt: '',
            kling_cfg_scale: 0.5,
            omni_resolution: selectedTrendVideoModel?.omni_resolutions?.[0] || '720p',
            omni_seed: null,
            omni_audio_ids: [],
            omni_character_ids: [],
            omni_base_voice: selectedTrendVideoModel?.omni_base_voices?.[0] || 'achernar',
            omni_voice_name: '',
            omni_voice_description: '',
            omni_example_dialogue: '',
            omni_character_name: '',
            omni_character_audio_ids: [],
          }
        : {
            kind: 'image',
            user_input: 'photo',
            model,
            ratio: trendRatio,
            preview_type: previewKind,
            user_fields: normalizedUserFields.length ? normalizedUserFields : undefined,
            quality: imageQuality,
            count: 1,
            nsfw_checker: false,
            nsfw_enabled: false,
          }

      const created = await submitPrompt({
        title: title.trim(),
        description: description.trim(),
        promptText: promptText.trim(),
        previewUrl: finalPreviewUrl,
        model,
        tags: trendKind === 'video'
          ? [TREND_TAG, VIDEO_TREND_TAG]
          : [TREND_TAG],
        generationSettings,
      })
      setItems((prev) => [created, ...prev.filter((item) => item.id !== created.id)])
      resetForm()
      setIsCreateOpen(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось опубликовать тренд')
    } finally {
      setSubmitting(false)
    }
  }

  const handleRemove = async (trend: PromptItem) => {
    if (!isAdmin || removingId !== null) return
    setRemovingId(trend.id)
    setError(null)
    try {
      await deactivatePrompt(trend.id)
      setItems((prev) => prev.filter((item) => item.id !== trend.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось убрать тренд')
    } finally {
      setRemovingId(null)
    }
  }

  const handleSaveEdit = async () => {
    if (!isAdmin || !editingTrend || savingEdit) return
    if (!editPreviewUrl) {
      setError('Загрузите новый preview')
      return
    }
    setSavingEdit(true)
    try {
      setEditingTrend(null)
      setEditPreviewUrl('')
      if (editFileInputRef.current) editFileInputRef.current.value = ''
    } finally {
      setSavingEdit(false)
    }
  }

  const handleCopyLink = async (trend: PromptItem) => {
    try {
      const link = await fetchPromptLink(trend.id)
      await copyTextToClipboard(link)
      setCopiedId(trend.id)
      window.setTimeout(() => setCopiedId((current) => current === trend.id ? null : current), 1800)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось скопировать ссылку')
    }
  }

  const rememberVideoAspectRatio = (trendId: number, video: HTMLVideoElement) => {
    const width = Number(video.videoWidth || 0)
    const height = Number(video.videoHeight || 0)
    if (!width || !height) return
    setVideoAspectRatios((current) => {
      const ratio = `${width} / ${height}`
      return current[trendId] === ratio ? current : { ...current, [trendId]: ratio }
    })
  }

  const setVideoCardReady = (trendId: number, ready: boolean) => {
    setVideoPreviewReady((current) => (
      current[trendId] === ready ? current : { ...current, [trendId]: ready }
    ))
  }

  const setVideoCardFailed = (trendId: number, failed: boolean) => {
    setVideoPreviewFailed((current) => (
      current[trendId] === failed ? current : { ...current, [trendId]: failed }
    ))
  }

  const renderTrendGrid = (trendItems: PromptItem[], sectionTitle: string, videoSection: boolean) => {
    if (!trendItems.length) return null
    return (
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-serif text-lg font-semibold text-foreground">{sectionTitle}</h3>
          <span className="rounded-full bg-secondary/60 px-2.5 py-1 text-xs text-muted-foreground">{trendItems.length}</span>
        </div>
        <div className="grid grid-cols-2 items-start gap-3 md:grid-cols-3">
          {trendItems.map((trend) => {
            const modelLabel = videoSection
              ? state.videoModels.find((item) => item.id === trend.model)?.label
              : state.imageModels.find((item) => item.id === trend.model)?.label
            const mediaKind = previewKindForTrend(trend, videoSection)
            const posterUrl = trend.preview_poster_url
              ? normalizeMiniAppMediaUrl(trend.preview_poster_url)
              : ''
            return (
              <article key={trend.id} className="glass min-w-0 overflow-hidden rounded-2xl border border-border/50">
                <div className="relative bg-secondary/40">
                  {trend.preview_url ? mediaKind === 'video' ? (
                    <div className="relative w-full overflow-hidden bg-black">
                      <video
                        src={videoPreviewFrameUrl(trend.preview_url)}
                        poster={posterUrl || undefined}
                        muted
                        autoPlay
                        loop
                        playsInline
                        preload="auto"
                        onLoadedMetadata={(event) => rememberVideoAspectRatio(trend.id, event.currentTarget)}
                        onLoadedData={() => {
                          setVideoCardFailed(trend.id, false)
                          setVideoCardReady(trend.id, true)
                        }}
                        onCanPlay={() => {
                          setVideoCardFailed(trend.id, false)
                          setVideoCardReady(trend.id, true)
                        }}
                        onPlaying={() => {
                          setVideoCardFailed(trend.id, false)
                          setVideoCardReady(trend.id, true)
                        }}
                        onLoadStart={() => {
                          setVideoCardFailed(trend.id, false)
                          setVideoCardReady(trend.id, false)
                        }}
                        onWaiting={() => setVideoCardReady(trend.id, false)}
                        onError={() => {
                          setVideoCardFailed(trend.id, true)
                          setVideoCardReady(trend.id, false)
                        }}
                        style={{ aspectRatio: videoAspectRatios[trend.id] || mediaAspectRatio(trend.generation_settings?.ratio) }}
                        className="w-full bg-black object-contain"
                      />
                      <span className="pointer-events-none absolute bottom-2 left-2 rounded-full bg-black/65 px-2.5 py-1 text-[10px] font-medium text-white backdrop-blur">
                        Как это работает
                      </span>
                      {posterUrl && (!videoPreviewReady[trend.id] || videoPreviewFailed[trend.id]) ? (
                        <img
                          src={posterUrl}
                          alt=""
                          aria-hidden="true"
                          loading="lazy"
                          className="absolute inset-0 h-full w-full bg-secondary/40 object-contain"
                          style={{ aspectRatio: videoAspectRatios[trend.id] || mediaAspectRatio(trend.generation_settings?.ratio) }}
                        />
                      ) : null}
                      {!posterUrl && videoPreviewFailed[trend.id] ? (
                        <div
                          className="absolute inset-0 flex items-center justify-center bg-secondary/70 text-gold"
                          style={{ aspectRatio: videoAspectRatios[trend.id] || mediaAspectRatio(trend.generation_settings?.ratio) }}
                        >
                          <Sparkles className="h-8 w-8" />
                        </div>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => setPreviewTrend(trend)}
                        aria-label={`Открыть промо-видео ${trend.title} крупно`}
                        className="absolute right-2 top-2 grid h-9 w-9 place-items-center rounded-full bg-black/60 text-white backdrop-blur"
                      >
                        <Film className="h-4 w-4" />
                      </button>
                    </div>
                  ) : (
                    <img src={normalizeMiniAppMediaUrl(trend.preview_url)} alt={trend.title} loading="lazy" className="h-auto max-h-[420px] w-full object-contain" />
                  ) : (
                    <div className={videoSection ? 'flex aspect-video items-center justify-center' : 'flex aspect-square items-center justify-center'}><Sparkles className="h-8 w-8 text-gold" /></div>
                  )}
                </div>
                <div className="space-y-2.5 p-3">
                  <div><h4 className="line-clamp-2 text-sm font-semibold text-foreground">{trend.title}</h4>{trend.description ? <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{trend.description}</p> : null}</div>
                  <div className="truncate rounded-lg bg-secondary/55 px-2 py-1.5 text-[10px] text-muted-foreground">{modelLabel || trend.model}</div>
                  <Button type="button" size="sm" className="w-full bg-gold text-primary-foreground hover:bg-gold/90" onClick={() => applyTrend(trend)}><Repeat2 className="h-3.5 w-3.5" />Повторить</Button>
                  <div className={isAdmin ? 'grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] gap-2' : 'grid'}>
                    <Button type="button" size="sm" variant="secondary" onClick={() => void handleCopyLink(trend)}>{copiedId === trend.id ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}{copiedId === trend.id ? 'Скопировано' : 'Ссылка'}</Button>
                    {isAdmin ? <Button type="button" variant="secondary" size="sm" className="min-w-0 px-2 text-xs" onClick={() => openEditTrend(trend)} aria-label="Редактировать тренд"><Pencil className="h-3.5 w-3.5" /><span className="truncate">Редактировать</span></Button> : null}
                    {isAdmin ? <Button type="button" variant="secondary" size="icon" onClick={() => void handleRemove(trend)} disabled={removingId === trend.id} aria-label="Убрать тренд">{removingId === trend.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}</Button> : null}
                  </div>
                </div>
              </article>
            )
          })}
        </div>
      </section>
    )
  }

  return (
    <div className="space-y-5 px-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Flame className="h-5 w-5 text-gold" />
            <h2 className="font-serif text-xl font-semibold text-foreground">Тренды</h2>
          </div>
          <p className="mt-1 max-w-xl text-sm text-muted-foreground">
            Готовые фото- и видео-шаблоны от команды NEUROMIX.
          </p>
        </div>
        {isAdmin ? (
          <Button
            type="button"
            size="sm"
            className="shrink-0 bg-gold text-primary-foreground hover:bg-gold/90"
            onClick={() => setIsCreateOpen((value) => !value)}
          >
            {isCreateOpen ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
            {isCreateOpen ? 'Закрыть' : 'Добавить'}
          </Button>
        ) : null}
      </div>

      {isAdmin && isCreateOpen ? (
        <section className="glass space-y-4 rounded-2xl border border-gold/25 p-4">
          <div>
            <p className="text-sm font-semibold text-foreground">Новый тренд</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Пользователи увидят обложку или промо-видео и описание, но не увидят скрытый prompt.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => changeTrendKind('image')}
              className={`rounded-xl border px-3 py-3 text-sm font-medium transition ${
                trendKind === 'image'
                  ? 'border-gold/50 bg-gold/15 text-gold'
                  : 'border-border/50 bg-secondary/40 text-muted-foreground'
              }`}
            >
              Фото-тренд
            </button>
            <button
              type="button"
              onClick={() => changeTrendKind('video')}
              className={`rounded-xl border px-3 py-3 text-sm font-medium transition ${
                trendKind === 'video'
                  ? 'border-gold/50 bg-gold/15 text-gold'
                  : 'border-border/50 bg-secondary/40 text-muted-foreground'
              }`}
            >
              Видео-тренд
            </button>
          </div>

          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Название тренда"
            maxLength={80}
            className="h-11 w-full rounded-xl border border-border/50 bg-secondary/50 px-3 text-sm outline-none focus:border-gold/50"
          />

          <Textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={
              trendKind === 'video'
                ? 'Что получится и какие исходники нужны'
                : 'Что получится и какое фото лучше загрузить'
            }
            className="min-h-[76px] resize-none bg-secondary/50"
            maxLength={240}
          />

          <label className="block space-y-2">
            <span className="text-xs font-medium text-muted-foreground">
              {trendKind === 'video' ? 'Видео-нейросеть' : 'Нейросеть для фото'}
            </span>
            <select
              value={model}
              onChange={(event) => setModel(event.target.value)}
              className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground outline-none focus:border-gold/50"
            >
              {availableModels.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label.replace('🔥 НОВИНКА', '').trim()}
                </option>
              ))}
            </select>
          </label>

          {trendKind === 'video' ? (
            <div className="grid grid-cols-2 gap-3">
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Формат</span>
                <select value={trendRatio} onChange={(event) => setTrendRatio(event.target.value)} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {(selectedTrendVideoModel?.ratios || ['16:9']).map((ratio) => (
                    <option key={ratio} value={ratio}>{ratio}</option>
                  ))}
                </select>
              </label>
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Длительность</span>
                <select value={videoDuration} onChange={(event) => setVideoDuration(Number(event.target.value))} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {(selectedTrendVideoModel?.durations || [5]).map((duration) => (
                    <option key={duration} value={duration}>{duration} сек</option>
                  ))}
                </select>
              </label>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Формат</span>
                <select value={trendRatio} onChange={(event) => setTrendRatio(event.target.value)} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {(selectedTrendImageModel?.ratios || ['1:1']).map((ratio) => (
                    <option key={ratio} value={ratio}>{ratio}</option>
                  ))}
                </select>
              </label>
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Качество</span>
                <select value={imageQuality} onChange={(event) => setImageQuality(event.target.value)} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {trendImageQualities.map((quality) => (
                    <option key={quality} value={quality}>{quality}</option>
                  ))}
                </select>
              </label>
            </div>
          )}

          <div className="space-y-3">
            <div>
              <span className="text-xs font-medium text-muted-foreground">Промо / превью карточки</span>
              <p className="mt-1 text-xs text-muted-foreground">Это отдельный медиа-пример. Фото-тренд может иметь видео-инструкцию «как пользоваться режимом».</p>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => changePreviewKind('image')}
                className={`rounded-xl border px-3 py-2.5 text-xs font-medium transition ${previewKind === 'image' ? 'border-gold/50 bg-gold/15 text-gold' : 'border-border/50 bg-secondary/40 text-muted-foreground'}`}
              >
                Фото-обложка
              </button>
              <button
                type="button"
                onClick={() => changePreviewKind('video')}
                className={`rounded-xl border px-3 py-2.5 text-xs font-medium transition ${previewKind === 'video' ? 'border-gold/50 bg-gold/15 text-gold' : 'border-border/50 bg-secondary/40 text-muted-foreground'}`}
              >
                Промо-видео
              </button>
            </div>

            {previewUrl ? (
              <div className="relative overflow-hidden rounded-2xl border border-border/50 bg-secondary/40">
                {previewKind === 'video' ? (
                  <video
                    src={previewUrl}
                    controls
                    data-audio-enabled="true"
                    loop
                    playsInline
                    preload="metadata"
                    className="h-auto max-h-[70vh] w-full bg-black object-contain"
                  />
                ) : (
                  <img
                    src={previewUrl}
                    alt="Preview тренда"
                    className="h-auto max-h-[70vh] w-full object-contain"
                  />
                )}
                <button
                  type="button"
                  onClick={() => {
                    setPreviewUrl('')
                    if (fileInputRef.current) fileInputRef.current.value = ''
                  }}
                  className="absolute right-2 top-2 rounded-full bg-background/80 p-2 text-foreground backdrop-blur"
                  aria-label="Удалить preview"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <div className="relative flex aspect-[16/9] w-full flex-col items-center justify-center gap-2 overflow-hidden rounded-2xl border border-dashed border-border/70 bg-secondary/35 p-4 text-sm text-muted-foreground transition-colors hover:border-gold/40 hover:text-foreground">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={previewKind === 'video' ? 'video/mp4,video/webm,video/quicktime' : 'image/jpeg,image/png,image/webp,image/avif'}
                  className="relative z-10 block w-full cursor-pointer rounded-lg border border-border/60 bg-background/80 px-3 py-2 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-60 file:mr-3 file:rounded-md file:border-0 file:bg-gold file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground"
                  disabled={uploadingPreview}
                  onChange={(event) => void handlePreviewUpload(event.target.files?.[0])}
                />
                {uploadingPreview ? (
                  <Loader2 className="h-6 w-6 animate-spin" />
                ) : previewKind === 'video' ? (
                  <Film className="h-7 w-7" />
                ) : (
                  <ImagePlus className="h-7 w-7" />
                )}
                {uploadingPreview ? 'Загружаю…' : previewKind === 'video' ? 'Загрузить промо-видео' : 'Загрузить обложку'}
              </div>
            )}
            {uploadingPreview ? (
              <p className="text-xs text-muted-foreground">Сохраняю preview на сервере. Не закрывайте mini app до завершения.</p>
            ) : null}
          </div>

          <div className="space-y-3 rounded-2xl border border-border/50 bg-secondary/25 p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold text-foreground">Поля пользователя</p>
                <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                  Необязательно. Пользователь заполнит их перед генерацией, а скрытый prompt останется закрытым.
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={userFields.length >= 6}
                onClick={addUserField}
              >
                <Plus className="h-3.5 w-3.5" />
                Поле
              </Button>
            </div>

            {userFields.length ? (
              <div className="space-y-3">
                {userFields.map((field, index) => (
                  <div key={index} className="space-y-2 rounded-xl border border-border/50 bg-background/45 p-3">
                    <div className="grid grid-cols-[minmax(0,1fr)_110px_auto] gap-2">
                      <input
                        value={field.label}
                        onChange={(event) => {
                          const label = event.target.value.slice(0, 48)
                          updateUserField(index, { label, key: label })
                        }}
                        placeholder="Например: Возраст"
                        className="h-10 min-w-0 rounded-lg border border-border/60 bg-secondary/50 px-3 text-sm text-foreground outline-none focus:border-gold/50"
                      />
                      <select
                        value={field.type}
                        onChange={(event) => {
                          const type = event.target.value as 'text' | 'number'
                          updateUserField(index,
                            type === 'number'
                              ? { type, min: 1, max: 120, placeholder: field.placeholder || '28', max_length: undefined }
                              : { type, min: undefined, max: undefined, max_length: 80 },
                          )
                        }}
                        className="h-10 rounded-lg border border-border/60 bg-secondary/50 px-2 text-xs text-foreground"
                      >
                        <option value="text">Текст</option>
                        <option value="number">Число</option>
                      </select>
                      <button
                        type="button"
                        onClick={() => removeUserField(index)}
                        className="flex h-10 w-10 items-center justify-center rounded-lg border border-border/60 bg-secondary/40 text-muted-foreground hover:text-destructive"
                        aria-label={`Удалить поле ${field.label || index + 1}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>

                    {field.type === 'number' ? (
                      <div className="grid grid-cols-3 gap-2">
                        <input
                          type="number"
                          value={field.min ?? ''}
                          onChange={(event) => updateUserField(index, { min: event.target.value === '' ? undefined : Number(event.target.value) })}
                          placeholder="Мин."
                          className="h-9 rounded-lg border border-border/60 bg-secondary/40 px-2 text-xs"
                        />
                        <input
                          type="number"
                          value={field.max ?? ''}
                          onChange={(event) => updateUserField(index, { max: event.target.value === '' ? undefined : Number(event.target.value) })}
                          placeholder="Макс."
                          className="h-9 rounded-lg border border-border/60 bg-secondary/40 px-2 text-xs"
                        />
                        <input
                          value={field.placeholder || ''}
                          onChange={(event) => updateUserField(index, { placeholder: event.target.value.slice(0, 80) })}
                          placeholder="Пример: 28"
                          className="h-9 rounded-lg border border-border/60 bg-secondary/40 px-2 text-xs"
                        />
                      </div>
                    ) : (
                      <input
                        value={field.placeholder || ''}
                        onChange={(event) => updateUserField(index, { placeholder: event.target.value.slice(0, 80) })}
                        placeholder="Подсказка в поле, например: Анна"
                        className="h-9 w-full rounded-lg border border-border/60 bg-secondary/40 px-2 text-xs"
                      />
                    )}

                    <p className="text-[10px] text-muted-foreground">
                      В скрытом prompt используйте <code className="text-gold">{`{{${field.label.trim() || 'Название'}}}`}</code>
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[11px] text-muted-foreground">
                Для обычного тренда ничего добавлять не нужно. Для birthday-шаблона добавьте поле «Возраст».
              </p>
            )}
          </div>

          <Textarea
            value={promptText}
            onChange={(event) => setPromptText(event.target.value)}
            placeholder="Скрытый prompt, который подставится при повторе"
            className="min-h-[150px] resize-none bg-secondary/50"
          />

          <Button
            type="button"
            className="w-full bg-gold text-primary-foreground hover:bg-gold/90"
            disabled={submitting || uploadingPreview}
            onClick={() => void handleCreate()}
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            Опубликовать тренд
          </Button>
        </section>
      ) : null}

      {error ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex justify-center py-12 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : items.length ? (
        <div className="space-y-7">
          {renderTrendGrid(photoTrends, '🖼 Фото-тренды', false)}
          {renderTrendGrid(videoTrends, '🎬 Видео-тренды', true)}
        </div>
      ) : (
        <div className="glass rounded-2xl border border-border/50 p-8 text-center">
          <Flame className="mx-auto h-9 w-9 text-gold/70" />
          <p className="mt-3 text-sm font-medium text-foreground">Трендов пока нет</p>
          <p className="mt-1 text-xs text-muted-foreground">{isAdmin ? 'Нажмите «Добавить», чтобы опубликовать первый шаблон.' : 'Команда NEUROMIX скоро добавит новые шаблоны.'}</p>
        </div>
      )}

      <TrendRunnerDialog
        trend={trendToRun}
        open={Boolean(trendToRun)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setTrendToRun(null)
        }}
      />

      <Dialog open={Boolean(editingTrend)} onOpenChange={(open) => {
        if (!open && !uploadingEditPreview && !savingEdit) {
          setEditingTrend(null)
          setEditPreviewUrl('')
          if (editFileInputRef.current) editFileInputRef.current.value = ''
        }
      }}>
        <DialogContent className="max-w-lg space-y-4 border-border/60 bg-background p-4">
          <DialogTitle className="pr-8 text-sm">Редактировать</DialogTitle>
          {editingTrend ? (
            <div className="space-y-4">
              <div>
                <p className="line-clamp-2 text-sm font-semibold text-foreground">{editingTrend.title}</p>
                <p className="mt-1 text-xs text-muted-foreground">Загрузите новый preview. Тип фото/видео сохранится вместе с трендом.</p>
              </div>

              <div className="space-y-2">
                {(editPreviewUrl || editingTrend.preview_url) ? (
                  <div className="overflow-hidden rounded-2xl border border-border/50 bg-secondary/40">
                    {previewKindForTrend(editingTrend, isVideoTrend(editingTrend)) === 'video' ? (
                      <video
                        src={normalizeMiniAppMediaUrl(editPreviewUrl || editingTrend.preview_url || '')}
                        controls
                        data-audio-enabled="true"
                        playsInline
                        preload="metadata"
                        className="h-auto max-h-[58vh] w-full bg-black object-contain"
                      />
                    ) : (
                      <img
                        src={normalizeMiniAppMediaUrl(editPreviewUrl || editingTrend.preview_url || '')}
                        alt={editingTrend.title}
                        className="aspect-square w-full object-cover"
                      />
                    )}
                  </div>
                ) : null}

                <input
                  ref={editFileInputRef}
                  type="file"
                  accept="image/jpeg,image/png,image/webp,image/avif,video/mp4,video/webm,video/quicktime"
                  className="block w-full cursor-pointer rounded-lg border border-border/60 bg-background/80 px-3 py-2 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-60 file:mr-3 file:rounded-md file:border-0 file:bg-gold file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground"
                  disabled={uploadingEditPreview || savingEdit}
                  onChange={(event) => void handleEditPreviewUpload(event.target.files?.[0])}
                />
                {uploadingEditPreview ? (
                  <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />Загружаю и сохраняю preview…</p>
                ) : null}
              </div>

              <Button
                type="button"
                className="w-full bg-gold text-primary-foreground hover:bg-gold/90"
                disabled={uploadingEditPreview || savingEdit || !editPreviewUrl}
                onClick={() => void handleSaveEdit()}
              >
                {savingEdit ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                Готово
              </Button>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(previewTrend)} onOpenChange={(open) => { if (!open) setPreviewTrend(null) }}>
        <DialogContent className="max-w-3xl border-border/60 bg-background p-3">
          <DialogTitle className="pr-8 text-sm">{previewTrend?.title || 'Промо-видео'}</DialogTitle>
          {previewTrend?.preview_url ? (
            <video
              src={normalizeMiniAppMediaUrl(previewTrend.preview_url)}
              poster={previewTrend.preview_poster_url ? normalizeMiniAppMediaUrl(previewTrend.preview_poster_url) : undefined}
              controls
              data-audio-enabled="true"
              loop
              playsInline
              onLoadedMetadata={(event) => rememberVideoAspectRatio(previewTrend.id, event.currentTarget)}
              style={{ aspectRatio: videoAspectRatios[previewTrend.id] || mediaAspectRatio(previewTrend.generation_settings?.ratio) }}
              className="mx-auto max-h-[78vh] max-w-full rounded-xl bg-black object-contain"
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}
