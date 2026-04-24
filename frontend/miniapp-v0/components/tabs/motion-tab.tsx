'use client'

import { useState } from 'react'
import { Sparkles, Upload, Video, Image as ImageIcon, Wand2 } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { generateMotion, uploadFile } from '@/lib/api'
import type { Task, UploadedFile } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ResultCard } from '../result-card'
import { cn } from '@/lib/utils'

type MotionMode = '720p' | '1080p'
type MotionDirection = 'video' | 'image'

function MotionUploadCard({
  title,
  description,
  icon: Icon,
  accept,
  file,
  onUpload,
  disabled,
}: {
  title: string
  description: string
  icon: typeof ImageIcon
  accept: string
  file: UploadedFile | null
  onUpload: (file: File) => Promise<void>
  disabled?: boolean
}) {
  const [isUploading, setIsUploading] = useState(false)

  async function handleChange(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0]
    if (!selected) return

    setIsUploading(true)
    try {
      await onUpload(selected)
    } finally {
      setIsUploading(false)
      event.target.value = ''
    }
  }

  return (
    <label
      className={cn(
        'group relative block overflow-hidden rounded-3xl border border-border/60',
        'bg-card/45 p-5 transition-all duration-300',
        'hover:border-gold/40 hover:bg-card/70',
        file && 'border-gold/45 bg-gold/[0.05]'
      )}
    >
      <input
        type="file"
        accept={accept}
        className="sr-only"
        disabled={disabled || isUploading}
        onChange={handleChange}
      />

      <div className="absolute inset-0 bg-gradient-to-br from-gold/[0.08] via-transparent to-cyan/[0.08] opacity-0 transition-opacity group-hover:opacity-100" />

      <div className="relative flex items-start gap-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-background/70 border border-border/60">
          <Icon className={cn('h-5 w-5', file ? 'text-gold' : 'text-muted-foreground')} />
        </div>

        <div className="min-w-0 flex-1">
          <p className="font-serif text-lg text-foreground">{title}</p>
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>

          <div className="mt-4 rounded-2xl border border-dashed border-border/70 bg-background/45 px-4 py-3">
            <div className="flex items-center gap-2 text-sm">
              <Upload className="h-4 w-4 text-gold" />
              <span className="truncate">
                {isUploading
                  ? 'Загружаю…'
                  : file
                    ? file.name
                    : 'Нажмите, чтобы загрузить файл'}
              </span>
            </div>
          </div>
        </div>
      </div>
    </label>
  )
}

