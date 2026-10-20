'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, Film, Flame, Loader2, Pencil, Repeat2, Share2, Sparkles, Trash2 } from 'lucide-react'
import { Button } from './ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './ui/dialog'
import { normalizeMiniAppMediaUrl, videoPreviewFrameUrl } from '@/lib/media-url'
import { formatTrendRepeatPrice } from '@/lib/trend-price'
import { fetchTrendCategory, resolveGenjutsuPrices, type ShowcaseCategory, type ShowcaseTrend } from '@/lib/trend-catalog-api'

// Avoid decoding a dozen videos at once in Telegram's constrained mobile WebView.
const activePreviews = new Set<HTMLVideoElement>()
const MAX_PLAYING_PREVIEWS = 2
const VIDEO_EXTENSIONS = /\.(mp4|m4v|mov|webm|mkv|avi)(?:[?#]|$)/i

function isVideoPreview(trend: ShowcaseTrend): boolean {
  const type = trend.generation_settings?.preview_type
  if (type === 'video') return true
  if (type === 'image') return false
  // A signed or extensionless CDN URL does not tell us its media type.
  // Explicit media kind and the legacy trend-video marker are authoritative
  // when preview_type is absent; never infer from the domain or URL alone.
  if (trend.generation_settings?.kind === 'video') return true
  if (trend.category === 'video') return true
  if ((trend.tags || []).some((tag) => String(tag).toLowerCase() === 'trend-video')) return true
  return VIDEO_EXTENSIONS.test(String(trend.preview_url || ''))
}

function stopVideo(element: HTMLVideoElement | null) {
  if (!element) return
  element.pause()
  activePreviews.delete(element)
}

function LivePreview({ trend }: { trend: ShowcaseTrend }) {
  const ref = useRef<HTMLVideoElement | null>(null)
  const [visible, setVisible] = useState(false)
  const [failed, setFailed] = useState(false)
  const [documentVisible, setDocumentVisible] = useState(true)
  const video = isVideoPreview(trend)
  const poster = trend.preview_poster_url ? normalizeMiniAppMediaUrl(trend.preview_poster_url) : ''
  const preview = trend.preview_url ? normalizeMiniAppMediaUrl(trend.preview_url) : ''

  useEffect(() => {
    if (!video || !ref.current) return
    const element = ref.current
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true)
      return
    }
    const observer = new IntersectionObserver((entries) => {
      setVisible(entries[0]?.isIntersecting && entries[0].intersectionRatio >= 0.35)
    }, { threshold: [0, 0.35, 0.6], rootMargin: '120px' })
    observer.observe(element)
    return () => {
      observer.disconnect()
      stopVideo(element)
    }
  }, [video, trend.id])

  useEffect(() => {
    if (!video) return
    const onVisibility = () => setDocumentVisible(document.visibilityState === 'visible')
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [video])

  useEffect(() => {
    const element = ref.current
    if (!video || !element) return
    const reducedMotion = typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const saveData = Boolean((navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData)
    if (!visible || !documentVisible || failed || reducedMotion || saveData) {
      stopVideo(element)
      return
    }
    for (const other of activePreviews) {
      if (activePreviews.size < MAX_PLAYING_PREVIEWS) break
      stopVideo(other)
    }
    activePreviews.add(element)
    try {
      void element.play().catch(() => stopVideo(element))
    } catch {
      stopVideo(element)
    }
    return () => stopVideo(element)
  }, [video, visible, documentVisible, failed])

  if (!video) {
    return preview
      ? <img src={preview} alt="" loading="lazy" className="h-full w-full object-cover" />
      : <div className="flex h-full items-center justify-center bg-secondary/70"><Sparkles className="h-9 w-9 text-gold/70" /></div>
  }

  return (
    <>
      {poster ? <img src={poster} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover" /> : null}
      {!failed ? (
        <video
          ref={ref}
          src={visible ? videoPreviewFrameUrl(preview) : undefined}
          poster={poster || undefined}
          muted
          loop
          playsInline
          preload={visible ? 'metadata' : 'none'}
          onError={() => setFailed(true)}
          className="relative h-full w-full object-cover"
          aria-hidden="true"
        />
      ) : !poster ? (
        <div className="flex h-full items-center justify-center bg-secondary/70">
          <Film className="h-9 w-9 text-muted-foreground" />
        </div>
      ) : null}
    </>
  )
}

function successfulRepeatsLabel(count: number): string {
  const lastTwo = count % 100
  const last = count % 10
  const ending = lastTwo >= 11 && lastTwo <= 14 ? 'повторов'
    : last === 1 ? 'повтор'
      : last >= 2 && last <= 4 ? 'повтора' : 'повторов'
  return count.toLocaleString('ru-RU') + ' ' + ending
}

function LiveTile({ trend, onPreview, isAdmin, className = '' }: {
  trend: ShowcaseTrend
  onPreview: (trend: ShowcaseTrend) => void
  isAdmin: boolean
  className?: string
}) {
  return (
    <button
      type="button"
      aria-label={'Открыть тренд ' + trend.title}
      onClick={() => onPreview(trend)}
      className={'group relative block aspect-[3/4] min-w-0 shrink-0 overflow-hidden rounded-2xl border border-border/60 bg-secondary/40 text-left shadow-md transition-transform active:scale-[0.98] ' + className}
    >
      <LivePreview trend={trend} />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/85 via-black/10 to-transparent" />
      <div className="pointer-events-none absolute left-2 top-2 flex max-w-[calc(100%-4rem)] flex-col items-start gap-1">
        {trend.badge === 'new' ? (
          <span className="rounded-md bg-blue-500 px-2 py-1 text-[10px] font-semibold text-white">Новинка</span>
        ) : null}
        {isAdmin === true && typeof trend.successful_runs_count === 'number' && Number.isSafeInteger(trend.successful_runs_count) && trend.successful_runs_count >= 0 ? (
          <span
            className="rounded-md bg-black/65 px-2 py-1 text-[10px] font-semibold text-white"
            aria-label={'Успешных повторов: ' + trend.successful_runs_count}
          >✅ {successfulRepeatsLabel(trend.successful_runs_count)}</span>
        ) : null}
      </div>
      {isVideoPreview(trend) ? (
        <span className="pointer-events-none absolute right-2 top-2 rounded-lg bg-black/60 p-1.5 text-white" aria-label="Видео">
          <Film className="h-4 w-4" />
        </span>
      ) : null}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 p-3">
        <span className="line-clamp-3 text-xs font-semibold leading-5 text-white drop-shadow-md sm:text-sm">{trend.title}</span>
        {formatTrendRepeatPrice(trend) ? <span className="mt-1 block text-xs font-semibold text-gold">{formatTrendRepeatPrice(trend)}</span> : null}
      </div>
    </button>
  )
}

export function TrendShowcase({ categories, onRepeat, onShare, onEdit, onRemove, removingId, isAdmin = false }: {
  categories: ShowcaseCategory[]
  isAdmin?: boolean
  onRepeat: (trend: ShowcaseTrend) => void
  onShare: (trend: ShowcaseTrend) => void
  onEdit?: (trend: ShowcaseTrend) => void
  onRemove?: (trend: ShowcaseTrend) => void
  removingId?: number | null
}) {
  const [selected, setSelected] = useState<ShowcaseTrend | null>(null)
  const [categoryId, setCategoryId] = useState<number | 'unassigned' | null>(null)
  const [pageItems, setPageItems] = useState<ShowcaseTrend[]>([])
  const [page, setPage] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [pageLoading, setPageLoading] = useState(false)
  const [pageError, setPageError] = useState('')
  const requestId = useRef(0)
  const category = categories.find((row) => row.id === categoryId)

  const loadPage = useCallback(async (id: number | 'unassigned', nextPage: number) => {
    const activeRequest = ++requestId.current
    setPageLoading(true)
    setPageError('')
    try {
      const result = await fetchTrendCategory(id, nextPage, 24)
      if (requestId.current !== activeRequest) return
      setPageItems((current) => nextPage === 1 ? result.items : [
        ...current,
        ...result.items.filter((item) => !current.some((old) => old.id === item.id)),
      ])
      setPage(result.page)
      setHasMore(result.has_more)
      void resolveGenjutsuPrices(result.items).then((priced) => {
        if (requestId.current !== activeRequest) return
        const pricedById = new Map(priced.map((trend) => [trend.id, trend]))
        setPageItems((current) => current.map((trend) => pricedById.get(trend.id) || trend))
      })
    } catch (error) {
      if (requestId.current === activeRequest) {
        setPageError(error instanceof Error ? error.message : 'Не удалось загрузить категорию')
      }
    } finally {
      if (requestId.current === activeRequest) setPageLoading(false)
    }
  }, [])

  useEffect(() => {
    if (categoryId === null) return
    setPageItems([])
    setPage(0)
    void loadPage(categoryId, 1)
    return () => { requestId.current += 1 }
  }, [categoryId, loadPage])

  const openCategory = (id: number | 'unassigned') => {
    setCategoryId(id)
  }

  const closeCategory = () => {
    requestId.current += 1
    setCategoryId(null)
  }

  return (
    <div className="space-y-7">
      {categoryId === null ? categories.filter((row) => row.is_visible && row.total > 0).map((row) => (
        <section key={row.id} aria-label={row.title} className="space-y-3">
          <div className="flex min-w-0 items-center justify-between gap-3">
            <h3 className="min-w-0 truncate font-serif text-lg font-semibold text-gold">
              {row.emoji ? row.emoji + ' ' : ''}{row.title}
            </h3>
            <Button
              variant="secondary"
              size="sm"
              className="h-9 shrink-0 border border-border/60 px-3 text-muted-foreground"
              onClick={() => openCategory(row.id)}
              aria-label={'Все тренды категории ' + row.title}
            >
              Все
            </Button>
          </div>
          <div className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto overscroll-x-contain px-4 pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {row.items.map((trend) => (
              <LiveTile
                key={trend.id}
                trend={trend}
                isAdmin={isAdmin}
                onPreview={setSelected}
                className="w-[min(44vw,188px)] snap-start"
              />
            ))}
          </div>
        </section>
      )) : (
        <section className="space-y-4">
          <Button type="button" variant="ghost" className="gap-2" onClick={closeCategory}>
            <ArrowLeft className="h-4 w-4" /> К категориям
          </Button>
          <div className="flex items-center justify-between gap-2">
            <h3 className="font-serif text-xl font-semibold text-gold">
              {category?.emoji ? category.emoji + ' ' : ''}{category?.title || 'Тренды'}
            </h3>
            <span className="text-xs text-muted-foreground">{category?.total || 0}</span>
          </div>
          {pageError ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{pageError}</p> : null}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {pageItems.map((trend) => (
              <LiveTile key={trend.id} trend={trend} isAdmin={isAdmin} onPreview={setSelected} className="w-full" />
            ))}
          </div>
          {pageLoading ? <div role="status" className="flex justify-center py-4"><Loader2 className="h-5 w-5 animate-spin" /></div> : null}
          {hasMore && !pageLoading ? (
            <Button type="button" variant="secondary" className="w-full" onClick={() => void loadPage(categoryId, page + 1)}>
              Показать ещё
            </Button>
          ) : null}
          {!pageLoading && !pageItems.length && !pageError ? (
            <p className="py-6 text-center text-sm text-muted-foreground">В категории пока нет трендов</p>
          ) : null}
        </section>
      )}

      <Dialog open={Boolean(selected)} onOpenChange={(open) => { if (!open) setSelected(null) }}>
        <DialogContent className="max-h-[92dvh] max-w-md overflow-y-auto border-border/60 bg-background p-4">
          <DialogTitle className="pr-8 font-serif text-lg">{selected?.title || 'Тренд'}</DialogTitle>
          <DialogDescription className="text-xs">{selected?.description || 'Посмотрите пример и повторите со своими данными'}</DialogDescription>
          {selected ? (
            <div className="space-y-3">
              {isAdmin === true && typeof selected.successful_runs_count === 'number' && Number.isSafeInteger(selected.successful_runs_count) && selected.successful_runs_count >= 0 ? (
                <p className="text-xs font-semibold text-foreground" aria-label={'Успешных повторов: ' + selected.successful_runs_count}>
                  ✅ Успешных повторов: {selected.successful_runs_count.toLocaleString('ru-RU')}
                </p>
              ) : null}
              {selected.preview_url ? isVideoPreview(selected) ? (
                <video
                  key={selected.id}
                  controls
                  playsInline
                  loop
                  poster={selected.preview_poster_url ? normalizeMiniAppMediaUrl(selected.preview_poster_url) : undefined}
                  src={videoPreviewFrameUrl(normalizeMiniAppMediaUrl(selected.preview_url))}
                  preload="metadata"
                  data-audio-enabled="true"
                  className="max-h-[60dvh] w-full rounded-xl bg-black object-contain"
                />
              ) : (
                <img src={normalizeMiniAppMediaUrl(selected.preview_url)} alt={selected.title} className="max-h-[60dvh] w-full rounded-xl object-contain" />
              ) : null}
              <Button type="button" className="min-h-11 w-full bg-gold text-primary-foreground" onClick={() => {
                setSelected(null)
                onRepeat(selected)
              }}>
                <Repeat2 className="h-4 w-4" /> Повторить
                {formatTrendRepeatPrice(selected) ? ' · ' + formatTrendRepeatPrice(selected) : ''}
              </Button>
              <Button type="button" variant="secondary" className="min-h-11 w-full" onClick={() => {
                setSelected(null)
                onShare(selected)
              }}>
                <Share2 className="h-4 w-4" /> Поделиться трендом
              </Button>
              {onEdit || onRemove ? (
                <div className="grid grid-cols-2 gap-2 border-t border-border/50 pt-3">
                  {onEdit ? (
                    <Button type="button" variant="secondary" className="min-h-11" onClick={() => {
                      setSelected(null)
                      onEdit(selected)
                    }}>
                      <Pencil className="h-4 w-4" /> Редактировать
                    </Button>
                  ) : null}
                  {onRemove ? (
                    <Button type="button" variant="destructive" className="min-h-11" disabled={removingId === selected.id} onClick={() => {
                      setSelected(null)
                      onRemove(selected)
                    }}>
                      <Trash2 className="h-4 w-4" /> Убрать тренд
                    </Button>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      {!categories.some((cat) => cat.is_visible && cat.total > 0) && categoryId === null ? (
        <div className="glass flex flex-col items-center rounded-2xl p-8 text-center text-muted-foreground">
          <Flame className="mb-3 h-8 w-8 text-gold/70" />
          <p>Трендов пока нет</p>
        </div>
      ) : null}
    </div>
  )
}
