'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '@/lib/app-context'
import { copyTextToClipboard } from '@/lib/clipboard'
import type { PromptItem, ScenarioType } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { deactivatePrompt, fetchPromptLink, fetchPrompts, submitPrompt, uploadFile } from '@/lib/api'
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
  X,
} from 'lucide-react'

type TrendKind = 'image' | 'video'

const VIDEO_TREND_TAG = 'trend-video'

function hasVideoTag(trend: PromptItem) {
  return (trend.tags || []).some((tag) => String(tag).toLowerCase() === VIDEO_TREND_TAG)
}

export function TrendsTab() {
  const {
    state,
    setActiveTab,
    setPromptPreset,
    setVideoPromptPreset,
  } = useApp()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [items, setItems] = useState<PromptItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [trendKind, setTrendKind] = useState<TrendKind>('image')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [promptText, setPromptText] = useState('')
  const [model, setModel] = useState('banana_pro')
  const [videoScenario, setVideoScenario] = useState<ScenarioType>('imgtxt')
  const [videoDuration, setVideoDuration] = useState(5)
  const [previewUrl, setPreviewUrl] = useState('')
  const [uploadingPreview, setUploadingPreview] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [removingId, setRemovingId] = useState<number | null>(null)
  const [copiedId, setCopiedId] = useState<number | null>(null)
  const [previewTrend, setPreviewTrend] = useState<PromptItem | null>(null)
  const [videoAspectRatios, setVideoAspectRatios] = useState<Record<number, string>>({})

  const isLive = state.mode === 'live'
  const isAdmin = state.user.isAdmin
  const availableModels = trendKind === 'video' ? state.videoModels : state.imageModels

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
      const trends = await fetchPrompts({ source: 'catalog', limit: 80 })
      setItems(trends)
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
    if (trendKind === 'video') {
      const selectedVideoModel = state.videoModels.find((item) => item.id === model)
      if (selectedVideoModel && !selectedVideoModel.supports.includes(videoScenario)) {
        setVideoScenario(selectedVideoModel.supports.includes('imgtxt') ? 'imgtxt' : selectedVideoModel.supports[0] || 'text')
      }
      if (selectedVideoModel && !selectedVideoModel.durations.includes(videoDuration)) {
        setVideoDuration(selectedVideoModel.durations[0] || 5)
      }
    }
    setPreviewUrl('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [model, state.imageModels, state.videoModels, trendKind, videoDuration, videoScenario])

  const resetForm = () => {
    setTrendKind('image')
    setTitle('')
    setDescription('')
    setPromptText('')
    setModel(state.imageModels[0]?.id || 'banana_pro')
    setVideoScenario('imgtxt')
    setVideoDuration(5)
    setPreviewUrl('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const applyTrend = (trend: PromptItem) => {
    if (isVideoTrend(trend)) {
      const videoModel = state.videoModels.find((item) => item.id === trend.model)
      const scenarioTag = (trend.tags || []).find((tag) => String(tag).startsWith('trend-scenario:'))
      const durationTag = (trend.tags || []).find((tag) => String(tag).startsWith('trend-duration:'))
      const configuredScenario = String(scenarioTag || '').split(':')[1] as ScenarioType
      const scenario = videoModel?.supports.includes(configuredScenario)
        ? configuredScenario
        : videoModel?.supports.includes('imgtxt') ? 'imgtxt' : videoModel?.supports[0] || 'text'
      setVideoPromptPreset({
        title: trend.title,
        prompt: trend.prompt_text,
        model: videoModel?.id || state.videoModels[0]?.id || 'v3_pro',
        scenario,
        duration: Number(String(durationTag || '').split(':')[1]) || videoModel?.durations[0] || 5,
      })
      setActiveTab(2)
      return
    }

    setPromptPreset({
      promptId: trend.id,
      title: trend.title,
      prompt: trend.prompt_text,
      model: trend.model || state.imageModels[0]?.id || 'banana_pro',
    })
    setActiveTab(1)
  }

  const handlePreviewUpload = async (file?: File) => {
    if (!file) return
    const expectedPrefix = trendKind === 'video' ? 'video/' : 'image/'
    if (!file.type.startsWith(expectedPrefix)) {
      setError(
        trendKind === 'video'
          ? 'Для видео-тренда нужен видеофайл'
          : 'Для фото-тренда нужно изображение',
      )
      return
    }

    setUploadingPreview(true)
    setError(null)
    try {
      const uploaded = await uploadFile(
        trendKind === 'video' ? 'video_reference' : 'image_reference',
        file,
      )
      setPreviewUrl(uploaded.url)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить preview')
    } finally {
      setUploadingPreview(false)
    }
  }

  const handleCreate = async () => {
    if (!isAdmin || submitting) return
    if (!title.trim() || !promptText.trim() || !previewUrl || !model) {
      setError('Заполните название, preview, нейросеть и скрытый prompt')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const created = await submitPrompt({
        title: title.trim(),
        description: description.trim(),
        promptText: promptText.trim(),
        previewUrl,
        model,
        tags: trendKind === 'video'
          ? ['trend', VIDEO_TREND_TAG, `trend-scenario:${videoScenario}`, `trend-duration:${videoDuration}`]
          : ['trend'],
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

  const renderTrendGrid = (trends: PromptItem[], title: string, videoSection: boolean) => {
    if (!trends.length) return null
    return (
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-serif text-lg font-semibold text-foreground">{title}</h3>
          <span className="rounded-full bg-secondary/60 px-2.5 py-1 text-xs text-muted-foreground">{trends.length}</span>
        </div>
        <div className="grid grid-cols-2 items-start gap-3 md:grid-cols-3">
          {trends.map((trend) => {
            const modelLabel = videoSection
              ? state.videoModels.find((item) => item.id === trend.model)?.label
              : state.imageModels.find((item) => item.id === trend.model)?.label
            return (
              <article key={trend.id} className="glass min-w-0 overflow-hidden rounded-2xl border border-border/50">
                <div className="relative bg-secondary/40">
                  {trend.preview_url ? videoSection ? (
                    <button type="button" className="block w-full" onClick={() => setPreviewTrend(trend)} aria-label={`Открыть видео ${trend.title}`}>
                      <video
                        src={trend.preview_url}
                        muted
                        playsInline
                        preload="metadata"
                        onLoadedMetadata={(event) => rememberVideoAspectRatio(trend.id, event.currentTarget)}
                        style={{ aspectRatio: videoAspectRatios[trend.id] || '16 / 9' }}
                        className="w-full bg-black object-contain"
                      />
                      <span className="absolute inset-0 grid place-items-center bg-black/10"><Film className="h-8 w-8 rounded-full bg-black/55 p-1.5 text-white" /></span>
                    </button>
                  ) : (
                    <img src={trend.preview_url} alt={trend.title} loading="lazy" className="h-auto max-h-[420px] w-full object-contain" />
                  ) : (
                    <div className={videoSection ? 'flex aspect-video items-center justify-center' : 'flex aspect-square items-center justify-center'}><Sparkles className="h-8 w-8 text-gold" /></div>
                  )}
                </div>
                <div className="space-y-2.5 p-3">
                  <div><h4 className="line-clamp-2 text-sm font-semibold text-foreground">{trend.title}</h4>{trend.description ? <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{trend.description}</p> : null}</div>
                  <div className="truncate rounded-lg bg-secondary/55 px-2 py-1.5 text-[10px] text-muted-foreground">{modelLabel || trend.model}</div>
                  <Button type="button" size="sm" className="w-full bg-gold text-primary-foreground hover:bg-gold/90" onClick={() => applyTrend(trend)}><Repeat2 className="h-3.5 w-3.5" />Повторить</Button>
                  <div className={isAdmin ? 'grid grid-cols-[1fr_auto] gap-2' : 'grid'}>
                    <Button type="button" size="sm" variant="secondary" onClick={() => void handleCopyLink(trend)}>{copiedId === trend.id ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}{copiedId === trend.id ? 'Скопировано' : 'Ссылка'}</Button>
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
              Пользователи увидят пример и описание, но не увидят скрытый prompt.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setTrendKind('image')}
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
              onClick={() => setTrendKind('video')}
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
                <span className="text-xs font-medium text-muted-foreground">Режим повтора</span>
                <select value={videoScenario} onChange={(event) => setVideoScenario(event.target.value as ScenarioType)} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {(state.videoModels.find((item) => item.id === model)?.supports || ['text']).map((scenario) => (
                    <option key={scenario} value={scenario}>{scenario === 'imgtxt' ? 'Фото + текст' : scenario === 'text' ? 'Текст → видео' : scenario}</option>
                  ))}
                </select>
              </label>
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Длительность</span>
                <select value={videoDuration} onChange={(event) => setVideoDuration(Number(event.target.value))} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {(state.videoModels.find((item) => item.id === model)?.durations || [5]).map((duration) => (
                    <option key={duration} value={duration}>{duration} сек</option>
                  ))}
                </select>
              </label>
            </div>
          ) : null}

          <div className="space-y-2">
            <span className="text-xs font-medium text-muted-foreground">
              {trendKind === 'video' ? 'Видео-пример шаблона' : 'Preview шаблона'}
            </span>
            <input
              ref={fileInputRef}
              type="file"
              accept={
                trendKind === 'video'
                  ? 'video/mp4,video/webm,video/quicktime'
                  : 'image/jpeg,image/png,image/webp'
              }
              className="hidden"
              onChange={(event) => void handlePreviewUpload(event.target.files?.[0])}
            />
            {previewUrl ? (
              <div className="relative overflow-hidden rounded-2xl border border-border/50 bg-secondary/40">
                {trendKind === 'video' ? (
                  <video
                    src={previewUrl}
                    controls
                    muted
                    playsInline
                    preload="metadata"
                    className="h-auto max-h-[70vh] w-full bg-black object-contain"
                  />
                ) : (
                  <img
                    src={previewUrl}
                    alt="Preview тренда"
                    className="aspect-square w-full object-cover"
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
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploadingPreview}
                className="flex aspect-[16/9] w-full flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border/70 bg-secondary/35 text-sm text-muted-foreground transition-colors hover:border-gold/40 hover:text-foreground"
              >
                {uploadingPreview ? (
                  <Loader2 className="h-6 w-6 animate-spin" />
                ) : trendKind === 'video' ? (
                  <Film className="h-7 w-7" />
                ) : (
                  <ImagePlus className="h-7 w-7" />
                )}
                {uploadingPreview
                  ? 'Загружаю…'
                  : trendKind === 'video'
                    ? 'Загрузить видео'
                    : 'Загрузить изображение'}
              </button>
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

      <Dialog open={Boolean(previewTrend)} onOpenChange={(open) => { if (!open) setPreviewTrend(null) }}>
        <DialogContent className="max-w-3xl border-border/60 bg-background p-3">
          <DialogTitle className="pr-8 text-sm">{previewTrend?.title || 'Видео-тренд'}</DialogTitle>
          {previewTrend?.preview_url ? (
            <video
              src={previewTrend.preview_url}
              controls
              autoPlay
              playsInline
              onLoadedMetadata={(event) => rememberVideoAspectRatio(previewTrend.id, event.currentTarget)}
              style={{ aspectRatio: videoAspectRatios[previewTrend.id] || '16 / 9' }}
              className="max-h-[78vh] w-full rounded-xl bg-black object-contain"
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}
