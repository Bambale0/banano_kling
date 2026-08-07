'use client'

import { useMemo, useState } from 'react'
import { useApp } from '@/lib/app-context'
import { VideoGeneratorForm } from '../forms/video-generator-form'
import { Seedance25PublicForm } from '../forms/seedance25-public-form'
import { ResultCard } from '../result-card'
import type { Task, ScenarioType, UploadedFile } from '@/lib/types'
import type { Seedance25GenerateResponse } from '@/lib/seedance25-api'
import { generateVideo, uploadFile } from '@/lib/api'

export function VideoTab() {
  const {
    state,
    addTask,
    setCredits,
    setTaskDetail,
    selectTask,
    addSavedReference,
    videoPromptPreset,
    setVideoPromptPreset,
    refreshTasks,
  } = useApp()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [lastРезультат, setLastРезультат] = useState<Task | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [videoMode, setVideoMode] = useState<'regular' | 'seedance25'>('regular')
  const [seedanceQueued, setSeedanceQueued] = useState<Seedance25GenerateResponse | null>(null)

  const seedance25Model = useMemo(
    () => state.videoModels.find((item) => item.id === 'seedance_2_5'),
    [state.videoModels],
  )
  const regularVideoModels = useMemo(
    () => state.videoModels.filter((item) => item.id !== 'seedance_2_5'),
    [state.videoModels],
  )
  const canUseSeedance25 = Boolean(seedance25Model)
  const effectiveMode = canUseSeedance25 ? videoMode : 'regular'

  const handleSubmit = async (data: {
    model: string
    scenario: ScenarioType
    ratio: string
    duration: number
    sourceFeedGenId?: number | null
    grokMode: string
    grokResolution: string
    veoGenerationType: string
    veoTranslation: boolean
    veoResolution: string
    veoSeed: number | null
    veoWatermark: string
    klingNegativePrompt: string
    klingCfgScale: number
    omniResolution: string
    omniSeed: number | null
    omniAudioIds: string[]
    omniCharacterIds: string[]
    omniBaseVoice: string
    omniVoiceName: string
    omniVoiceDescription: string
    omniExampleDialogue: string
    omniCharacterName: string
    omniCharacterAudioIds: string[]
    prompt: string
    startImage: string | null
    references: string[]
    videoReferences: string[]
    audioReference: string | null
  }) => {
    if (state.mode !== 'live') {
      const modeError = new Error('Откройте Mini App через Telegram, чтобы запустить генерацию.')
      setError(modeError.message)
      throw modeError
    }
    setIsSubmitting(true)
    setError(null)
    try {
      const result = await generateVideo(data)
      addTask(result.task)
      setCredits(result.credits)
      setLastРезультат(result.task)
      if (result.detail) {
        setTaskDetail(result.detail)
      }
      selectTask(result.task)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось запустить видео')
      throw e
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleUploadImageReference = async (file: File): Promise<UploadedFile> => {
    if (state.mode !== 'live') {
      throw new Error('Откройте Mini App через Telegram, чтобы загрузить референс.')
    }
    const uploaded = await uploadFile('image_reference', file)
    addSavedReference(uploaded)
    return uploaded
  }

  const handleUploadVideoReference = async (file: File): Promise<UploadedFile> => {
    if (state.mode !== 'live') {
      throw new Error('Откройте Mini App через Telegram, чтобы загрузить видео.')
    }
    const uploaded = await uploadFile('video_reference', file)
    addSavedReference(uploaded)
    return uploaded
  }

  const handleUploadAudioReference = async (file: File): Promise<UploadedFile> => {
    if (state.mode !== 'live') {
      throw new Error('Откройте Mini App через Telegram, чтобы загрузить аудио.')
    }
    const uploaded = await uploadFile('audio_reference', file)
    addSavedReference(uploaded)
    return uploaded
  }

  const handleSeedanceQueued = async (result: Seedance25GenerateResponse) => {
    setSeedanceQueued(result)
    setCredits(result.credits)
    try {
      await refreshTasks()
    } catch {
      // Dedicated Seedance webhook/polling still completes the task in Telegram.
    }
  }

  return (
    <div className="min-w-0 space-y-4 overflow-x-hidden px-3 pb-3 sm:px-4">
      <div className="text-center mb-6">
        <h2 className="font-serif text-xl font-semibold text-foreground mb-1">
          Генерация видео
        </h2>
        <p className="text-sm text-muted-foreground">
          Создавайте кинематографичные видео с AI
        </p>
      </div>

      {canUseSeedance25 ? (
        <div className="mx-auto mb-4 grid max-w-xl grid-cols-2 gap-2 rounded-2xl border border-cyan/20 bg-background/40 p-1.5">
          <button
            type="button"
            onClick={() => setVideoMode('regular')}
            className={`rounded-xl px-3 py-2 text-xs font-medium transition ${
              effectiveMode === 'regular'
                ? 'bg-secondary text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            Все модели
          </button>
          <button
            type="button"
            onClick={() => setVideoMode('seedance25')}
            className={`rounded-xl px-3 py-2 text-xs font-medium transition ${
              effectiveMode === 'seedance25'
                ? 'bg-cyan/15 text-cyan'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <span className="mr-1 rounded-full border border-gold/40 bg-gold/15 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.12em] text-gold">NEW</span>
            Seedance 2.5
          </button>
        </div>
      ) : null}

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)] xl:gap-6">
        {effectiveMode === 'seedance25' && seedance25Model ? (
          <Seedance25PublicForm
            model={seedance25Model}
            credits={state.user.credits}
            isAdmin={state.user.isAdmin}
            onQueued={handleSeedanceQueued}
            onSavedReference={addSavedReference}
          />
        ) : (
          <VideoGeneratorForm
            models={regularVideoModels}
            onSubmit={handleSubmit}
            onUploadImageReference={handleUploadImageReference}
            onUploadVideoReference={handleUploadVideoReference}
            onUploadAudioReference={handleUploadAudioReference}
            savedImageReferences={state.savedReferences.filter((item) => item.type === 'image')}
            savedVideoReferences={state.savedReferences.filter((item) => item.type === 'video')}
            savedAudioReferences={state.savedReferences.filter((item) => item.type === 'audio')}
            promptPreset={videoPromptPreset}
            onPromptPresetConsumed={() => setVideoPromptPreset(null)}
            isSubmitting={isSubmitting}
            credits={state.user.credits}
          />
        )}

        <div className="space-y-4">
          {error && effectiveMode === 'regular' ? (
            <div className="p-4 rounded-xl bg-destructive/10 border border-destructive/30">
              <p className="text-sm text-destructive">{error}</p>
            </div>
          ) : null}

          {effectiveMode === 'seedance25' ? (
            <div className="glass rounded-2xl border border-cyan/20 p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-cyan/80 mb-2">Seedance queue</p>
              <h3 className="font-serif text-lg text-foreground mb-2">Seedance 2.5</h3>
              {seedanceQueued ? (
                <div className="space-y-2 text-sm">
                  <p>✅ Задача отправлена в Kie.ai.</p>
                  <p className="break-all font-mono text-xs text-muted-foreground">{seedanceQueued.task_id}</p>
                  <p className="text-xs text-muted-foreground">
                    {seedanceQueued.admin_free
                      ? 'Для администратора списание отключено.'
                      : `Списано ${seedanceQueued.cost}🍌.`}{' '}
                    Результат придёт в Telegram. Если callback задержится, включён polling fallback.
                  </p>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Здесь появится ID последней задачи Seedance 2.5. Итоговое видео бот пришлёт автоматически.
                </p>
              )}
            </div>
          ) : lastРезультат ? (
            <ResultCard
              task={lastРезультат}
              onClose={() => setLastРезультат(null)}
            />
          ) : (
            <div className="glass rounded-2xl border border-cyan/20 p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-cyan/80 mb-2">Очередь</p>
              <h3 className="font-serif text-lg text-foreground mb-2">Видео-панель</h3>
              <p className="text-sm text-muted-foreground">
                Очередь, task id и превью ролика появятся здесь. Для image-to-video сначала добавьте стартовый кадр, для video-to-video загрузите видео-референс.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
