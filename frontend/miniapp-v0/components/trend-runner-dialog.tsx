'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ImagePlus,
  Link2,
  Loader2,
  Plus,
  RefreshCcw,
  Ruler,
  Sparkles,
  Weight,
  X,
} from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { uploadFile } from '@/lib/api'
import {
  resolvePinterestReference,
  runPinterestRepeatTrend,
  runTrend,
} from '@/lib/trend-api'
import { mediaAspectRatio, normalizeMiniAppMediaUrl, videoPreviewFrameUrl } from '@/lib/media-url'
import type { PromptItem, UploadedFile } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'

type RunnerPhase = 'idle' | 'uploading' | 'generating' | 'error'

interface TrendRunnerDialogProps {
  trend: PromptItem | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif', 'avif'])
const MAX_REFERENCES = 12
const MAX_PINTEREST_ANGLES = 5
const DEFAULT_TWO_PHOTO_LABELS = ['РЕФЕРЕНС', 'ТЫ']

function isPinterestRepeatItem(trend: PromptItem | null): boolean {
  if (!trend) return false
  const tags = new Set((trend.tags || []).map((tag) => String(tag || '').trim().toLowerCase()))
  const title = String(trend.title || '').toLowerCase()
  return (
    tags.has('pinterest') ||
    tags.has('pinterest-repeat') ||
    tags.has('repeat-pinterest') ||
    title.includes('pinterest')
  )
}

function parseOptionalNumber(value: string): number | null {
  const normalized = value.trim()
  if (!normalized) return null
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? Math.trunc(parsed) : null
}

export function TrendRunnerDialog({
  trend,
  open,
  onOpenChange,
}: TrendRunnerDialogProps) {
  const {
    addTask,
    setCredits,
    setTaskDetail,
    selectTask,
    addSavedReference,
  } = useApp()
  const inputRefs = useRef<Array<HTMLInputElement | null>>([])
  const previewRefs = useRef<string[]>([])
  const [phase, setPhase] = useState<RunnerPhase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [previewUrls, setPreviewUrls] = useState<Array<string | null>>([])
  const [uploadedReferences, setUploadedReferences] = useState<Array<UploadedFile | null>>([])
  const [identityAngles, setIdentityAngles] = useState<UploadedFile[]>([])
  const [identityAnglePreviews, setIdentityAnglePreviews] = useState<string[]>([])
  const [pinterestUrl, setPinterestUrl] = useState('')
  const [resolvingPinterest, setResolvingPinterest] = useState(false)
  const [heightCm, setHeightCm] = useState('')
  const [weightKg, setWeightKg] = useState('')
  const [trendPreviewFailed, setTrendPreviewFailed] = useState(false)

  const pinterestRepeat = isPinterestRepeatItem(trend)
  const busy = phase === 'uploading' || phase === 'generating' || resolvingPinterest
  const isVideoTrend = trend?.generation_settings?.kind === 'video'
  const configuredReferenceCount = Number(trend?.generation_settings?.reference_count || 0)
  const exactReferenceCount = pinterestRepeat
    ? 2
    : Number.isFinite(configuredReferenceCount) && configuredReferenceCount > 0
      ? Math.min(MAX_REFERENCES, Math.trunc(configuredReferenceCount))
      : 0
  const exactSlots = exactReferenceCount > 0
  const referenceLabels = exactSlots
    ? Array.from({ length: exactReferenceCount }, (_, index) =>
        pinterestRepeat
          ? DEFAULT_TWO_PHOTO_LABELS[index] || `ФОТО ${index + 1}`
          : trend?.generation_settings?.reference_labels?.[index]?.trim() ||
            (exactReferenceCount === 2 ? DEFAULT_TWO_PHOTO_LABELS[index] : `Фото ${index + 1}`),
      )
    : []
  const completedReferences = uploadedReferences.filter(
    (reference): reference is UploadedFile => Boolean(reference),
  )
  const parsedHeight = parseOptionalNumber(heightCm)
  const parsedWeight = parseOptionalNumber(weightKg)
  const validHeight = parsedHeight !== null && parsedHeight >= 120 && parsedHeight <= 230
  const validWeight = parsedWeight !== null && parsedWeight >= 30 && parsedWeight <= 250
  const pinterestPrimaryReady = Boolean(uploadedReferences[0] && uploadedReferences[1])
  const readyToGenerate = pinterestRepeat
    ? pinterestPrimaryReady && validHeight && validWeight
    : exactSlots
      ? completedReferences.length === exactReferenceCount
      : completedReferences.length > 0

  const clearPreviews = useCallback(() => {
    for (const previewUrl of previewRefs.current) {
      if (previewUrl.startsWith('blob:')) URL.revokeObjectURL(previewUrl)
    }
    previewRefs.current = []
    setPreviewUrls([])
    setIdentityAnglePreviews([])
  }, [])

  const resetRunner = useCallback(() => {
    setPhase('idle')
    setError(null)
    setPinterestUrl('')
    setResolvingPinterest(false)
    setHeightCm('')
    setWeightKg('')
    setIdentityAngles([])
    setTrendPreviewFailed(false)
    clearPreviews()
    setUploadedReferences(exactSlots ? Array(exactReferenceCount).fill(null) : [])
    setPreviewUrls(exactSlots ? Array(exactReferenceCount).fill(null) : [])
    for (const input of inputRefs.current) {
      if (input) input.value = ''
    }
  }, [clearPreviews, exactReferenceCount, exactSlots])

  useEffect(() => {
    if (!open) {
      resetRunner()
      return
    }
    setUploadedReferences(exactSlots ? Array(exactReferenceCount).fill(null) : [])
    setPreviewUrls(exactSlots ? Array(exactReferenceCount).fill(null) : [])
    setIdentityAngles([])
    setIdentityAnglePreviews([])
  }, [exactReferenceCount, exactSlots, open, resetRunner, trend?.id])

  useEffect(() => {
    setTrendPreviewFailed(false)
  }, [trend?.id])

  useEffect(() => clearPreviews, [clearPreviews])

  const validateImage = (file: File) => {
    const extension = file.name.split('.').pop()?.toLowerCase() || ''
    return file.type.startsWith('image/') || IMAGE_EXTENSIONS.has(extension)
  }

  const removePrimaryReference = (slotIndex: number) => {
    if (busy) return
    const preview = previewUrls[slotIndex]
    if (preview?.startsWith('blob:')) URL.revokeObjectURL(preview)
    previewRefs.current = previewRefs.current.filter((url) => url !== preview)
    setPreviewUrls((current) => {
      const next = [...current]
      next[slotIndex] = null
      return next
    })
    setUploadedReferences((current) => {
      const next = [...current]
      next[slotIndex] = null
      return next
    })
    if (slotIndex === 0) setPinterestUrl('')
    setError(null)
    setPhase('idle')
  }

  const uploadIntoSlot = async (slotIndex: number, file: File) => {
    if (!trend || busy) return
    if (!validateImage(file)) {
      setPhase('error')
      setError(`Файл «${file.name}» не является изображением`)
      return
    }

    const localPreview = URL.createObjectURL(file)
    const previousPreview = previewUrls[slotIndex]
    if (previousPreview?.startsWith('blob:')) URL.revokeObjectURL(previousPreview)
    previewRefs.current = previewRefs.current.filter((url) => url !== previousPreview)
    previewRefs.current.push(localPreview)
    setPreviewUrls((current) => {
      const next = [...current]
      next[slotIndex] = localPreview
      return next
    })
    if (pinterestRepeat && slotIndex === 0) setPinterestUrl('')
    setError(null)
    setPhase('uploading')

    try {
      const uploaded = await uploadFile('image_reference', file)
      addSavedReference(uploaded)
      setUploadedReferences((current) => {
        const next = [...current]
        next[slotIndex] = uploaded
        return next
      })
      setPhase('idle')
    } catch (cause) {
      URL.revokeObjectURL(localPreview)
      previewRefs.current = previewRefs.current.filter((url) => url !== localPreview)
      setPreviewUrls((current) => {
        const next = [...current]
        next[slotIndex] = null
        return next
      })
      setUploadedReferences((current) => {
        const next = [...current]
        next[slotIndex] = null
        return next
      })
      setPhase('error')
      setError(cause instanceof Error ? cause.message : 'Не удалось загрузить фото')
    }
  }

  const handlePhotos = async (selectedFiles: File[]) => {
    if (!trend || busy || !selectedFiles.length) return
    if (completedReferences.length + selectedFiles.length > MAX_REFERENCES) {
      setPhase('error')
      setError(`Можно загрузить максимум ${MAX_REFERENCES} фото`)
      return
    }

    const invalidFile = selectedFiles.find((file) => !validateImage(file))
    if (invalidFile) {
      setPhase('error')
      setError(`Файл «${invalidFile.name}» не является изображением`)
      return
    }

    const localPreviews = selectedFiles.map((file) => URL.createObjectURL(file))
    previewRefs.current = [...previewRefs.current, ...localPreviews]
    setPreviewUrls((current) => [...current, ...localPreviews])
    setError(null)
    setPhase('uploading')

    try {
      const uploaded = await Promise.all(
        selectedFiles.map((file) => uploadFile('image_reference', file)),
      )
      for (const reference of uploaded) addSavedReference(reference)
      setUploadedReferences((current) => [...current, ...uploaded])
      setPhase('idle')
    } catch (cause) {
      for (const previewUrl of localPreviews) URL.revokeObjectURL(previewUrl)
      previewRefs.current = previewRefs.current.filter((url) => !localPreviews.includes(url))
      setPreviewUrls((current) => current.filter((url) => !url || !localPreviews.includes(url)))
      setPhase('error')
      setError(cause instanceof Error ? cause.message : 'Не удалось загрузить фото')
    }
  }

  const uploadPinterestAngles = async (selectedFiles: File[]) => {
    if (!trend || busy || !selectedFiles.length) return
    if (identityAngles.length + selectedFiles.length > MAX_PINTEREST_ANGLES) {
      setPhase('error')
      setError(`Можно добавить максимум ${MAX_PINTEREST_ANGLES} дополнительных ракурсов`)
      return
    }
    const invalidFile = selectedFiles.find((file) => !validateImage(file))
    if (invalidFile) {
      setPhase('error')
      setError(`Файл «${invalidFile.name}» не является изображением`)
      return
    }

    const localPreviews = selectedFiles.map((file) => URL.createObjectURL(file))
    previewRefs.current = [...previewRefs.current, ...localPreviews]
    setIdentityAnglePreviews((current) => [...current, ...localPreviews])
    setError(null)
    setPhase('uploading')

    try {
      const uploaded = await Promise.all(
        selectedFiles.map((file) => uploadFile('image_reference', file)),
      )
      for (const reference of uploaded) addSavedReference(reference)
      setIdentityAngles((current) => [...current, ...uploaded])
      setPhase('idle')
    } catch (cause) {
      for (const previewUrl of localPreviews) URL.revokeObjectURL(previewUrl)
      previewRefs.current = previewRefs.current.filter((url) => !localPreviews.includes(url))
      setIdentityAnglePreviews((current) => current.filter((url) => !localPreviews.includes(url)))
      setPhase('error')
      setError(cause instanceof Error ? cause.message : 'Не удалось загрузить дополнительные ракурсы')
    }
  }

  const removeIdentityAngle = (index: number) => {
    if (busy) return
    const preview = identityAnglePreviews[index]
    if (preview?.startsWith('blob:')) URL.revokeObjectURL(preview)
    previewRefs.current = previewRefs.current.filter((url) => url !== preview)
    setIdentityAnglePreviews((current) => current.filter((_, itemIndex) => itemIndex !== index))
    setIdentityAngles((current) => current.filter((_, itemIndex) => itemIndex !== index))
  }

  const handlePinterestUrl = async () => {
    if (!pinterestRepeat || busy || !pinterestUrl.trim()) return
    setError(null)
    setResolvingPinterest(true)
    try {
      const resolved = await resolvePinterestReference(pinterestUrl)
      const previousPreview = previewUrls[0]
      if (previousPreview?.startsWith('blob:')) URL.revokeObjectURL(previousPreview)
      previewRefs.current = previewRefs.current.filter((url) => url !== previousPreview)
      setPreviewUrls((current) => {
        const next = [...current]
        next[0] = resolved.image_url
        return next
      })
      setUploadedReferences((current) => {
        const next = [...current]
        next[0] = {
          id: `pinterest:${resolved.image_url}`,
          name: 'Pinterest reference',
          url: resolved.image_url,
          preview_url: resolved.image_url,
          type: 'image',
          size: 0,
          source: 'pinterest',
        }
        return next
      })
      setPinterestUrl(resolved.source_url)
      setPhase('idle')
    } catch (cause) {
      setPhase('error')
      setError(cause instanceof Error ? cause.message : 'Не удалось загрузить фото из Pinterest')
    } finally {
      setResolvingPinterest(false)
    }
  }

  const handleGenerate = async () => {
    if (!trend || busy || !readyToGenerate) return
    setError(null)
    setPhase('generating')
    try {
      const referenceUrls = pinterestRepeat
        ? [
            uploadedReferences[0]?.url || '',
            uploadedReferences[1]?.url || '',
            ...identityAngles.map((reference) => reference.url),
          ].filter(Boolean)
        : completedReferences.map((reference) => reference.url)
      const result = pinterestRepeat
        ? await runPinterestRepeatTrend(trend.id, referenceUrls, {
            heightCm: parseOptionalNumber(heightCm) as number,
            weightKg: parseOptionalNumber(weightKg) as number,
          })
        : await runTrend(trend.id, referenceUrls)
      addTask(result.task)
      setCredits(result.credits)
      if (result.detail) setTaskDetail(result.detail)
      selectTask(result.task)
      onOpenChange(false)
    } catch (cause) {
      setPhase('error')
      setError(cause instanceof Error ? cause.message : 'Не удалось запустить тренд')
    }
  }

  const renderExactSlot = (label: string, index: number) => {
    const previewUrl = previewUrls[index]
    const uploaded = uploadedReferences[index]
    return (
      <div key={`${label}-${index}`} className="space-y-1.5">
        <div className="flex items-center gap-1.5 px-1">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground">
            {label}
          </p>
          {pinterestRepeat ? (
            <span className="rounded-full bg-violet-500/10 px-1.5 py-0.5 text-[9px] font-semibold text-violet-500">
              {index === 0 ? 'откуда' : 'кого вставляем'}
            </span>
          ) : null}
        </div>
        <div className="relative">
          <label className="relative flex min-h-44 cursor-pointer flex-col overflow-hidden rounded-2xl border border-dashed border-border/70 bg-secondary/35 text-sm transition hover:border-gold/50">
            <input
              ref={(node) => { inputRefs.current[index] = node }}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif,image/avif"
              className="absolute inset-0 z-20 cursor-pointer opacity-0"
              disabled={busy}
              onChange={(event) => {
                const file = event.currentTarget.files?.[0]
                event.currentTarget.value = ''
                if (file) void uploadIntoSlot(index, file)
              }}
            />
            {previewUrl ? (
              <img src={previewUrl} alt={label} className="h-36 w-full object-cover" />
            ) : (
              <div className="flex h-36 flex-col items-center justify-center gap-2 text-muted-foreground">
                {phase === 'uploading' ? (
                  <Loader2 className="h-7 w-7 animate-spin text-gold" />
                ) : (
                  <ImagePlus className="h-7 w-7 text-gold" />
                )}
                <span className="text-xs font-medium">Загрузить</span>
              </div>
            )}
            <div className="flex min-h-10 items-center justify-center px-2 py-2 text-center text-xs font-medium text-foreground">
              {uploaded ? 'Готово ✓' : index === 0 ? 'Фото, которое повторяем' : 'Ваше фото'}
            </div>
          </label>
          {uploaded && !busy ? (
            <button
              type="button"
              aria-label={`Удалить ${label.toLowerCase()}`}
              onClick={() => removePrimaryReference(index)}
              className="absolute right-2 top-2 z-30 flex h-8 w-8 items-center justify-center rounded-full bg-background/90 text-foreground shadow"
            >
              <X className="h-4 w-4" />
            </button>
          ) : null}
        </div>
      </div>
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!busy) onOpenChange(nextOpen)
      }}
    >
      <DialogContent className="max-h-[92vh] max-w-lg overflow-y-auto border-border/60 bg-background p-4">
        <DialogTitle className="pr-8 font-serif text-lg">
          {pinterestRepeat ? 'Повтори фото с Pinterest' : trend?.title || 'Повторить тренд'}
        </DialogTitle>

