'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ImagePlus,
  Link2,
  Loader2,
  RefreshCcw,
  Ruler,
  Sparkles,
  Weight,
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
  const [pinterestUrl, setPinterestUrl] = useState('')
  const [resolvingPinterest, setResolvingPinterest] = useState(false)
  const [heightCm, setHeightCm] = useState('')
  const [weightKg, setWeightKg] = useState('')

  const pinterestRepeat = isPinterestRepeatItem(trend)
  const busy = phase === 'uploading' || phase === 'generating' || resolvingPinterest
  const isVideoTrend = trend?.generation_settings?.kind === 'video'
  const configuredReferenceCount = Number(trend?.generation_settings?.reference_count || 0)
  const exactReferenceCount = Number.isFinite(configuredReferenceCount) && configuredReferenceCount > 0
    ? Math.min(MAX_REFERENCES, Math.trunc(configuredReferenceCount))
    : pinterestRepeat
      ? 2
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
  const readyToGenerate = exactSlots
    ? completedReferences.length === exactReferenceCount
    : completedReferences.length > 0

  const clearPreviews = useCallback(() => {
    for (const previewUrl of previewRefs.current) {
      if (previewUrl.startsWith('blob:')) URL.revokeObjectURL(previewUrl)
    }
    previewRefs.current = []
    setPreviewUrls([])
  }, [])

  const resetRunner = useCallback(() => {
    setPhase('idle')
    setError(null)
    setPinterestUrl('')
    setResolvingPinterest(false)
    setHeightCm('')
    setWeightKg('')
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
  }, [exactReferenceCount, exactSlots, open, resetRunner, trend?.id])

  useEffect(() => clearPreviews, [clearPreviews])

  const validateImage = (file: File) => {
    const extension = file.name.split('.').pop()?.toLowerCase() || ''
    return file.type.startsWith('image/') || IMAGE_EXTENSIONS.has(extension)
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
      const referenceUrls = completedReferences.map((reference) => reference.url)
      const result = pinterestRepeat
        ? await runPinterestRepeatTrend(trend.id, referenceUrls, {
            heightCm: parseOptionalNumber(heightCm),
            weightKg: parseOptionalNumber(weightKg),
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
        <p className="px-1 text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground">
          {label}
        </p>
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
      <DialogContent className="max-w-lg border-border/60 bg-background p-4">
        <DialogTitle className="pr-8 font-serif text-lg">
          {pinterestRepeat ? 'Повтори фото с Pinterest' : trend?.title || 'Повторить тренд'}
        </DialogTitle>

        {trend?.preview_url ? (
          isVideoTrend ? (
            <video
              src={videoPreviewFrameUrl(trend.preview_url)}
              muted
              loop
              autoPlay
              controls
              playsInline
              preload="metadata"
              style={{ aspectRatio: mediaAspectRatio(trend.generation_settings?.ratio) }}
              className="mx-auto max-h-[38vh] max-w-full rounded-2xl bg-black object-contain"
            />
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
              <p className="text-xs font-semibold text-foreground">🔐 Как получить идеальное фото?</p>
              <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                Ищи понравившийся кадр в Pinterest. Мы возьмём из него сцену, свет и позу, а внешность — из твоего фото.
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
                  <Link2 className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
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
            </div>

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
                    className="h-11 w-full rounded-xl border border-border/70 bg-secondary/25 px-3 pr-9 text-base outline-none transition focus:border-gold/60"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">кг</span>
                </div>
              </label>
            </div>
            <p className="-mt-1 text-[10px] leading-relaxed text-muted-foreground">
              Рост и вес нужны, чтобы масштаб тела и пропорции результата совпадали с тобой.
            </p>

            {readyToGenerate ? (
              <div className="rounded-2xl border border-border/60 bg-secondary/20 p-3">
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">Источник</p>
                <div className="mt-2 flex items-center gap-2">
                  {previewUrls.slice(0, 2).map((url, index) => url ? (
                    <img
                      key={`${url}-${index}`}
                      src={url}
                      alt={index === 0 ? 'Референс' : 'Вы'}
                      className="h-9 w-9 rounded-full border border-border/60 object-cover"
                    />
                  ) : null)}
                  {pinterestUrl ? (
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium text-foreground">Pinterest</p>
                      <p className="truncate text-[10px] text-muted-foreground">{pinterestUrl}</p>
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">Референс загружен с устройства</p>
                  )}
                </div>
                <div className="mt-3 space-y-1 text-[11px] text-muted-foreground">
                  <p><span className="text-emerald-500">●</span> сцена, свет и поза считаются с референса</p>
                  <p><span className="text-emerald-500">●</span> лицо и внешность берутся только с твоего фото</p>
                </div>
              </div>
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
