'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '@/lib/app-context'
import { notifyFeedChanged } from '@/lib/feed-events'
import { cn } from '@/lib/utils'
import { 
  X, Image, Video, Clock, Check, CheckCircle2, XCircle,
  Banana, ExternalLink, Copy, RefreshCw, Headphones, UserRound, Images, BookOpen, Eye, EyeOff, ShieldAlert
} from 'lucide-react' 
import { motion, AnimatePresence } from 'framer-motion'
import { Button } from '@/components/ui/button'
import {
  publishGeneration,
  removeGenerationPrompt,
  saveGenerationPrompt,
  unpublishGeneration,
} from '@/lib/api'
import { toast } from 'sonner'
import { copyTextToClipboard } from '@/lib/clipboard'
import { SeedanceTrendPublisher } from '@/components/seedance-trend-publisher'

const EMPTY_REFERENCE_URLS: string[] = []

export function TaskDetailPanel() {
  const { state, taskDetail, isTaskDetailOpen, closeTaskDetail, updateTask } = useApp()
  const [publishBusy, setPublishBusy] = useState(false)
  const [libraryBusy, setLibraryBusy] = useState(false)
  const [feedPromptVisible, setFeedPromptVisible] = useState(false)
  const [feedReferencesVisible, setFeedReferencesVisible] = useState(false)
  const [feedBlurred, setFeedBlurred] = useState(false)
  const [publicationScope, setPublicationScope] = useState<'profile' | 'feed'>('feed')
  const [adultContent, setAdultContent] = useState(false)
  const [publicationEditorOpen, setPublicationEditorOpen] = useState(false)
  const [publicationLink, setPublicationLink] = useState<string | null>(null)
  const [selectedReferenceImages, setSelectedReferenceImages] = useState<Set<number>>(new Set())
  const [selectedReferenceVideos, setSelectedReferenceVideos] = useState<Set<number>>(new Set())
  const [selectedRepeatReferenceImages, setSelectedRepeatReferenceImages] = useState<Set<number>>(new Set())
  const publicationSourceRef = useRef<{ taskId?: string; repeatImages: number[] }>({ repeatImages: [] })

  const publicationReferenceImages = taskDetail?.publication_reference_images
    ?? taskDetail?.request_data?.source_reference_images
    ?? taskDetail?.request_data?.reference_images
    ?? EMPTY_REFERENCE_URLS
  const publicationReferenceVideos = taskDetail?.publication_reference_videos
    ?? taskDetail?.request_data?.v_reference_videos
    ?? EMPTY_REFERENCE_URLS
  const publicationReferenceImageIndices = useMemo(
    () => taskDetail?.publication_reference_image_indices
      ?? publicationReferenceImages.map((_, index) => index),
    [taskDetail?.publication_reference_image_indices, publicationReferenceImages],
  )
  const publicationReferenceVideoIndices = useMemo(
    () => taskDetail?.publication_reference_video_indices
      ?? publicationReferenceVideos.map((_, index) => index),
    [taskDetail?.publication_reference_video_indices, publicationReferenceVideos],
  )
  const referenceCount = publicationReferenceImages.length + publicationReferenceVideos.length
  const selectedReferenceCount = selectedReferenceImages.size + selectedReferenceVideos.size

  useEffect(() => {
    const previousSource = publicationSourceRef.current
    const taskChanged = previousSource.taskId !== taskDetail?.task_id
    const savedRepeatImages = taskDetail?.feed_repeat_reference_selection?.images ?? []
    publicationSourceRef.current = {
      taskId: taskDetail?.task_id,
      repeatImages: [...savedRepeatImages],
    }

    if (!taskChanged && isTaskDetailOpen && publicationEditorOpen) {
      // Polling/focus refreshes replace arrays even when their contents are equal.
      // Keep the author's active draft, but never retain unavailable/revoked refs.
      const revokedImages = new Set(
        previousSource.repeatImages.filter((index) => !savedRepeatImages.includes(index)),
      )
      setSelectedRepeatReferenceImages((current) => {
        const retained = new Set(taskDetail?.type === 'image'
          ? [...current].filter((index) =>
            publicationReferenceImageIndices.includes(index) && !revokedImages.has(index),
          )
          : [])
        return retained.size === current.size ? current : retained
      })
      return
    }

    setFeedPromptVisible(Boolean(taskDetail?.feed_prompt_visible))
    setFeedReferencesVisible(Boolean(taskDetail?.feed_references_visible))
    setFeedBlurred(Boolean(taskDetail?.feed_blurred))
    setPublicationScope(taskDetail?.publication_scope === 'profile' ? 'profile' : 'feed')
    setAdultContent(Boolean(taskDetail?.is_adult_content))
    const savedSelection = taskDetail?.feed_reference_selection
    setSelectedReferenceImages(new Set(savedSelection?.images ?? publicationReferenceImageIndices))
    setSelectedReferenceVideos(new Set(savedSelection?.videos ?? publicationReferenceVideoIndices))
    // Public visibility and legacy display selections never imply repeat consent.
    setSelectedRepeatReferenceImages(new Set(
      taskDetail?.type === 'image'
        ? savedRepeatImages.filter((index) => publicationReferenceImageIndices.includes(index))
        : [],
    ))
    if (taskChanged || !isTaskDetailOpen) {
      setPublicationEditorOpen(false)
      setPublicationLink(null)
    }
  }, [
    taskDetail?.task_id,
    taskDetail?.type,
    taskDetail?.feed_prompt_visible,
    taskDetail?.feed_references_visible,
    taskDetail?.feed_blurred,
    taskDetail?.publication_scope,
    taskDetail?.is_adult_content,
    taskDetail?.feed_reference_selection,
    taskDetail?.feed_repeat_reference_selection,
    publicationReferenceImageIndices,
    publicationReferenceVideoIndices,
    publicationEditorOpen,
    isTaskDetailOpen,
  ])

  const toggleReference = (
    index: number,
    setSelected: React.Dispatch<React.SetStateAction<Set<number>>>,
  ) => {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  const confirmPublication = (target: string) => {
    if (typeof window === 'undefined') return true
    return window.confirm(
      `Публикация в ${target}\n\n` +
        'Вы подтверждаете, что у вас есть права или согласие на исходники, результат и текст промпта.\n\n' +
        'Ответственность за опубликованный пользовательский контент несёт пользователь. Администрация бота не проводит предварительную модерацию и не отвечает за материалы, которые пользователи выкладывают самостоятельно.\n\n' +
        'Спорный материал может быть удалён по жалобе правообладателя или другого заинтересованного лица.'
    )
  }

  const handleCopyTaskId = async () => {
    if (!taskDetail || typeof navigator === 'undefined') return
    try {
      await navigator.clipboard.writeText(taskDetail.task_id)
    } catch {
      // Ignore clipboard failures in constrained webviews
    }
  }

  const handleCopyPrompt = async () => {
    if (!taskDetail?.prompt || taskDetail.prompt_hidden || typeof navigator === 'undefined') return
    try {
      await navigator.clipboard.writeText(taskDetail.prompt)
    } catch {
      // Ignore clipboard failures in constrained webviews
    }
  }

  const isPublished = Boolean(taskDetail?.is_profile_visible || taskDetail?.is_public_feed)
  const canCopyPrompt = Boolean(taskDetail?.prompt && !taskDetail?.prompt_hidden)

  const handlePublish = async () => {
    if (!taskDetail || publishBusy) return
    const target = publicationScope === 'profile' ? 'свой профиль' : 'ленту и свой профиль'
    if (!isPublished && !confirmPublication(target)) return
    setPublishBusy(true)
    try {
      const published = await publishGeneration(taskDetail.task_id, {
          promptVisible: feedPromptVisible,
          referencesVisible: feedReferencesVisible,
          referenceImageIndices: [...selectedReferenceImages].sort((left, right) => left - right),
          referenceVideoIndices: [...selectedReferenceVideos].sort((left, right) => left - right),
          ...(taskDetail.type === 'image' ? {
            repeatReferenceImageIndices: [...selectedRepeatReferenceImages].sort((left, right) => left - right),
          } : {}),
          blurred: feedBlurred,
          publicationScope,
          adultContent,
        })
        updateTask(taskDetail.task_id, {
          is_public_feed: published.publication_scope === 'feed',
          is_profile_visible: true,
          publication_scope: published.publication_scope,
          is_adult_content: Boolean(published.is_adult_content),
          feed_interactions_enabled: published.feed_interactions_enabled,
          feed_prompt_visible: feedPromptVisible,
          feed_references_visible: Boolean(published.feed_references_visible),
          feed_reference_selection: {
            images: [...selectedReferenceImages].sort((left, right) => left - right),
            videos: [...selectedReferenceVideos].sort((left, right) => left - right),
          },
          ...(taskDetail.type === 'image' ? {
            feed_repeat_reference_selection: {
              images: [...selectedRepeatReferenceImages].sort((left, right) => left - right),
            },
          } : {}),
          feed_blurred: Boolean(published.feed_blurred),
        })
        notifyFeedChanged(published)
        setPublicationLink(published.publication_link || null)
        setPublicationEditorOpen(false)
        toast.success(
          published.publication_scope === 'profile'
            ? 'Опубликовано только в профиле'
            : 'Опубликовано в ленте и профиле'
        )
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось опубликовать')
    } finally {
      setPublishBusy(false)
    }
  }

  const handleUnpublish = async () => {
    if (!taskDetail || publishBusy || !isPublished) return
    setPublishBusy(true)
    try {
      await unpublishGeneration(taskDetail.task_id)
      updateTask(taskDetail.task_id, {
        is_public_feed: false,
        is_profile_visible: false,
        publication_scope: 'private',
        is_adult_content: false,
        ...(taskDetail.type === 'image' ? {
          feed_repeat_reference_selection: { images: [] },
        } : {}),
      })
      setSelectedRepeatReferenceImages(new Set())
      setPublicationLink(null)
      setPublicationEditorOpen(false)
      notifyFeedChanged()
      toast.success('Публикация убрана')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось убрать публикацию')
    } finally {
      setPublishBusy(false)
    }
  }

  const handleCopyPublicationLink = async () => {
    if (!publicationLink) return
    try {
      await copyTextToClipboard(publicationLink)
      toast.success('Ссылка скопирована')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось скопировать ссылку')
    }
  }

  const handleSavePrompt = async () => {
    if (!taskDetail || libraryBusy) return
    if (!taskDetail.is_prompt_library && !confirmPublication('ленту промптов')) return
    setLibraryBusy(true)
    try {
      if (taskDetail.is_prompt_library) {
        await removeGenerationPrompt(taskDetail.task_id)
        updateTask(taskDetail.task_id, { is_prompt_library: false })
        toast.success('Убрано из промптов')
      } else {
        await saveGenerationPrompt(taskDetail.task_id)
        updateTask(taskDetail.task_id, { is_prompt_library: true })
        toast.success('Промпт сохранён')
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сохранить prompt')
    } finally {
      setLibraryBusy(false)
    }
  }

  const canPublishToFeed = Boolean(
    taskDetail &&
      (taskDetail.type === 'image' || taskDetail.type === 'video') &&
      taskDetail.prompt_actions_allowed !== false &&
      !taskDetail.prompt_hidden
  )
  const canSavePrompt = Boolean(
    taskDetail &&
      taskDetail.type === 'image' &&
      taskDetail.prompt_actions_allowed !== false &&
      !taskDetail.prompt_hidden
  )

  const canPublishSeedanceTrend = Boolean(
    state.user.isAdmin &&
      taskDetail &&
      taskDetail.type === 'video' &&
      taskDetail.status === 'completed' &&
      taskDetail.result_url &&
      (taskDetail.model === 'seedance_2' || taskDetail.model === 'seedance_2_5') &&
      taskDetail.prompt_actions_allowed !== false &&
      !taskDetail.prompt_hidden
  )

  return (
    <AnimatePresence>
      {isTaskDetailOpen && taskDetail && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={closeTaskDetail}
            className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50"
          />

          {/* Panel */}
          <motion.div
            initial={{ opacity: 0, y: '100%' }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: '100%' }}
            transition={{ 
              type: 'spring', 
              damping: 30, 
              stiffness: 300,
              mass: 0.8,
            }}
            className={cn(
              "fixed bottom-0 left-0 right-0 z-50",
              "max-h-[85vh] overflow-auto",
              "glass-strong rounded-t-3xl border-t border-border/50",
              "safe-bottom"
            )}
          >
            {/* Handle */}
            <div className="sticky top-0 z-10 flex justify-center pt-3 pb-2 bg-inherit">
              <div className="w-10 h-1 rounded-full bg-border" />
            </div>

            {/* Header */}
            <div className="flex items-center justify-between px-5 pb-4">
              <h2 className="font-serif text-xl font-semibold text-foreground">
                Детали задачи
              </h2>
              <button
                onClick={closeTaskDetail}
                className="w-8 h-8 rounded-full bg-secondary/80 flex items-center justify-center hover:bg-secondary transition-colors"
              >
                <X className="w-4 h-4 text-muted-foreground" />
              </button>
            </div>

            {/* Content */}
            <div className="px-5 pb-6 space-y-5">
              {/* Preview */}
              {taskDetail.result_url && taskDetail.status === 'completed' && taskDetail.type === 'image' && (
                <div className="relative aspect-square rounded-2xl overflow-hidden bg-secondary/50">
                  <img
                    src={taskDetail.result_url}
                    alt="Результат"
                    className="w-full h-full object-cover"
                  />
                </div>
              )}

              {taskDetail.result_url && taskDetail.status === 'completed' && taskDetail.type === 'video' && (
                <div className="relative aspect-video rounded-2xl overflow-hidden bg-secondary/50">
                  <video
                    src={taskDetail.result_url}
                    className="w-full h-full object-cover"
                    controls
                    playsInline
                  />
                </div>
              )}

              {taskDetail.result_url && taskDetail.status === 'completed' && (taskDetail.type === 'audio' || taskDetail.type === 'character') && (
                <div className="rounded-2xl border border-border/50 bg-secondary/50 p-4">
                  <p className="mb-2 text-xs text-muted-foreground">
                    {taskDetail.type === 'audio' ? 'Audio ID' : 'Character ID'}
                  </p>
                  <code className="block break-all font-mono text-sm text-foreground">
                    {taskDetail.result_url}
                  </code>
                </div>
              )}

              {/* Pending state */}
              {taskDetail.status === 'pending' && (
                <div className="relative aspect-video rounded-2xl overflow-hidden bg-secondary/50 flex flex-col items-center justify-center">
                  <div className="w-16 h-16 rounded-2xl bg-gold/10 flex items-center justify-center mb-4">
                    <RefreshCw className="w-8 h-8 text-gold animate-spin" />
                  </div>
                  <p className="text-sm font-medium text-foreground mb-1">
                    Генерация в процессе
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Статус обновляется автоматически
                  </p>
                </div>
              )}

              {/* Info grid */}
              <div className="grid grid-cols-2 gap-3">
                <InfoItem 
                  label="Модель" 
                  value={taskDetail.model_label} 
                />
                <InfoItem 
                  label="Тип" 
                  value={
                    taskDetail.type === 'image'
                      ? 'Фото'
                      : taskDetail.type === 'audio'
                        ? 'Audio ID'
                        : taskDetail.type === 'character'
                          ? 'Character ID'
                          : 'Видео'
                  }
                  icon={taskDetail.type === 'image' ? Image : taskDetail.type === 'audio' ? Headphones : taskDetail.type === 'character' ? UserRound : Video}
                />
                <InfoItem 
                  label="Формат" 
                  value={taskDetail.aspect_ratio} 
                />
                <InfoItem 
                  label="Статус" 
                  value={
                    taskDetail.status === 'pending' ? 'В обработке' :
                    taskDetail.status === 'completed' ? 'Готово' : 'Ошибка'
                  }
                  icon={
                    taskDetail.status === 'pending' ? Clock :
                    taskDetail.status === 'completed' ? CheckCircle2 : XCircle
                  }
                  statusColor={
                    taskDetail.status === 'pending' ? 'text-gold' :
                    taskDetail.status === 'completed' ? 'text-success' : 'text-destructive'
                  }
                />
                <InfoItem 
                  label="Стоимость" 
                  value={`${taskDetail.cost}`}
                  icon={Banana}
                  statusColor="text-gold"
                />
                <InfoItem
                  label="Референсы"
                  value={`${taskDetail.request_data?.reference_images?.length || 0}`}
                />
                {taskDetail.request_data?.v_reference_videos && (
                  <InfoItem
                    label="Видео-референсы"
                    value={`${taskDetail.request_data.v_reference_videos.length}`}
                  />
                )}
                {taskDetail.duration && (
                  <InfoItem 
                    label="Длительность" 
                    value={`${taskDetail.duration} сек.`} 
                  />
                )}
              </div>

              {/* Task ID */}
              <div className="flex items-center gap-2 p-3 rounded-xl bg-secondary/50">
                <span className="text-xs text-muted-foreground">ID:</span>
                <code className="text-xs text-foreground font-mono flex-1 truncate">
                  {taskDetail.task_id}
                </code>
                <button
                  onClick={handleCopyTaskId}
                  className="text-muted-foreground hover:text-foreground transition-colors"
                >
                  <Copy className="w-4 h-4" />
                </button>
              </div>

              {/* Prompt */}
              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-medium text-foreground">Промпт</h3>
                  {canCopyPrompt ? (
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      className="h-8 px-3"
                      onClick={handleCopyPrompt}
                    >
                      <Copy className="mr-2 h-4 w-4" />
                      Скопировать
                    </Button>
                  ) : null}
                </div>
                <p className="text-sm text-muted-foreground leading-relaxed p-3 rounded-xl bg-secondary/50 whitespace-pre-wrap break-words">
                  {taskDetail.prompt_hidden ? 'Описание автора уже использовано для этой работы.' : taskDetail.prompt || '—'}
                </p>
              </div>

              {/* References */}
              {taskDetail.request_data?.reference_images && taskDetail.request_data.reference_images.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-foreground mb-2">
                    Референсы ({taskDetail.request_data.reference_images.length})
                  </h3>
                  <div className="flex gap-2 overflow-x-auto pb-2">
                    {taskDetail.request_data.reference_images.map((url, i) => (
                      <div 
                        key={i}
                        className="w-20 h-20 rounded-xl overflow-hidden flex-shrink-0 bg-secondary/50"
                      >
                        <img src={url} alt="" className="w-full h-full object-cover" />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Actions */}
              {taskDetail.status === 'completed' && taskDetail.result_url && (
                <div className="space-y-2">
                  {canPublishSeedanceTrend ? <SeedanceTrendPublisher task={taskDetail} /> : null}
                  {canPublishToFeed && publicationEditorOpen ? (
                <div className="rounded-xl border border-border/50 bg-secondary/35 p-3">
                  <p className="mb-3 text-sm font-semibold text-foreground">Куда опубликовать?</p>
                  <div className="mb-3 grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      disabled={adultContent}
                      onClick={() => setPublicationScope('feed')}
                      className={cn(
                        'rounded-lg border px-3 py-2 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45',
                        publicationScope === 'feed'
                          ? 'border-cyan/40 bg-cyan/10 text-cyan'
                          : 'border-border/50 bg-background/40 text-muted-foreground'
                      )}
                    >
                      Лента и профиль
                    </button>
                    <button
                      type="button"
                      onClick={() => setPublicationScope('profile')}
                      className={cn(
                        'rounded-lg border px-3 py-2 text-xs font-medium transition-colors',
                        publicationScope === 'profile'
                          ? 'border-cyan/40 bg-cyan/10 text-cyan'
                          : 'border-border/50 bg-background/40 text-muted-foreground'
                      )}
                    >
                      Только профиль
                    </button>
                  </div>
                  {taskDetail.type === 'image' ? (
                    <button
                      type="button"
                      onClick={() => {
                        setAdultContent((current) => {
                          const next = !current
                          if (next) {
                            setPublicationScope('profile')
                          }
                          return next
                        })
                      }}
                      className={cn(
                        'mb-3 flex w-full items-start gap-2 rounded-lg border p-3 text-left transition-colors',
                        adultContent
                          ? 'border-destructive/40 bg-destructive/10 text-destructive'
                          : 'border-border/50 bg-background/40 text-muted-foreground'
                      )}
                    >
                      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>
                        <span className="block text-xs font-semibold">Контент 18+</span>
                        <span className="mt-0.5 block text-[11px] leading-relaxed">
                          Публикуется только в профиле. Blur включается отдельно по вашему выбору.
                        </span>
                      </span>
                    </button>
                  ) : null}
                  <h3 className="mb-2 text-xs font-semibold text-foreground">Что показать в публикации</h3>
                  <div className="grid grid-cols-3 gap-2">
                        <button
                          type="button"
                          onClick={() => setFeedPromptVisible((prev) => !prev)}
                          className={cn(
                            'flex h-10 items-center justify-center gap-2 rounded-lg border px-3 text-xs font-medium transition-colors',
                            feedPromptVisible
                              ? 'border-cyan/40 bg-cyan/10 text-cyan'
                              : 'border-border/50 bg-background/40 text-muted-foreground'
                          )}
                        >
                          {feedPromptVisible ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                          Prompt
                        </button>
                        <button
                          type="button"
                          disabled={referenceCount === 0}
                          onClick={() => setFeedReferencesVisible((prev) => !prev)}
                          className={cn(
                            'flex h-10 items-center justify-center gap-2 rounded-lg border px-3 text-xs font-medium transition-colors disabled:opacity-50',
                            feedReferencesVisible
                              ? 'border-cyan/40 bg-cyan/10 text-cyan'
                              : 'border-border/50 bg-background/40 text-muted-foreground'
                          )}
                        >
                          {feedReferencesVisible ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                          Рефы {referenceCount ? `(${feedReferencesVisible ? selectedReferenceCount : referenceCount})` : ''}
                        </button>
                        <button
                          type="button"
                          onClick={() => setFeedBlurred((prev) => !prev)}
                          className={cn(
                            'flex h-10 items-center justify-center gap-2 rounded-lg border px-3 text-xs font-medium transition-colors',
                            feedBlurred
                              ? 'border-cyan/40 bg-cyan/10 text-cyan'
                              : 'border-border/50 bg-background/40 text-muted-foreground'
                          )}
                        >
                          {feedBlurred ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                          Blur
                        </button>
                      </div>
                  {feedReferencesVisible && referenceCount > 0 ? (
                    <div className="mt-3 rounded-lg border border-border/50 bg-background/30 p-2.5">
                      <div className="mb-2 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                        <span>Референсы в публикации</span>
                        <span>{selectedReferenceCount} из {referenceCount}</span>
                      </div>
                      <div className="flex gap-2 overflow-x-auto pb-1">
                        {publicationReferenceImages.map((url, index) => {
                          const sourceIndex = publicationReferenceImageIndices[index]
                          const selected = selectedReferenceImages.has(sourceIndex)
                          return (
                            <div key={`image-${index}`} className={cn('relative h-20 w-20 shrink-0 overflow-hidden rounded-lg border', selected ? 'border-cyan/50' : 'border-border/40 opacity-45')}>
                              <img src={url} alt={`Фото-референс ${index + 1}`} className="h-full w-full object-cover" />
                              <button
                                type="button"
                                aria-label={`${selected ? 'Исключить' : 'Вернуть'} фото-референс ${index + 1}`}
                                onClick={() => toggleReference(sourceIndex, setSelectedReferenceImages)}
                                className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-background/85 text-foreground"
                              >
                                {selected ? <X className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                              </button>
                            </div>
                          )
                        })}
                        {publicationReferenceVideos.map((url, index) => {
                          const sourceIndex = publicationReferenceVideoIndices[index]
                          const selected = selectedReferenceVideos.has(sourceIndex)
                          return (
                            <div key={`video-${index}`} className={cn('relative h-20 w-28 shrink-0 overflow-hidden rounded-lg border bg-secondary/60', selected ? 'border-cyan/50' : 'border-border/40 opacity-45')}>
                              <video src={url} aria-label={`Видео-референс ${index + 1}`} muted playsInline className="h-full w-full object-cover" />
                              <button
                                type="button"
                                aria-label={`${selected ? 'Исключить' : 'Вернуть'} видео-референс ${index + 1}`}
                                onClick={() => toggleReference(sourceIndex, setSelectedReferenceVideos)}
                                className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-background/85 text-foreground"
                              >
                                {selected ? <X className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                              </button>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ) : null}
                  {taskDetail.type === 'image' ? (
                    <div
                      role="group"
                      aria-labelledby="repeat-reference-permission-heading"
                      className="mt-3 rounded-lg border border-border/50 bg-background/30 p-3"
                    >
                      <h3 id="repeat-reference-permission-heading" className="text-xs font-semibold text-foreground">
                        Референсы для повторов
                      </h3>
                      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                        Выберите фото, которые разрешаете использовать при чужих повторах.
                        Для повтора они используются только на сервере: их превью и ссылки не передаются другим пользователям.
                        Показ референсов в публикации настраивается отдельно выше.
                      </p>
                      {publicationReferenceImages.length > 0 ? (
                        <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
                          {publicationReferenceImages.map((url, index) => {
                            const sourceIndex = publicationReferenceImageIndices[index]
                            const selected = selectedRepeatReferenceImages.has(sourceIndex)
                            return (
                              <button
                                key={`repeat-image-${sourceIndex}`}
                                type="button"
                                role="checkbox"
                                aria-label={`Фото-референс ${index + 1} для повторов`}
                                aria-checked={selected}
                                disabled={publishBusy}
                                onClick={() => toggleReference(sourceIndex, setSelectedRepeatReferenceImages)}
                                className={cn(
                                  'relative h-20 w-20 shrink-0 overflow-hidden rounded-lg border-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan disabled:cursor-not-allowed disabled:opacity-50',
                                  selected ? 'border-cyan' : 'border-border/50',
                                )}
                              >
                                <img src={url} alt="" className="h-full w-full object-cover" />
                                <span className={cn(
                                  'absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full border bg-background/90',
                                  selected ? 'border-cyan text-cyan' : 'border-border text-muted-foreground',
                                )}>
                                  {selected ? <Check className="h-4 w-4" /> : null}
                                </span>
                              </button>
                            )
                          })}
                        </div>
                      ) : (
                        <p className="mt-2 text-[11px] text-muted-foreground">Нет доступных фото-референсов.</p>
                      )}
                      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px]">
                        <span className="text-muted-foreground" aria-live="polite">
                          {selectedRepeatReferenceImages.size > 0
                            ? `Для повторов выбрано: ${selectedRepeatReferenceImages.size}`
                            : 'Приватные референсы для повторов не разрешены'}
                        </span>
                        {selectedRepeatReferenceImages.size > 0 ? (
                          <button
                            type="button"
                            disabled={publishBusy}
                            onClick={() => setSelectedRepeatReferenceImages(new Set())}
                            className="min-h-9 rounded-md px-2 text-cyan disabled:opacity-50"
                          >
                            Снять выбор
                          </button>
                        ) : null}
                      </div>
                      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                        Чтобы отозвать разрешение для будущих повторов, снимите выбор и сохраните публикацию.
                      </p>
                    </div>
                  ) : null}
                  <div className="mt-3 grid gap-2">
                    <Button type="button" disabled={publishBusy} onClick={handlePublish}>
                      {publishBusy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Images className="h-4 w-4" />}
                      {isPublished ? 'Сохранить публикацию' : 'Опубликовать'}
                    </Button>
                    {isPublished ? (
                      <Button type="button" variant="outline" disabled={publishBusy} onClick={handleUnpublish}>
                        Убрать публикацию
                      </Button>
                    ) : null}
                  </div>
                    </div>
                  ) : null}
                  {publicationLink ? (
                    <div className="grid grid-cols-2 gap-2 rounded-xl border border-border/50 bg-secondary/35 p-2">
                      <Button asChild type="button" variant="secondary" size="sm">
                        <a href={publicationLink} target="_blank" rel="noreferrer">
                          <ExternalLink className="h-4 w-4" />
                          Открыть
                        </a>
                      </Button>
                      <Button type="button" variant="secondary" size="sm" onClick={handleCopyPublicationLink}>
                        <Copy className="h-4 w-4" />
                        Скопировать
                      </Button>
                    </div>
                  ) : null}
                  {(canPublishToFeed || canSavePrompt) && (
                    <div className={cn('grid gap-2', canSavePrompt ? 'grid-cols-2' : 'grid-cols-1')}>
                      {canPublishToFeed ? (
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={publishBusy}
                        onClick={() => setPublicationEditorOpen((open) => !open)}
                      >
                        <Images className="h-4 w-4" />
                        {isPublished ? 'Настроить публикацию' : 'Опубликовать'}
                      </Button>
                      ) : null}
                      {canSavePrompt ? (
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={libraryBusy}
                        onClick={handleSavePrompt}
                      >
                        {libraryBusy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <BookOpen className="h-4 w-4" />}
                        {taskDetail.is_prompt_library ? 'Убрать из промптов' : 'В промпты'}
                      </Button>
                      ) : null}
                    </div>
                  )}
                  <Button
                    asChild
                    className="w-full bg-gold hover:bg-gold/90 text-primary-foreground"
                    size="lg"
                  >
                    <a href={taskDetail.result_url} target="_blank" rel="noreferrer">
                      <ExternalLink className="w-4 h-4 mr-2" />
                      Открыть оригинал
                    </a>
                  </Button>
                </div>
              )}

              {/* Time */}
              <p className="text-center text-xs text-muted-foreground">
                Создано: {new Date(taskDetail.created_at).toLocaleString('ru-RU')}
              </p>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

function InfoItem({ 
  label, 
  value, 
  icon: Icon,
  statusColor,
}: { 
  label: string
  value: string
  icon?: React.ComponentType<{ className?: string }>
  statusColor?: string
}) {
  return (
    <div className="p-3 rounded-xl bg-secondary/50">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <div className="flex items-center gap-1.5">
        {Icon && <Icon className={cn("w-4 h-4", statusColor || "text-foreground")} />}
        <span className={cn("text-sm font-medium", statusColor || "text-foreground")}>
          {value}
        </span>
      </div>
    </div>
  )
}