export function MotionTab() {
  const { state, addTask, setCredits, setTaskDetail, selectTask } = useApp()

  const [characterImage, setCharacterImage] = useState<UploadedFile | null>(null)
  const [motionVideo, setMotionVideo] = useState<UploadedFile | null>(null)
  const [mode, setMode] = useState<MotionMode>('720p')
  const [direction, setDirection] = useState<MotionDirection>('video')
  const [prompt, setPrompt] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [lastResult, setLastResult] = useState<Task | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function uploadImage(file: File) {
    if (state.mode !== 'live') {
      setCharacterImage({
        id: `file_${Date.now()}`,
        name: file.name,
        url: URL.createObjectURL(file),
        type: 'image',
        size: file.size,
      })
      return
    }

    setCharacterImage(await uploadFile('image_reference', file))
  }

  async function uploadVideo(file: File) {
    if (state.mode !== 'live') {
      setMotionVideo({
        id: `file_${Date.now()}`,
        name: file.name,
        url: '',
        type: 'video',
        size: file.size,
      })
      return
    }

    setMotionVideo(await uploadFile('video_reference', file))
  }

  async function handleSubmit() {
    setError(null)

    if (!characterImage) {
      setError('Загрузите фото персонажа')
      return
    }

    if (!motionVideo) {
      setError('Загрузите видео движения')
      return
    }

    setIsSubmitting(true)

    try {
      if (state.mode === 'live') {
        const result = await generateMotion({
          imageUrl: characterImage.url,
          videoUrl: motionVideo.url,
          prompt,
          mode,
          direction,
        })

        addTask(result.task)
        setCredits(result.credits)
        setLastResult(result.task)
        selectTask(result.task)

        if (result.detail) {
          setTaskDetail(result.detail)
        }
      } else {
        const cost = mode === '1080p' ? 18 : 12
        const newTask: Task = {
          task_id: `motion_${Date.now()}`,
          type: 'video',
          model: 'motion_control',
          model_label: 'Kling 2.6 Motion Control',
          aspect_ratio: 'motion',
          status: 'pending',
          created_at: new Date().toISOString(),
          prompt_preview: prompt || 'Motion transfer',
          cost,
          duration: 5,
        }

        addTask(newTask)
        setCredits(Math.max(state.user.credits - cost, 0))
        setLastResult(newTask)
        selectTask(newTask)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось запустить Motion Control')
    } finally {
      setIsSubmitting(false)
    }
  }

  const estimatedCost = mode === '1080p' ? 'Pro тариф' : 'Standard тариф'

  return (
    <div className="px-4 space-y-6">
      <div className="relative overflow-hidden rounded-[2rem] border border-gold/20 bg-gradient-to-br from-gold/[0.12] via-card/70 to-cyan/[0.10] p-6">
        <div className="absolute -right-12 -top-12 h-36 w-36 rounded-full bg-gold/20 blur-3xl" />
        <div className="absolute -left-10 bottom-0 h-28 w-28 rounded-full bg-cyan/15 blur-3xl" />

        <div className="relative">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-gold/25 bg-background/50 px-3 py-1 text-xs uppercase tracking-[0.22em] text-gold">
            <Sparkles className="h-3.5 w-3.5" />
            Motion Canvas
          </div>

          <h2 className="font-serif text-3xl font-semibold leading-tight text-foreground">
            Перенесите движение на персонажа
          </h2>

          <p className="mt-3 max-w-[34rem] text-sm leading-6 text-muted-foreground">
            Загрузите фото героя и видео движения. Kling 2.6 Motion Control
            перенесёт динамику, сохранив образ и визуальное направление.
          </p>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.12fr)_minmax(320px,0.88fr)]">
        <div className="space-y-4">
          <MotionUploadCard
            title="Фото персонажа"
            description="Исходное фото героя, объекта или персонажа."
            icon={ImageIcon}
            accept="image/*"
            file={characterImage}
            onUpload={uploadImage}
            disabled={isSubmitting}
          />

          <MotionUploadCard
            title="Видео движения"
            description="Короткий ролик, с которого переносим движение."
            icon={Video}
            accept="video/*"
            file={motionVideo}
            onUpload={uploadVideo}
            disabled={isSubmitting}
          />

          <div className="glass rounded-3xl border border-border/60 p-5">
            <p className="font-serif text-lg text-foreground mb-4">Настройки движения</p>

            <div className="grid grid-cols-2 gap-3">
              {(['720p', '1080p'] as MotionMode[]).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setMode(item)}
                  className={cn(
                    'rounded-2xl border px-4 py-3 text-sm transition-all',
                    mode === item
                      ? 'border-gold/60 bg-gold/10 text-gold'
                      : 'border-border/70 bg-background/40 text-muted-foreground'
                  )}
                >
                  {item}
                </button>
              ))}
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3">
              {[
                { id: 'video' as const, label: 'Как в видео' },
                { id: 'image' as const, label: 'Как на фото' },
              ].map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setDirection(item.id)}
                  className={cn(
                    'rounded-2xl border px-4 py-3 text-sm transition-all',
                    direction === item.id
                      ? 'border-cyan/60 bg-cyan/10 text-cyan'
                      : 'border-border/70 bg-background/40 text-muted-foreground'
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>

            <div className="mt-4">
              <Textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Опционально: keep face stable, cinematic motion, smooth camera…"
                className="min-h-28 rounded-2xl bg-background/50"
              />
            </div>
          </div>

          {error && (
            <div className="rounded-2xl border border-destructive/30 bg-destructive/10 p-4">
              <p className="text-sm text-destructive">{error}</p>
            </div>
          )}

          <Button
            type="button"
            size="lg"
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="h-14 w-full rounded-2xl bg-gold text-background hover:bg-gold/90"
          >
            <Wand2 className="mr-2 h-5 w-5" />
            {isSubmitting ? 'Запускаю Motion…' : 'Run Motion Control'}
          </Button>
        </div>

        <div className="space-y-4">
          <div className="glass rounded-3xl border border-border/60 p-5">
            <p className="text-xs uppercase tracking-[0.18em] text-gold/80 mb-3">
              Что отправим
            </p>

            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Режим</span>
                <strong>Kling 2.6 Motion</strong>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Качество</span>
                <strong>{mode}</strong>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Ориентация</span>
                <strong>{direction === 'video' ? 'как в видео' : 'как на фото'}</strong>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Фото</span>
                <strong>{characterImage ? 'загружено' : 'нет'}</strong>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Видео</span>
                <strong>{motionVideo ? 'загружено' : 'нет'}</strong>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Стоимость</span>
                <strong>{estimatedCost}</strong>
              </div>
            </div>
          </div>

          {lastResult ? (
            <ResultCard task={lastResult} onClose={() => setLastResult(null)} />
          ) : (
            <div className="rounded-3xl border border-cyan/20 bg-cyan/[0.06] p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-cyan/80 mb-2">
                Result
              </p>
              <h3 className="font-serif text-lg text-foreground mb-2">
                Готово к переносу движения
              </h3>
              <p className="text-sm leading-6 text-muted-foreground">
                После запуска здесь появится task id и статус. Готовый ролик
                подтянется в историю и придёт в чат бота.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
