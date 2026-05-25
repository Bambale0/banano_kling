'use client'

import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useApp } from '@/lib/app-context'
import type { FeedComment, FeedItem } from '@/lib/types'
import { cn, isHttpUrl } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  addFeedComment,
  fetchFeed,
  fetchFeedComments,
  likeFeedItem,
  removeFeedItem,
  shareFeedItem,
} from '@/lib/api'
import {
  Heart,
  ImageOff,
  Loader2,
  MessageCircle,
  Send,
  Share2,
  Sparkles,
  Trash2,
  UserRound,
  X,
} from 'lucide-react'

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

function getPinHeightWeight(value?: string | null) {
  const match = String(value || '').match(/^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/)
  if (!match) return 1.25
  const width = Number(match[1])
  const height = Number(match[2])
  if (!width || !height) return 1.25
  return height / width
}

export function FeedTab() {
  const { state, setActiveTab, setPromptPreset, openProfile } = useApp()
  const [source, setSource] = useState<(typeof sources)[number]['id']>('recent')
  const [items, setItems] = useState<FeedItem[]>([])
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [previewItem, setPreviewItem] = useState<FeedItem | null>(null)
  const [commentsItem, setCommentsItem] = useState<FeedItem | null>(null)
  const [comments, setComments] = useState<FeedComment[]>([])
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [commentText, setCommentText] = useState('')

  const isLive = state.mode === 'live'
  const feedColumns = useMemo(() => {
    const columns: [FeedItem[], FeedItem[]] = [[], []]
    const heights = [0, 0.45]

    items.forEach((item) => {
      const columnIndex = heights[0] <= heights[1] ? 0 : 1
      columns[columnIndex].push(item)
      heights[columnIndex] += getPinHeightWeight(item.aspect_ratio) + 0.4
    })

    return columns
  }, [items])

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

  useEffect(() => {
    let ignore = false
    async function loadComments() {
      if (!commentsItem || !isLive) {
        setComments([])
        return
      }
      setCommentsLoading(true)
      try {
        const nextComments = await fetchFeedComments(commentsItem.id)
        if (!ignore) setComments(nextComments)
      } catch (e) {
        if (!ignore) setError(getErrorMessage(e, 'Не удалось загрузить комментарии'))
      } finally {
        if (!ignore) setCommentsLoading(false)
      }
    }
    loadComments()
    return () => {
      ignore = true
    }
  }, [commentsItem, isLive])

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
      prompt: item.prompt || '',
      model: modelExists ? item.model : state.imageModels[0]?.id || 'banana_pro',
      ratio: item.aspect_ratio || '1:1',
      sourceFeedGenId: item.id,
      promptHidden: false,
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

  const handleOpenAuthor = (item: FeedItem) => {
    const code = String(item.author_referral_code || '').trim()
    if (!code) return
    openProfile(code)
  }

  const handleSubmitComment = async () => {
    const text = commentText.trim()
    if (!isLive || !commentsItem || !text) return
    setBusyId(commentsItem.id)
    try {
      const { comment, commentsCount } = await addFeedComment(commentsItem.id, text)
      setComments((prev) => [...prev, comment])
      setCommentText('')
      setItems((prev) =>
        prev.map((item) =>
          item.id === commentsItem.id ? { ...item, comments_count: commentsCount } : item
        )
      )
      setCommentsItem((prev) =>
        prev ? { ...prev, comments_count: commentsCount } : prev
      )
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось отправить комментарий'))
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
        <div className="grid grid-cols-2 items-start gap-3 pb-28">
          {feedColumns.map((column, columnIndex) => (
            <div
              key={columnIndex}
              className={cn('flex min-w-0 flex-col gap-3', columnIndex === 1 && 'pt-8')}
            >
              {column.map((item) => (
                <article
                  key={item.id}
                  className="min-w-0 overflow-hidden rounded-2xl border border-border/45 bg-card/45 shadow-sm shadow-background/30"
                >
                  <div className="relative overflow-hidden bg-secondary/50">
                    <button
                      type="button"
                      onClick={() => setPreviewItem(item)}
                      className="group block w-full text-left"
                      aria-label="Открыть фото"
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
                    </button>
                    <div className="absolute left-2 top-2 rounded-full bg-background/80 px-2 py-1 text-[10px] font-medium text-foreground backdrop-blur">
                      {item.aspect_ratio || 'image'}
                    </div>
                    <button
                      type="button"
                      onClick={() => handleRemix(item)}
                      className="absolute right-2 top-2 flex h-8 w-8 items-center justify-center rounded-full bg-gold text-primary-foreground opacity-95 shadow-lg shadow-background/30"
                      aria-label="Повторить"
                    >
                      <Sparkles className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="space-y-2.5 px-2.5 pb-3 pt-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-semibold text-foreground">{item.model}</p>
                        <button
                          type="button"
                          className={cn(
                            'mt-0.5 flex max-w-full items-center gap-1 truncate text-[11px] text-muted-foreground transition-colors',
                            item.author_referral_code && 'hover:text-cyan'
                          )}
                          disabled={!item.author_referral_code}
                          onClick={() => handleOpenAuthor(item)}
                        >
                          <UserRound className="h-3 w-3 shrink-0" />
                          <span className="truncate">{item.author}</span>
                        </button>
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
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        className="h-8 min-w-0 flex-1 rounded-full px-2 text-[11px]"
                        onClick={() => setCommentsItem(item)}
                        aria-label="Комментарии"
                      >
                        <MessageCircle className="h-4 w-4" />
                        {item.comments_count || 0}
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
          ))}
        </div>
      ) : (
        <div className="glass rounded-2xl border border-border/50 p-6 text-center text-sm text-muted-foreground">
          {isLive ? 'В ленте пока нет опубликованных работ.' : 'Откройте mini app из Telegram, чтобы увидеть ленту.'}
        </div>
      )}

      {previewItem ? (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-background/95 px-3 py-6">
          <button
            type="button"
            onClick={() => setPreviewItem(null)}
            className="absolute right-4 top-4 flex h-10 w-10 items-center justify-center rounded-full bg-secondary/80 text-foreground"
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" />
          </button>
          {isHttpUrl(previewItem.result_url) ? (
            <img
              src={previewItem.result_url}
              alt=""
              className="max-h-full w-auto max-w-full object-contain"
            />
          ) : (
            <div className="flex h-48 w-full items-center justify-center text-muted-foreground">
              <ImageOff className="h-8 w-8" />
            </div>
          )}
        </div>
      ) : null}

      {commentsItem ? (
        <div className="fixed inset-0 z-[85] flex items-end bg-background/70 backdrop-blur-sm">
          <div className="flex max-h-[82vh] w-full flex-col rounded-t-2xl border border-border/60 bg-card shadow-2xl">
            <div className="flex items-center justify-between border-b border-border/60 px-4 py-3">
              <div className="text-sm font-semibold text-foreground">Комментарии</div>
              <button
                type="button"
                onClick={() => setCommentsItem(null)}
                className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-muted-foreground"
                aria-label="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
              {commentsLoading ? (
                <div className="flex justify-center py-6 text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin" />
                </div>
              ) : comments.length ? (
                comments.map((comment) => (
                  <div key={comment.id} className="flex gap-2 text-sm">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary text-[11px] font-semibold text-foreground">
                      {comment.author.replace(/^@/, '').slice(0, 1).toUpperCase() || 'U'}
                    </div>
                    <div className="min-w-0 flex-1">
                      <span className="mr-2 font-semibold text-foreground">{comment.author}</span>
                      <span className="break-words text-foreground/90">{comment.text}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="py-8 text-center text-sm text-muted-foreground">Пока пусто</div>
              )}
            </div>
            <div className="flex items-center gap-2 border-t border-border/60 p-3">
              <input
                value={commentText}
                onChange={(event) => setCommentText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    handleSubmitComment()
                  }
                }}
                maxLength={500}
                className="h-10 min-w-0 flex-1 rounded-full border border-border/60 bg-background px-4 text-sm text-foreground outline-none focus:border-cyan"
                placeholder="Комментарий"
              />
              <Button
                type="button"
                size="icon"
                className="h-10 w-10 rounded-full"
                disabled={!commentText.trim() || busyId === commentsItem.id}
                onClick={handleSubmitComment}
                aria-label="Отправить"
              >
                {busyId === commentsItem.id ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
