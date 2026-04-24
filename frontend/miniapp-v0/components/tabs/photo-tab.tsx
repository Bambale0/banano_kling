'use client'

import { useState } from 'react'
import { useApp } from '@/lib/app-context'
import { ImageGeneratorForm } from '../forms/image-generator-form'
import { ResultCard } from '../result-card'
import type { Task, UploadedFile } from '@/lib/types'
import { generateImage, uploadFile } from '@/lib/api'

export function PhotoTab() {
  const { state, addTask, setCredits, setTaskDetail, selectTask } = useApp()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [lastResult, setLastResult] = useState<Task | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (data: {
    model: string
    ratio: string
    quality: string
    count: number
    nsfwChecker: boolean
    nsfwEnabled: boolean
    prompt: string
    references: string[]
  }) => {
    setIsSubmitting(true)
    setError(null)
    try {
      let lastTask: Task | null = null
      let latestCredits = state.user.credits

      for (let index = 0; index < data.count; index += 1) {
        if (state.mode === 'live') {
          const result = await generateImage({
            model: data.model,
            ratio: data.ratio,
            quality: data.quality,
            nsfwChecker: data.nsfwChecker,
            nsfwEnabled: data.nsfwEnabled,
            prompt: data.prompt,
            references: data.references,
          })
          addTask(result.task)
          latestCredits = result.credits
          lastTask = result.task
          if (result.detail) {
            setTaskDetail(result.detail)
          }
        } else {
          const model = state.imageModels.find(m => m.id === data.model)
          const unitCost = model?.cost || 2
          const newTask: Task = {
            task_id: `task_${Date.now()}_${index}`,
            type: 'image',
            model: data.model,
            model_label: model?.label || data.model,
            aspect_ratio: data.ratio,
            status: 'pending',
            created_at: new Date().toISOString(),
            prompt_preview: data.prompt.slice(0, 100) + (data.prompt.length > 100 ? '...' : ''),
            cost: unitCost,
          }
          addTask(newTask)
          latestCredits = Math.max(latestCredits - unitCost, 0)
          lastTask = newTask
        }
      }

      setCredits(latestCredits)
      if (lastTask) {
        setLastResult(lastTask)
        selectTask(lastTask)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось запустить фото')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleUploadReference = async (file: File): Promise<UploadedFile> => {
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

  return (
    <div className="px-4 space-y-6">
      <div className="text-center mb-6">
        <h2 className="font-serif text-xl font-semibold text-foreground mb-1">
          Генерация фото
        </h2>
        <p className="text-sm text-muted-foreground">
          Создавайте уникальные изображения с AI
        </p>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
        <ImageGeneratorForm 
          models={state.imageModels}
          onSubmit={handleSubmit}
          onUploadReference={handleUploadReference}
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
            <div className="glass rounded-2xl border border-border/50 p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-gold/80 mb-2">Результат</p>
              <h3 className="font-serif text-lg text-foreground mb-2">Готово к запуску</h3>
              <p className="text-sm text-muted-foreground">
                Выберите модель, добавьте prompt и при необходимости загрузите референсы. Очередь, ошибки и готовый результат появятся здесь.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
