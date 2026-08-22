'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { ImagePlus, Loader2, RefreshCcw, Sparkles } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { uploadFile } from '@/lib/api'
import { runTrend } from '@/lib/trend-api'
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
const DEFAULT_TWO_PHOTO_LABELS = ['Референс из Pinterest', 'Ваше фото']

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

  const busy = phase === 'uploading' || phase === 'generating'
  const isVideoTrend = trend?.generation_settings?.kind === 'video'
  const configuredReferenceCount = Number(trend?.generation_settings?.reference_count || 0)
  const exactReferenceCount = Number.isFinite(configuredReferenceCount) && configuredReferenceCount > 0
    ? Math.min(MAX_REFERENCES, Math.trunc(configuredReferenceCount))
    : 0
  const exactSlots = exactReferenceCount > 0
  const referenceLabels = exactSlots
    ? Array.from({ length: exactReferenceCount }, (_, index) =>
        trend?.generation_settings?.reference_labels?.[index]?.trim() ||
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
      setPreviewUrls((current) => current.filter((url) => !localPreviews.includes(url)))
      setPhase('error')
      setError(cause instanceof Error ? cause.message : 'Не удалось загрузить фото')
    }
  }

  const handleGenerate = async () => {
    if (!trend || busy || !readyToGenerate) return
    setError(null)
    setPhase('generating')
    try {
      const result = await runTrend(
        trend.id,
        completedReferences.map((reference) => reference.url),
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
            {exactSlots ? 'Добавьте два фото по порядку' : 'Загрузите свои фото'}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {exactSlots
              ? 'Сначала добавьте референс, затем своё фото. Генерация не начнётся сама — после загрузки обоих нажмите «Сгенерировать».'
              : 'Добавьте все нужные фото — можно по одному или несколькими заходами. Генерация начнётся только после нажатия кнопки «Сгенерировать».'}
          </p>
        </div>

        {exactSlots ? (
          <div className="grid grid-cols-2 gap-3">
            {referenceLabels.map((label, index) => {
              const previewUrl = previewUrls[index]
              const uploaded = uploadedReferences[index]
              return (
                <label
                  key={`${label}-${index}`}
                  className="relative flex min-h-40 cursor-pointer flex-col overflow-hidden rounded-2xl border border-dashed border-border/70 bg-secondary/35 text-sm transition hover:border-gold/50"
                >
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
                    <img src={previewUrl} alt={label} className="h-32 w-full object-cover" />
                  ) : (
                    <div className="flex h-32 items-center justify-center">
                      {phase === 'uploading' ? (
                        <Loader2 className="h-7 w-7 animate-spin text-gold" />
                      ) : (
                        <ImagePlus className="h-7 w-7 text-gold" />
                      )}
                    </div>
                  )}
                  <div className="flex min-h-12 items-center justify-center px-2 py-2 text-center font-medium text-foreground">
                    {index + 1}. {label}{uploaded ? ' ✓' : ''}
                  </div>
                </label>
              )
            })}
          </div>
        ) : (
          <>
            {previewUrls.length ? (
              <div className="grid max-h-64 grid-cols-2 gap-2 overflow-y-auto rounded-2xl bg-secondary/20 p-2">
                {previewUrls.filter(Boolean).map((previewUrl, index) => (
                  <img
                    key={previewUrl}
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

        {error ? (
          <p className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <Button
          type="button"
          disabled={busy || !readyToGenerate}
          onClick={() => void handleGenerate()}
        >
          {phase === 'generating' ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {phase === 'generating'
            ? 'Генерирую…'
            : exactSlots
              ? `Сгенерировать · ${completedReferences.length}/${exactReferenceCount}`
              : `Сгенерировать · ${completedReferences.length} фото`}
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
