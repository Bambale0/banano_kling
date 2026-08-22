'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { ImagePlus, Loader2, RefreshCcw, Sparkles, X } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { uploadFile } from '@/lib/api'
import { runTrend } from '@/lib/trend-api'
import { mediaAspectRatio, normalizeMiniAppMediaUrl, videoPreviewFrameUrl } from '@/lib/media-url'
import type { PromptItem, UploadedFile } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'

type RunnerPhase = 'idle' | 'uploading' | 'generating' | 'error'

type ExactTrendSettings = NonNullable<PromptItem['generation_settings']> & {
  required_reference_count?: number
  reference_hint?: string
}

interface TrendRunnerDialogProps {
  trend: PromptItem | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif', 'avif'])
const MAX_REFERENCES = 12

function requiredReferenceCount(trend: PromptItem | null): number | null {
  const settings = trend?.generation_settings as ExactTrendSettings | null | undefined
  const rawValue = Number(settings?.required_reference_count)
  if (!Number.isFinite(rawValue) || rawValue < 1) return null
  return Math.min(MAX_REFERENCES, Math.max(1, Math.trunc(rawValue)))
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
  const inputRef = useRef<HTMLInputElement>(null)
  const previewRefs = useRef<string[]>([])
  const [phase, setPhase] = useState<RunnerPhase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [previewUrls, setPreviewUrls] = useState<string[]>([])
  const [uploadedReferences, setUploadedReferences] = useState<UploadedFile[]>([])

  const busy = phase === 'uploading' || phase === 'generating'
  const isVideoTrend = trend?.generation_settings?.kind === 'video'
  const exactReferenceCount = requiredReferenceCount(trend)
  const referenceLimit = exactReferenceCount ?? MAX_REFERENCES
  const hasEnoughReferences = exactReferenceCount
    ? uploadedReferences.length === exactReferenceCount
    : uploadedReferences.length > 0
  const referenceHint = String(
    (trend?.generation_settings as ExactTrendSettings | null | undefined)?.reference_hint || '',
  ).trim()

  const clearPreviews = useCallback(() => {
    for (const previewUrl of previewRefs.current) {
      if (previewUrl.startsWith('blob:')) URL.revokeObjectURL(previewUrl)
    }
    previewRefs.current = []
    setPreviewUrls([])
  }, [])

  useEffect(() => {
    if (open) return
    setPhase('idle')
    setError(null)
    clearPreviews()
    setUploadedReferences([])
    if (inputRef.current) inputRef.current.value = ''
  }, [clearPreviews, open])

  useEffect(() => clearPreviews, [clearPreviews])

  const handlePhotos = async (selectedFiles: File[]) => {
    if (!trend || busy || !selectedFiles.length) return
    if (uploadedReferences.length + selectedFiles.length > referenceLimit) {
      setPhase('error')
      setError(
        exactReferenceCount
          ? `Для этого тренда нужно ровно ${exactReferenceCount} фото`
          : `Можно загрузить максимум ${MAX_REFERENCES} фото`,
      )
      return
    }

    const invalidFile = selectedFiles.find((file) => {
      const extension = file.name.split('.').pop()?.toLowerCase() || ''
      return !file.type.startsWith('image/') && !IMAGE_EXTENSIONS.has(extension)
    })
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
      setPreviewUrls((current) => current.filter((url) => !localPreviews.includes(url)))
      setPhase('error')
      setError(cause instanceof Error ? cause.message : 'Не удалось загрузить фото')
    }
  }

  const removeReference = (index: number) => {
    if (busy) return
    const previewUrl = previewRefs.current[index]
    if (previewUrl?.startsWith('blob:')) URL.revokeObjectURL(previewUrl)
    previewRefs.current = previewRefs.current.filter((_, itemIndex) => itemIndex !== index)
    setPreviewUrls((current) => current.filter((_, itemIndex) => itemIndex !== index))
    setUploadedReferences((current) => current.filter((_, itemIndex) => itemIndex !== index))
    setPhase('idle')
    setError(null)
  }

