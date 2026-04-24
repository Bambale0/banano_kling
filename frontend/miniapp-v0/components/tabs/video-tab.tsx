'use client'

import { useState } from 'react'
import { useApp } from '@/lib/app-context'
import { VideoGeneratorForm } from '../forms/video-generator-form'
import { ResultCard } from '../result-card'
import type { Task, ScenarioType, UploadedFile } from '@/lib/types'
import { generateVideo, uploadFile } from '@/lib/api'

export function VideoTab() {
  const { state, addTask, setCredits, setTaskDetail, selectTask } = useApp()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [lastResult, setLastResult] = useState<Task | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (data: {
    model: string
    scenario: ScenarioType
    ratio: string
    duration: number
    grokMode: string
    veoGenerationType: string
    veoTranslation: boolean
    veoResolution: string
    veoSeed: number | null
    veoWatermark: string
    klingNegativePrompt: string
    klingCfgScale: number
    prompt: string
    startImage: string | null
    references: string[]
    videoReferences: string[]
  }) => {
    setIsSubmitting(true)
    setError(null)
    try {
      if (state.mode === 'live') {
        const result = await generateVideo(data)
        addTask(result.task)
        setCredits(result.credits)
        setLastResult(result.task)
        if (result.detail) {
          setTaskDetail(result.detail)
        }
        selectTask(result.task)
      } else {
        const model = state.videoModels.find(m => m.id === data.model)
        const cost = model?.costs[data.duration.toString()] || 5
        const newTask: Task = {
          task_id: `task_${Date.now()}`,
          type: 'video',
          model: data.model,
          model_label: model?.label || data.model,
          aspect_ratio: data.ratio,
          status: 'pending',
          created_at: new Date().toISOString(),
          prompt_preview: data.prompt.slice(0, 100) + (data.prompt.length > 100 ? '...' : ''),
          cost,
          duration: data.duration,
        }
        addTask(newTask)
        setCredits(Math.max(state.user.credits - cost, 0))
        setLastResult(newTask)
        selectTask(newTask)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось запустить видео')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleUploadImageReference = async (file: File): Promise<UploadedFile> => {
    if (state.mode !== 'live') {
      return {
        id: `file_${Date.now()}`,
        name: file.name,
        url: URL.createObjectURL(file),
        type: 'image',
        size: file.size,
      }
    }
    return uploadFile('image_reference', file)
  }

  const handleUploadVideoReference = async (file: File): Promise<UploadedFile> => {
    if (state.mode !== 'live') {
      return {
        id: `file_${Date.now()}`,
        name: file.name,
        url: '',
        type: 'video',
        size: file.size,
      }
    }
    return uploadFile('video_reference', file)
  }

  return (
    <div className="px-4 space-y-6">
      <div className="text-center mb-6">
        <h2 className="font-serif text-xl font-semibold text-foreground mb-1">
          Генерация видео
        </h2>
        <p className="text-sm text-muted-foreground">
          Создавайте кинематографичные видео с AI
        </p>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
        <VideoGeneratorForm 
          models={state.videoModels}
          onSubmit={handleSubmit}
          onUploadImageReference={handleUploadImageReference}
          onUploadVideoReference={handleUploadVideoReference}
          isSubmitting={isSubmitting}
          credits={state.user.credits}
        />

        <div className="space-y-4">
          {error && (
            <div className="p-4 rounded-xl bg-destructive/10 border border-destructive/30">
              <p className="text-sm text-destructive">{error}</p>
            </div>
          )}

          {lastResult ? (
            <ResultCard 
              task={lastResult}
              onClose={() => setLastResult(null)}
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
