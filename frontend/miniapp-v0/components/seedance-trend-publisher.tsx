'use client'

import { useEffect, useMemo, useState } from 'react'
import { Check, Flame, Loader2, LockKeyhole, UserRound } from 'lucide-react'
import { toast } from 'sonner'

import type { TaskDetail } from '@/lib/types'
import {
  fetchSeedanceTrendSource,
  publishSeedanceTrend,
  type SeedanceTrendReferenceItem,
  type SeedanceTrendSource,
} from '@/lib/seedance-trend-admin-api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'

interface SeedanceTrendPublisherProps {
  task: TaskDetail
}

function toggled(values: Set<number>, index: number): Set<number> {
  const next = new Set(values)
  if (next.has(index)) next.delete(index)
  else next.add(index)
  return next
}

function ordered(values: Set<number>): number[] {
  return [...values].sort((left, right) => left - right)
}

function MediaHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="flex items-center justify-between">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{label}</p>
      <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-muted-foreground">{count}</span>
    </div>
  )
}

export function SeedanceTrendPublisher({ task }: SeedanceTrendPublisherProps) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [source, setSource] = useState<SeedanceTrendSource | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [identityIndex, setIdentityIndex] = useState<number | null>(null)
  const [fixedImages, setFixedImages] = useState<Set<number>>(new Set())
  const [fixedVideos, setFixedVideos] = useState<Set<number>>(new Set())
  const [fixedAudios, setFixedAudios] = useState<Set<number>>(new Set())
  const [replaceableImages, setReplaceableImages] = useState<Set<number>>(new Set())
  const [replaceableVideos, setReplaceableVideos] = useState<Set<number>>(new Set())
  const [replaceableAudios, setReplaceableAudios] = useState<Set<number>>(new Set())

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setSource(null)
    void fetchSeedanceTrendSource(task.task_id)
      .then((nextSource) => {
        if (cancelled) return
        const suggestedIdentity =
          nextSource.references.images.find((item) => item.default_action === 'replace_with_user')?.index ??
          nextSource.references.images[0]?.index ??
          null
        setSource(nextSource)
        setTitle(`Повтори образ · ${task.model_label}`.slice(0, 80))
        setDescription('Загрузите свои файлы в отмеченные слоты. Закреплённые детали применятся автоматически.')
        setIdentityIndex(suggestedIdentity)
        setFixedImages(
          new Set(
            nextSource.references.images
              .filter((item) => item.index !== suggestedIdentity && item.default_action === 'keep_hidden')
              .map((item) => item.index),
          ),
        )
        setFixedVideos(new Set(nextSource.references.videos.map((item) => item.index)))
        setFixedAudios(new Set(nextSource.references.audios.map((item) => item.index)))
        setReplaceableImages(new Set())
        setReplaceableVideos(new Set())
        setReplaceableAudios(new Set())
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : 'Не удалось открыть референсы')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, task.model_label, task.task_id])

  const fixedCount = fixedImages.size + fixedVideos.size + fixedAudios.size
  const replaceableCount = replaceableImages.size + replaceableVideos.size + replaceableAudios.size
  const canPublish = useMemo(
    () => Boolean(source && identityIndex && fixedCount + replaceableCount > 0 && title.trim() && !loading && !saving),
    [fixedCount, identityIndex, loading, replaceableCount, saving, source, title],
  )

  const chooseIdentity = (index: number) => {
    if (saving) return
    setIdentityIndex(index)
    setFixedImages((current) => {
      const next = new Set(current)
      next.delete(index)
      return next
    })
    setReplaceableImages((current) => {
      const next = new Set(current)
      next.delete(index)
      return next
    })
    setError(null)
  }

  const submit = async () => {
    if (!source || !identityIndex || !canPublish) return
    setSaving(true)
    setError(null)
    try {
      await publishSeedanceTrend({
        taskId: source.task_id,
        title: title.trim(),
        description: description.trim(),
        identityImageIndex: identityIndex,
        fixedImageIndices: ordered(fixedImages),
        fixedVideoIndices: ordered(fixedVideos),
        fixedAudioIndices: ordered(fixedAudios),
        replaceableImageIndices: ordered(replaceableImages),
        replaceableVideoIndices: ordered(replaceableVideos),
        replaceableAudioIndices: ordered(replaceableAudios),
      })
      toast.success('Seedance-тренд опубликован')
      setOpen(false)
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Не удалось опубликовать тренд'
      setError(message)
      toast.error(message)
    } finally {
      setSaving(false)
    }
  }

  const renderImage = (item: SeedanceTrendReferenceItem) => {
    const identity = identityIndex === item.index
    const fixed = fixedImages.has(item.index)
    const replaceable = replaceableImages.has(item.index)
    return (
      <div key={item.index} className="overflow-hidden rounded-xl border border-border/60 bg-secondary/35">
        <img src={item.preview_url} alt={`Исходный @Image${item.index}`} className="aspect-square w-full object-cover" />
        <div className="space-y-1.5 p-2">
          <p className="text-[11px] font-semibold text-foreground">Исходный @Image{item.index}</p>
          <button
            type="button"
            disabled={saving}
            onClick={() => chooseIdentity(item.index)}
            className={cn(
              'flex w-full items-center gap-1.5 rounded-lg border px-2 py-1.5 text-left text-[10px] transition',
              identity
                ? 'border-cyan/50 bg-cyan/10 text-cyan'
                : 'border-border/50 bg-background/45 text-muted-foreground',
            )}
          >
            <UserRound className="h-3.5 w-3.5" />
            {identity ? 'Лицо заменяем' : 'Сделать лицом'}
          </button>
          <button
            type="button"
            disabled={saving || identity}
            onClick={() => {
              setFixedImages((current) => toggled(current, item.index))
              setReplaceableImages((current) => {
                const next = new Set(current)
                next.delete(item.index)
                return next
              })
            }}
            className={cn(
              'flex w-full items-center gap-1.5 rounded-lg border px-2 py-1.5 text-left text-[10px] transition disabled:cursor-not-allowed disabled:opacity-45',
              fixed
                ? 'border-gold/50 bg-gold/10 text-gold'
                : 'border-border/50 bg-background/45 text-muted-foreground',
            )}
          >
            {fixed ? <Check className="h-3.5 w-3.5" /> : <LockKeyhole className="h-3.5 w-3.5" />}
            {fixed ? 'Скрыт, без замены' : replaceable ? 'Закрепить без замены' : 'Не использовать'}
          </button>
          <button
            type="button"
            disabled={saving || identity}
            onClick={() => {
              setReplaceableImages((current) => toggled(current, item.index))
              setFixedImages((current) => {
                const next = new Set(current)
                next.delete(item.index)
                return next
              })
            }}
            className={cn(
              'flex w-full items-center gap-1.5 rounded-lg border px-2 py-1.5 text-left text-[10px] transition disabled:cursor-not-allowed disabled:opacity-45',
              replaceable
                ? 'border-cyan/50 bg-cyan/10 text-cyan'
                : 'border-border/50 bg-background/45 text-muted-foreground',
            )}
          >
            <UserRound className="h-3.5 w-3.5" />
            {replaceable ? 'Скрыт, пользователь заменяет' : 'Скрыть и разрешить замену'}
          </button>
        </div>
      </div>
    )
  }

  const renderFixedMedia = (
    item: SeedanceTrendReferenceItem,
    kind: 'video' | 'audio',
    values: Set<number>,
    setValues: React.Dispatch<React.SetStateAction<Set<number>>>,
    replaceableValues: Set<number>,
    setReplaceableValues: React.Dispatch<React.SetStateAction<Set<number>>>,
  ) => {
    const fixed = values.has(item.index)
    const replaceable = replaceableValues.has(item.index)
    return (
      <div key={`${kind}-${item.index}`} className="rounded-xl border border-border/60 bg-secondary/35 p-2">
        {kind === 'video' ? (
          <video src={item.preview_url} controls playsInline preload="metadata" className="mb-2 aspect-video w-full rounded-lg bg-black object-contain" />
        ) : (
          <audio src={item.preview_url} controls preload="metadata" className="mb-2 w-full" />
        )}
        <button
          type="button"
          disabled={saving}
          onClick={() => {
            setValues((current) => toggled(current, item.index))
            setReplaceableValues((current) => {
              const next = new Set(current)
              next.delete(item.index)
              return next
            })
          }}
          className={cn(
            'flex w-full items-center justify-center gap-1.5 rounded-lg border px-2 py-2 text-[11px] transition',
            fixed
              ? 'border-gold/50 bg-gold/10 text-gold'
              : 'border-border/50 bg-background/45 text-muted-foreground',
          )}
        >
          {fixed ? <Check className="h-3.5 w-3.5" /> : <LockKeyhole className="h-3.5 w-3.5" />}
          @{kind === 'video' ? 'Video' : 'Audio'}{item.index} · {fixed ? 'скрыт, без замены' : replaceable ? 'закрепить без замены' : 'исключён'}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => {
            setReplaceableValues((current) => toggled(current, item.index))
            setValues((current) => {
              const next = new Set(current)
              next.delete(item.index)
              return next
            })
          }}
          className={cn(
            'mt-1.5 flex w-full items-center justify-center gap-1.5 rounded-lg border px-2 py-2 text-[11px] transition',
            replaceable
              ? 'border-cyan/50 bg-cyan/10 text-cyan'
              : 'border-border/50 bg-background/45 text-muted-foreground',
          )}
        >
          <UserRound className="h-3.5 w-3.5" />
          {replaceable ? 'Скрыт, пользователь заменяет' : 'Скрыть и разрешить замену'}
        </button>
      </div>
    )
  }

  return (
    <>
      <Button type="button" variant="secondary" className="w-full" onClick={() => setOpen(true)}>
        <Flame className="h-4 w-4" />
        Сделать Seedance-трендом
      </Button>
      <Dialog open={open} onOpenChange={(next) => !saving && setOpen(next)}>
        <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Тренд из готовой Seedance-генерации</DialogTitle>
            <DialogDescription>
              Выберите фото для замены лица. Для остальных фото, видео и аудио можно выбрать: скрыть без замены или скрыть и разрешить пользователю загрузить свой файл. Оригиналы не показываются при повторе.
            </DialogDescription>
          </DialogHeader>

          {loading ? (
            <div className="flex min-h-48 items-center justify-center text-muted-foreground">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : error && !source ? (
            <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>
          ) : source ? (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1.5">
                  <span className="text-xs font-medium text-muted-foreground">Название</span>
                  <input
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    maxLength={80}
                    className="h-10 w-full rounded-lg border border-border/60 bg-secondary/45 px-3 text-sm outline-none focus:border-gold/50"
                  />
                </label>
                <div className="rounded-lg border border-border/50 bg-secondary/35 p-3 text-xs text-muted-foreground">
                  <p>Модель: <span className="font-semibold text-foreground">{source.model}</span></p>
                  <p>Формат: <span className="font-semibold text-foreground">{source.aspect_ratio || 'adaptive'}</span></p>
                  <p>Закреплено: <span className="font-semibold text-foreground">{fixedCount}</span></p>
                </div>
              </div>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-muted-foreground">Описание для пользователя</span>
                <Textarea value={description} onChange={(event) => setDescription(event.target.value)} maxLength={240} className="min-h-20" />
              </label>

              <div className="space-y-2">
                <MediaHeader label="Фото-референсы" count={source.references.images.length} />
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{source.references.images.map(renderImage)}</div>
              </div>

              {source.references.videos.length ? (
                <div className="space-y-2">
                  <MediaHeader label="Видео-референсы" count={source.references.videos.length} />
                  <div className="grid gap-2 sm:grid-cols-2">
                    {source.references.videos.map((item) => renderFixedMedia(item, 'video', fixedVideos, setFixedVideos, replaceableVideos, setReplaceableVideos))}
                  </div>
                </div>
              ) : null}

              {source.references.audios.length ? (
                <div className="space-y-2">
                  <MediaHeader label="Аудио-референсы" count={source.references.audios.length} />
                  <div className="grid gap-2">
                    {source.references.audios.map((item) => renderFixedMedia(item, 'audio', fixedAudios, setFixedAudios, replaceableAudios, setReplaceableAudios))}
                  </div>
                </div>
              ) : null}

              <div className="rounded-xl border border-gold/25 bg-gold/5 p-3 text-xs leading-relaxed text-muted-foreground">
                В повторе лицо пользователя станет <strong className="text-foreground">@Image1</strong>. Закреплённые фото получат @Image2 и далее; @Video и @Audio сохранят независимую нумерацию.
              </div>
              {error ? <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</div> : null}
            </div>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" disabled={saving} onClick={() => setOpen(false)}>Отмена</Button>
            <Button type="button" disabled={!canPublish} onClick={() => void submit()}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Flame className="h-4 w-4" />}
              Опубликовать тренд
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