        {trend?.preview_url ? (
          isVideoTrend ? (
            <div
              style={{ aspectRatio: mediaAspectRatio(trend.generation_settings?.ratio) }}
              className="relative mx-auto max-h-[42vh] w-full max-w-full overflow-hidden rounded-2xl bg-black"
            >
              <video
                src={videoPreviewFrameUrl(trend.preview_url)}
                poster={trend.preview_poster_url ? normalizeMiniAppMediaUrl(trend.preview_poster_url) : undefined}
                muted
                loop
                autoPlay
                controls
                playsInline
                preload="metadata"
                onLoadedData={() => setTrendPreviewFailed(false)}
                onCanPlay={() => setTrendPreviewFailed(false)}
                onError={() => setTrendPreviewFailed(true)}
                className="h-full w-full object-contain"
              />
              {trendPreviewFailed && !trend.preview_poster_url ? (
                <div className="absolute inset-0 flex items-center justify-center bg-secondary/70 text-gold">
                  <Sparkles className="h-8 w-8" />
                </div>
              ) : null}
            </div>
          ) : pinterestRepeat ? null : (
            <img
              src={normalizeMiniAppMediaUrl(trend.preview_url)}
              alt={trend.title}
              className="max-h-[42vh] w-full rounded-2xl object-contain"
            />
          )
        ) : null}

