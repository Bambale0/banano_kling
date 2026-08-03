'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { ImagePlus, Loader2, RefreshCcw, Sparkles } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { generateImage, generateVideo, uploadFile } from '@/lib/api'
import { resolveTrendSettings } from '@/lib/trend-settings'
import type { PromptItem, Task } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'

type RunnerPhase = 'idle' | 'uploading' | 'generating' | 'error'

interface TrendRunnerDialogProps {
  trend: PromptItem | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif', 'avif'])

export function TrendRunnerDialog({
  trend,
  open,
  onOpenChange,
}: TrendRunnerDialogProps) {
  const {
    state,
    addTask,
    setCredits,
    setTaskDetail,
    selectTask,
    addSavedReference,
  } = useApp()
  const inputRef = useRef<HTMLInputElement>(null)
  const previewRef = useRef<string>('')
  const [phase, setPhase] = useState<RunnerPhase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState('')

  const settings = useMemo(
    () =>
      trend
        ? resolveTrendSettings(trend, state.imageModels, state.videoModels)
        : null,
    [state.imageModels, state.videoModels, trend],
  )
  const busy = phase === 'uploading' || phase === 'generating'

  useEffect(() => {
    if (open) return
    setPhase('idle')
    setError(null)
    if (previewRef.current.startsWith('blob:')) {
      URL.revokeObjectURL(previewRef.current)
    }
    previewRef.current = ''
    setPreviewUrl('')
    if (inputRef.current) inputRef.current.value = ''
  }, [open])

  useEffect(
    () => () => {
      if (previewRef.current.startsWith('blob:')) {
        URL.revokeObjectURL(previewRef.current)
      }
    },
    [],
  )

  const runImageTrend = async (uploadedUrl: string): Promise<Task> => {
    if (!trend || !settings || settings.kind !== 'image') {
      throw new Error('Настройки фото-тренда недоступны')
    }

    let lastTask: Task | null = null
    let credits = state.user.credits
    const count = settings.count || 1
    for (let index = 0; index < count; index += 1) {
      const result = await generateImage({
        model: settings.model,
        ratio: settings.ratio,
        quality: settings.quality || 'basic',
        nsfwChecker: Boolean(settings.nsfw_checker),
        nsfwEnabled: Boolean(settings.nsfw_enabled),
        promptId: trend.id,
        sourceFeedGenId: null,
        prompt: trend.prompt_text,
        references: [uploadedUrl],
      })
      addTask(result.task)
      if (result.detail) setTaskDetail(result.detail)
      credits = result.credits
      lastTask = result.task
    }
    setCredits(credits)
    if (!lastTask) throw new Error('Не удалось создать задачу')
    return lastTask
  }

  const runVideoTrend = async (uploadedUrl: string): Promise<Task> => {
    if (!trend || !settings || settings.kind !== 'video') {
      throw new Error('Настройки видео-тренда недоступны')
    }
    if (settings.scenario !== 'imgtxt') {
      throw new Error('Этот видео-тренд нужно пересохранить в режиме «Фото + текст»')
    }

    const result = await generateVideo({
      model: settings.model,
      scenario: settings.scenario,
      ratio: settings.ratio,
      duration: settings.duration || 5,
      grokMode: settings.grok_mode,
      grokResolution: settings.grok_resolution,
      veoGenerationType: settings.veo_generation_type,
      veoTranslation: settings.veo_translation,
      veoResolution: settings.veo_resolution,
      veoSeed: settings.veo_seed,
      veoWatermark: settings.veo_watermark,
      klingNegativePrompt: settings.kling_negative_prompt,
      klingCfgScale: settings.kling_cfg_scale,
      omniResolution: settings.omni_resolution,
      omniSeed: settings.omni_seed,
      omniAudioIds: settings.omni_audio_ids,
      omniCharacterIds: settings.omni_character_ids,
      omniBaseVoice: settings.omni_base_voice,
      omniVoiceName: settings.omni_voice_name,
      omniVoiceDescription: settings.omni_voice_description,
      omniExampleDialogue: settings.omni_example_dialogue,
      omniCharacterName: settings.omni_character_name,
      omniCharacterAudioIds: settings.omni_character_audio_ids,
      prompt: trend.prompt_text,
      startImage: uploadedUrl,
      references: [],
      videoReferences: [],
      audioReference: null,
    })
    addTask(result.task)
    setCredits(result.credits)
    if (result.detail) setTaskDetail(result.detail)
    return result.task
  }

  const handlePhoto = async (file?: File) => {
    if (!file || !trend || !settings || busy) return
    const extension = file.name.split('.').pop()?.toLowerCase() || ''
    if (!file.type.startsWith('image/') && !IMAGE_EXTENSIONS.has(extension)) {
      setPhase('error')
      setError('Нужно загрузить фотографию')
      return
    }

    if (previewRef.current.startsWith('blob:')) {
      URL.revokeObjectURL(previewRef.current)
    }
    const localPreview = URL.createObjectURL(file)
    previewRef.current = localPreview
    setPreviewUrl(localPreview)
    setError(null)
    setPhase('uploading')

    try {
      const uploaded = await uploadFile('image_reference', file)
      addSavedReference(uploaded)
      setPhase('generating')
      const task =
        settings.kind === 'video'
          ? await runVideoTrend(uploaded.url)
          : await runImageTrend(uploaded.url)
      selectTask(task)
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
          settings?.kind === 'video' ? (
            <video
              src={trend.preview_url}
              muted
              loop
              autoPlay
              playsInline
              className="max-h-[42vh] w-full rounded-2xl bg-black object-contain"
            />
          ) : (
            <img
              src={trend.preview_url}
              alt={trend.title}
              className="max-h-[42vh] w-full rounded-2xl object-contain"
            />
          )
        ) : null}

        <div className="rounded-2xl border border-gold/25 bg-gold/10 p-4 text-center">
          <Sparkles className="mx-auto h-6 w-6 text-gold" />
          <p className="mt-2 text-sm font-semibold text-foreground">
            Загрузите своё фото
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Модель, промпт, формат, качество и остальные параметры применятся автоматически.
          </p>
        </div>

        {previewUrl ? (
          <img
            src={previewUrl}
            alt="Загруженное фото"
            className="max-h-56 w-full rounded-2xl object-contain"
          />
        ) : null}

        <label className="relative flex min-h-28 cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border/70 bg-secondary/35 p-4 text-sm text-muted-foreground transition hover:border-gold/50 hover:text-foreground">
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/heic,image/heif,image/avif"
            className="absolute inset-0 cursor-pointer opacity-0"
            disabled={busy}
            onChange={(event) => {
    const file = event.currentTarget.files?.[0]
    event.currentTarget.value = ''
    void handlePhoto(file)
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
              ? 'Загружаю фото…'
              : phase === 'generating'
                ? 'Применяю тренд и запускаю…'
                : phase === 'error'
                  ? 'Выбрать другое фото'
                  : 'Выбрать фото'}
          </span>
        </label>

        {error ? (
          <p className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </p>
        ) : null}

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
