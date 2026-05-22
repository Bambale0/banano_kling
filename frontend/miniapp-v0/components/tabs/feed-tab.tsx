'use client'

import { useEffect, useState, type CSSProperties } from 'react'
import { useApp } from '@/lib/app-context'
import type { FeedItem } from '@/lib/types'
import { cn, isHttpUrl } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { fetchFeed, likeFeedItem, removeFeedItem, shareFeedItem } from '@/lib/api'
import { Heart, ImageOff, Loader2, Share2, Sparkles, Trash2 } from 'lucide-react'

const sources = [
  { id: 'recent', label: 'Новые' },
  { id: 'top_day', label: 'Топ дня' },
  { id: 'top', label: 'Лучшие' },
] as const

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function getPinAspectRatio(value?: string | null): CSSProperties['aspectRatio'] {
  const match = String(value || '').match(/^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/)
  if (!match) return '4 / 5'
  const width = Number(match[1])
  const height = Number(match[2])
  if (!width || !height) return '4 / 5'
  return `${width} / ${height}`
}

export function FeedTab() {
  const { state, setActiveTab, setPromptPreset } = useApp()
  const [source, setSource] = useState<(typeof sources)[number]['id']>('recent')
  const [items, setItems] = useState<FeedItem[]>([])
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const isLive = state.mode === 'live'

  useEffect(() => {
    let ignore = false
    async function load() {
      if (!isLive) {
        setItems([])
        return
      }
      setLoading(true)
      setError(null)
      try {
        const feed = await fetchFeed({ source, limit: 40 })
        if (!ignore) setItems(feed)
      } catch (e) {
        if (!ignore) setError(getErrorMessage(e, 'Не удалось загрузить ленту'))
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => {
      ignore = true
    }
  }, [isLive, source])

  const handleLike = async (item: FeedItem) => {
    if (!isLive) return
    setBusyId(item.id)
    try {
      const updated = await likeFeedItem(item.id)
      setItems((prev) => prev.map((feedItem) => (feedItem.id === updated.id ? updated : feedItem)))
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось поставить лайк'))
    } finally {
      setBusyId(null)
    }
  }

  const handleShare = async (item: FeedItem) => {
    if (!isLive || typeof navigator === 'undefined') return
    setBusyId(item.id)
    try {
      const { item: updated, link } = await shareFeedItem(item.id)
      setItems((prev) => prev.map((feedItem) => (feedItem.id === updated.id ? updated : feedItem)))
      await navigator.clipboard.writeText(link)
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось создать ссылку'))
    } finally {
      setBusyId(null)
    }
  }

  const handleRemix = async (item: FeedItem) => {
    if (!isLive) return
    const modelExists = state.imageModels.some((model) => model.id === item.model)
    setPromptPreset({
      promptId: null,
      title: 'Повторить образ из ленты',
      prompt: '',
      model: modelExists ? item.model : state.imageModels[0]?.id || 'banana_pro',
      ratio: item.aspect_ratio || '1:1',
      sourceFeedGenId: item.id,
      promptHidden: true,
    })
    setActiveTab(1)
  }

  const handleRemove = async (item: FeedItem) => {
    if (!isLive || !item.is_mine) return
    setBusyId(item.id)
    try {
      await removeFeedItem(item.id)
      setItems((prev) => prev.filter((feedItem) => feedItem.id !== item.id))
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось убрать пост'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="px-4 space-y-5">
      <div>
        <h2 className="font-serif text-xl font-semibold text-foreground">Лента работ</h2>
        <p className="mt-1 text-sm text-muted-foreground">Публичные изображения, которые можно лайкнуть или повторить со своим фото.</p>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-1">
        {sources.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setSource(item.id)}
            className={cn(
              'rounded-lg border px-3 py-2 text-xs font-medium transition-colors',
              source === item.id
                ? 'border-gold/50 bg-gold/15 text-gold'
                : 'border-border/50 bg-secondary/50 text-muted-foreground'
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-10 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : items.length ? (
        <div className="columns-2 gap-3 sm:columns-3 xl:columns-4">
          {items.map((item) => (
            <article
              key={item.id}
              className="mb-3 break-inside-avoid overflow-hidden rounded-2xl border border-border/45 bg-card/45 shadow-sm shadow-background/30"
            >
              <button
                type="button"
                onClick={() => handleRemix(item)}
                className="group relative block w-full overflow-hidden bg-secondary/50 text-left"
                aria-label="Повторить с моим фото"
              >
                {isHttpUrl(item.result_url) ? (
                  <img
                    src={item.result_url}
                    alt=""
                    loading="lazy"
                    style={{ aspectRatio: getPinAspectRatio(item.aspect_ratio) }}
                    className="w-full object-cover transition-transform duration-500 group-hover:scale-[1.03]"
                  />
                ) : (
                  <div
                    style={{ aspectRatio: getPinAspectRatio(item.aspect_ratio) }}
                    className="flex w-full items-center justify-center text-muted-foreground"
                  >
                    <ImageOff className="h-8 w-8" />
                  </div>
                )}
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-background/70 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
                <div className="absolute left-2 top-2 rounded-full bg-background/80 px-2 py-1 text-[10px] font-medium text-foreground backdrop-blur">
                  {item.aspect_ratio || 'image'}
                </div>
                <span className="absolute right-2 top-2 flex h-8 w-8 items-center justify-center rounded-full bg-gold text-primary-foreground opacity-95 shadow-lg shadow-background/30">
                  <Sparkles className="h-4 w-4" />
                </span>
              </button>
              <div className="space-y-2.5 px-2.5 pb-3 pt-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-xs font-semibold text-foreground">{item.model}</p>
                    <p className="truncate text-[11px] text-muted-foreground">{item.author}</p>
                  </div>
                  <div className="shrink-0 rounded-full bg-secondary/70 px-2 py-1 text-[10px] text-muted-foreground">
                    {item.remixes}
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    className="h-8 min-w-0 flex-1 rounded-full px-2 text-[11px]"
                    disabled={busyId === item.id}
                    onClick={() => handleLike(item)}
                    aria-label="Лайк"
                  >
                    <Heart className="h-4 w-4" />
                    {item.likes_count}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    className="h-8 min-w-0 flex-1 rounded-full px-2 text-[11px]"
                    disabled={busyId === item.id}
                    onClick={() => handleShare(item)}
                    aria-label="Ссылка"
                  >
                    <Share2 className="h-4 w-4" />
                    {item.shares_count}
                  </Button>
                  {item.is_mine ? (
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="secondary"
                      className="h-8 w-8 rounded-full"
                      disabled={busyId === item.id}
                      onClick={() => handleRemove(item)}
                      aria-label="Убрать"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  ) : null}
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="glass rounded-2xl border border-border/50 p-6 text-center text-sm text-muted-foreground">
          {isLive ? 'В ленте пока нет опубликованных работ.' : 'Откройте mini app из Telegram, чтобы увидеть ленту.'}
        </div>
      )}
    </div>
  )
}