        {pinterestRepeat ? (
          <>
            <div className="rounded-2xl border border-amber-300/30 bg-amber-200/10 p-3">
              <p className="text-xs font-semibold text-foreground">Как получить результат 1 в 1</p>
              <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                Слева — кадр, который повторяем. Справа — ваше основное фото. Генерация не запускается после загрузки: сначала добавьте все данные и нажмите «Создать».
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              {referenceLabels.map(renderExactSlot)}
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-3">
                <div className="h-px flex-1 bg-border/70" />
                <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                  или вставь ссылку
                </span>
                <div className="h-px flex-1 bg-border/70" />
              </div>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Link2 className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-red-500" />
                  <input
                    value={pinterestUrl}
                    onChange={(event) => setPinterestUrl(event.target.value)}
                    placeholder="Ссылка на пин с Pinterest"
                    disabled={busy}
                    className="h-10 w-full rounded-xl border border-border/70 bg-secondary/25 pl-9 pr-3 text-sm outline-none transition focus:border-gold/60"
                  />
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={busy || !pinterestUrl.trim()}
                  onClick={() => void handlePinterestUrl()}
                >
                  {resolvingPinterest ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Загрузить'}
                </Button>
              </div>
              <p className="text-[10px] leading-relaxed text-muted-foreground">
                Вставьте ссылку на пин — мы сами вытащим картинку и разберём сцену.
              </p>
            </div>

            {uploadedReferences[0] ? (
              <div className="rounded-2xl border border-border/60 bg-secondary/20 p-3">
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">Источник</p>
                <div className="mt-2 flex items-center gap-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-red-500/10 text-sm font-bold text-red-500">P</div>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-foreground">
                      {pinterestUrl ? 'Pinterest' : 'Референс с устройства'}
                    </p>
                    <p className="truncate text-[10px] text-muted-foreground">
                      {pinterestUrl || uploadedReferences[0]?.name || 'Референс загружен'}
                    </p>
                  </div>
                  <button
                    type="button"
                    aria-label="Удалить источник"
                    disabled={busy}
                    onClick={() => removePrimaryReference(0)}
                    className="flex h-7 w-7 items-center justify-center rounded-full text-muted-foreground hover:bg-secondary"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ) : null}

            {pinterestPrimaryReady ? (
              <>
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground">
                      1–5 ракурсов одного человека
                    </p>
                    <span className="text-[10px] text-muted-foreground">{identityAngles.length}/{MAX_PINTEREST_ANGLES}</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {identityAnglePreviews.map((preview, index) => (
                      <div key={`${preview}-${index}`} className="relative h-14 w-14 overflow-hidden rounded-xl border border-border/60">
                        <img src={preview} alt={`Дополнительный ракурс ${index + 1}`} className="h-full w-full object-cover" />
                        {!busy ? (
                          <button
                            type="button"
                            aria-label={`Удалить ракурс ${index + 1}`}
                            onClick={() => removeIdentityAngle(index)}
                            className="absolute right-0.5 top-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-background/90 text-foreground"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        ) : null}
                      </div>
                    ))}
                    {identityAngles.length < MAX_PINTEREST_ANGLES ? (
                      <label className="relative flex h-14 w-14 cursor-pointer items-center justify-center rounded-xl border border-dashed border-border/70 bg-secondary/25 text-muted-foreground hover:border-gold/50 hover:text-foreground">
                        <input
                          ref={(node) => { inputRefs.current[2] = node }}
                          type="file"
                          multiple
                          accept="image/jpeg,image/png,image/webp,image/heic,image/heif,image/avif"
                          className="absolute inset-0 cursor-pointer opacity-0"
                          disabled={busy}
                          onChange={(event) => {
                            const files = Array.from(event.currentTarget.files || [])
                            event.currentTarget.value = ''
                            void uploadPinterestAngles(files)
                          }}
                        />
                        {phase === 'uploading' ? (
                          <Loader2 className="h-5 w-5 animate-spin" />
                        ) : (
                          <Plus className="h-5 w-5" />
                        )}
                      </label>
                    ) : null}
                  </div>
                  <p className="text-[10px] leading-relaxed text-muted-foreground">
                    Дополнительные ракурсы необязательны, но помогают точнее сохранить лицо, волосы и пропорции.
                  </p>
                </div>

                <div className="space-y-1 text-[11px] text-muted-foreground">
                  <p><span className="text-emerald-500">●</span> сцена, свет и поза считаются с референса</p>
                  <p><span className="text-emerald-500">●</span> лицо и внешность берутся только с твоего фото</p>
                </div>
              </>
            ) : null}

            <div className="grid grid-cols-2 gap-3">
              <label className="space-y-1.5">
                <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground">
                  <Ruler className="h-3.5 w-3.5" /> Рост
                </span>
                <div className="relative">
                  <input
                    inputMode="numeric"
                    value={heightCm}
                    onChange={(event) => setHeightCm(event.target.value.replace(/[^0-9]/g, '').slice(0, 3))}
                    placeholder="165"
                    disabled={busy}
                    aria-invalid={Boolean(heightCm) && !validHeight}
                    className="h-11 w-full rounded-xl border border-border/70 bg-secondary/25 px-3 pr-9 text-base outline-none transition focus:border-gold/60"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">см</span>
                </div>
              </label>
              <label className="space-y-1.5">
                <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground">
                  <Weight className="h-3.5 w-3.5" /> Вес
                </span>
                <div className="relative">
                  <input
                    inputMode="numeric"
                    value={weightKg}
                    onChange={(event) => setWeightKg(event.target.value.replace(/[^0-9]/g, '').slice(0, 3))}
                    placeholder="55"
                    disabled={busy}
                    aria-invalid={Boolean(weightKg) && !validWeight}
                    className="h-11 w-full rounded-xl border border-border/70 bg-secondary/25 px-3 pr-9 text-base outline-none transition focus:border-gold/60"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">кг</span>
                </div>
              </label>
            </div>
            <p className="-mt-1 text-[10px] leading-relaxed text-muted-foreground">
              Рост и вес обязательны, чтобы руки, шея и пропорции тела совпали с вами.
            </p>
            {heightCm && !validHeight ? (
              <p className="text-[10px] text-destructive">Рост должен быть от 120 до 230 см.</p>
            ) : null}
            {weightKg && !validWeight ? (
              <p className="text-[10px] text-destructive">Вес должен быть от 30 до 250 кг.</p>
            ) : null}
          </>
        ) : (
          <>
            <div className="rounded-2xl border border-gold/25 bg-gold/10 p-4 text-center">
              <Sparkles className="mx-auto h-6 w-6 text-gold" />
              <p className="mt-2 text-sm font-semibold text-foreground">
                {exactSlots ? 'Добавьте фото по порядку' : 'Загрузите свои фото'}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {exactSlots
                  ? 'Заполните все слоты. Генерация не начнётся сама — после загрузки нажмите «Сгенерировать».'
                  : 'Добавьте все нужные фото — можно по одному или несколькими заходами. Генерация начнётся только после нажатия кнопки «Сгенерировать».'}
              </p>
            </div>

            {exactSlots ? (
              <div className="grid grid-cols-2 gap-3">
                {referenceLabels.map(renderExactSlot)}
              </div>
            ) : (
              <>
                {previewUrls.length ? (
                  <div className="grid max-h-64 grid-cols-2 gap-2 overflow-y-auto rounded-2xl bg-secondary/20 p-2">
                    {previewUrls.filter(Boolean).map((previewUrl, index) => (
                      <img
                        key={`${previewUrl}-${index}`}
                        src={previewUrl || ''}
                        alt={`Референс ${index + 1}`}
                        className="h-28 w-full rounded-xl object-cover"
                      />
                    ))}
                  </div>
                ) : null}

                <label className="relative flex min-h-28 cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border/70 bg-secondary/35 p-4 text-sm text-muted-foreground transition hover:border-gold/50 hover:text-foreground">
                  <input
                    ref={(node) => { inputRefs.current[0] = node }}
                    type="file"
                    multiple
                    accept="image/jpeg,image/png,image/webp,image/heic,image/heif,image/avif"
                    className="absolute inset-0 cursor-pointer opacity-0"
                    disabled={busy}
                    onChange={(event) => {
                      const files = Array.from(event.currentTarget.files || [])
                      event.currentTarget.value = ''
                      void handlePhotos(files)
                    }}
                  />
                  {busy ? (
                    <Loader2 className="h-7 w-7 animate-spin text-gold" />
                  ) : phase === 'error' ? (
                    <RefreshCcw className="h-7 w-7 text-gold" />
                  ) : (
                    <ImagePlus className="h-7 w-7 text-gold" />
                  )}
                  <span className="font-medium">
                    {phase === 'uploading'
                      ? 'Загружаю референсы…'
                      : phase === 'generating'
                        ? 'Запускаю тренд…'
                        : phase === 'error'
                          ? 'Добавить фото ещё раз'
                          : completedReferences.length
                            ? 'Добавить ещё фото'
                            : 'Выбрать фото'}
                  </span>
                  {!busy ? (
                    <span className="text-xs text-muted-foreground">
                      Выбрано {completedReferences.length} из {MAX_REFERENCES}
                    </span>
                  ) : null}
                </label>
              </>
            )}
          </>
        )}

        {error ? (
          <p className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <Button
          type="button"
          disabled={busy || !readyToGenerate}
          onClick={() => void handleGenerate()}
          className={pinterestRepeat ? 'h-12 text-base font-semibold' : undefined}
        >
          {phase === 'generating' ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : pinterestRepeat ? null : (
            <Sparkles className="h-4 w-4" />
          )}
          {phase === 'generating'
            ? 'Генерирую…'
            : pinterestRepeat
              ? 'Создать →'
              : exactSlots
                ? `Сгенерировать · ${completedReferences.length}/${exactReferenceCount}`
                : `Сгенерировать · ${completedReferences.length} фото`}
        </Button>

        {pinterestRepeat && !readyToGenerate ? (
          <p className="text-center text-[10px] text-muted-foreground">
            Для запуска нужны референс, ваше фото, рост и вес. Загрузка фото сама генерацию не запускает.
          </p>
        ) : null}

        {!pinterestRepeat ? (
          <Button
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={() => onOpenChange(false)}
          >
            Закрыть
          </Button>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