  const handleGenerate = async () => {
    if (!trend || busy || !hasEnoughReferences) return
    setError(null)
    setPhase('generating')
    try {
      const result = await runTrend(
        trend.id,
        uploadedReferences.map((reference) => reference.url),
      )
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

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!busy) onOpenChange(nextOpen)
      }}
    >
      <DialogContent className="max-w-lg border-border/60 bg-background p-4">
        <DialogTitle className="pr-8 font-serif text-lg">
          {trend?.title || 'Повторить тренд'}
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
              className="mx-auto max-h-[42vh] max-w-full rounded-2xl bg-black object-contain"
            />
          ) : (
            <img
              src={normalizeMiniAppMediaUrl(trend.preview_url)}
              alt={trend.title}
              className="max-h-[42vh] w-full rounded-2xl object-contain"
            />
          )
        ) : null}

        <div className="rounded-2xl border border-gold/25 bg-gold/10 p-4 text-center">
          <Sparkles className="mx-auto h-6 w-6 text-gold" />
          <p className="mt-2 text-sm font-semibold text-foreground">
            {exactReferenceCount
              ? `Загрузите ${exactReferenceCount} фото`
              : 'Загрузите свои фото'}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {referenceHint || (
              exactReferenceCount
                ? `Добавляйте фото по одному в указанном порядке. Генерация начнётся только после нажатия кнопки «Сгенерировать».`
                : 'Добавьте все нужные фото — можно по одному или несколькими заходами. Генерация начнётся только после нажатия кнопки «Сгенерировать».'
            )}
          </p>
        </div>

        {previewUrls.length ? (
          <div className="grid max-h-64 grid-cols-2 gap-2 overflow-y-auto rounded-2xl bg-secondary/20 p-2">
            {previewUrls.map((previewUrl, index) => (
              <div key={previewUrl} className="relative">
                <img
                  src={previewUrl}
                  alt={`Референс ${index + 1}`}
                  className="h-28 w-full rounded-xl object-cover"
                />
                {!busy ? (
                  <button
                    type="button"
                    aria-label={`Удалить фото ${index + 1}`}
                    className="absolute right-1.5 top-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-black/70 text-white backdrop-blur transition hover:bg-black/85"
                    onClick={() => removeReference(index)}
                  >
                    <X className="h-4 w-4" />
                  </button>
                ) : null}
                {exactReferenceCount ? (
                  <span className="absolute bottom-1.5 left-1.5 rounded-full bg-black/70 px-2 py-0.5 text-[10px] font-medium text-white backdrop-blur">
                    Фото {index + 1}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}

        {uploadedReferences.length < referenceLimit ? (
          <label className="relative flex min-h-28 cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border/70 bg-secondary/35 p-4 text-sm text-muted-foreground transition hover:border-gold/50 hover:text-foreground">
            <input
              ref={inputRef}
              type="file"
              multiple={!exactReferenceCount && referenceLimit - uploadedReferences.length > 1}
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
                    : uploadedReferences.length
                      ? `Добавить фото ${uploadedReferences.length + 1}`
                      : exactReferenceCount
                        ? 'Добавить фото 1'
                        : 'Выбрать фото'}
            </span>
            {!busy ? (
              <span className="text-xs text-muted-foreground">
                Выбрано {uploadedReferences.length} из {referenceLimit}
              </span>
            ) : null}
          </label>
        ) : null}

        {error ? (
          <p className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <Button
          type="button"
          disabled={busy || !hasEnoughReferences}
          onClick={() => void handleGenerate()}
        >
          {phase === 'generating' ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {phase === 'generating'
            ? 'Генерирую…'
            : exactReferenceCount && !hasEnoughReferences
              ? `Добавьте ещё ${exactReferenceCount - uploadedReferences.length} фото`
              : `Сгенерировать · ${uploadedReferences.length} фото`}
        </Button>

        <Button
          type="button"
          variant="secondary"
          disabled={busy}
          onClick={() => onOpenChange(false)}
        >
          Закрыть
        </Button>
      </DialogContent>
    </Dialog>
  )
}
