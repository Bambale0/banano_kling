'use client'

import { useEffect, useState } from 'react'
import {
  fetchVkPublicCategory,
  fetchVkPublicDiscovery,
  type VkPublicCategoryPage,
  type VkPublicDiscovery,
  type VkPublicFeedItem,
  type VkPublicTrend,
} from '@/lib/shared-account-api'

function mediaUrl(raw: string | null | undefined): string {
  const url = String(raw || '').trim()
  return /^https:\/\//i.test(url) || /^\/(?!\/)[\w./%-]+$/i.test(url) ? url : ''
}

function Preview({ image, video, title }: { image?: string | null; video?: string | null; title: string }) {
  const src = mediaUrl(image)
  const movie = mediaUrl(video)
  return <div className="aspect-[4/3] overflow-hidden rounded-xl bg-secondary/60">
    {movie
      ? <video src={movie} poster={src || undefined} controls playsInline preload="none" className="h-full w-full object-cover" />
      : src
        ? <img src={src} alt={title} loading="lazy" className="h-full w-full object-cover" />
        : <div className="flex h-full items-center justify-center text-muted-foreground">✨ NEUROMIX</div>}
  </div>
}

function TrendCard({ item }: { item: VkPublicTrend }) {
  return <article className="min-w-0 rounded-2xl border border-border/70 bg-card p-2">
    <Preview
      image={item.preview_poster_url || item.preview_url}
      video={item.generation_type === 'video' ? item.preview_url : null}
      title={item.title}
    />
    <div className="space-y-1 px-1 py-2">
      <div className="text-xs text-muted-foreground">{item.generation_type === 'video' ? '🎬 Видео' : '🖼 Фото'}</div>
      <h4 className="line-clamp-2 text-sm font-semibold">{item.title}</h4>
      {item.description ? <p className="line-clamp-2 text-xs text-muted-foreground">{item.description}</p> : null}
    </div>
  </article>
}

function FeedCard({ item }: { item: VkPublicFeedItem }) {
  return <article className="min-w-0 rounded-2xl border border-border/70 bg-card p-2">
    <Preview
      image={item.preview_url || (item.generation_type === 'image' ? item.result_url : null)}
      video={item.generation_type === 'video' ? item.result_url : null}
      title="Опубликованная работа"
    />
    <p className="px-1 py-2 text-xs text-muted-foreground">
      {item.generation_type === 'video' ? '🎬 Видео' : '🖼 Фото'} · ❤ {item.likes_count}
    </p>
  </article>
}

export function VkStandaloneDiscovery() {
  const [view, setView] = useState<'trends' | 'feed'>('trends')
  const [categoryId, setCategoryId] = useState<string | number | null>(null)
  const [page, setPage] = useState(1)
  const [discovery, setDiscovery] = useState<VkPublicDiscovery | null>(null)
  const [category, setCategory] = useState<VkPublicCategoryPage | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setBusy(true)
    setError('')
    const operation = categoryId === null
      ? fetchVkPublicDiscovery(view, controller.signal)
      : fetchVkPublicCategory(categoryId, page, controller.signal)
    operation.then(payload => {
      if (controller.signal.aborted) return
      if ('category' in payload) {
        setCategory(current => page === 1 || !current
          ? payload
          : { ...payload, items: [...current.items, ...payload.items] })
      } else {
        setDiscovery(payload)
      }
    }).catch(failure => {
      if (!controller.signal.aborted) {
        setError(failure instanceof Error ? failure.message : 'Не удалось загрузить каталог.')
      }
    }).finally(() => {
      if (!controller.signal.aborted) setBusy(false)
    })
    return () => controller.abort()
  }, [view, categoryId, page, retry])

  const switchView = (next: 'trends' | 'feed') => {
    setView(next)
    setCategoryId(null)
    setCategory(null)
    setDiscovery(null)
    setPage(1)
  }

  return <section aria-label="Каталог ВКонтакте" className="space-y-4">
    <div className="flex gap-2">
      <button type="button" aria-pressed={view === 'trends'}
        onClick={() => switchView('trends')}
        className={'rounded-xl px-4 py-2 text-sm font-medium ' + (view === 'trends' ? 'bg-primary text-primary-foreground' : 'border border-border')}>
        Тренды
      </button>
      <button type="button" aria-pressed={view === 'feed'}
        onClick={() => switchView('feed')}
        className={'rounded-xl px-4 py-2 text-sm font-medium ' + (view === 'feed' ? 'bg-primary text-primary-foreground' : 'border border-border')}>
        Лента
      </button>
    </div>
    {categoryId !== null ? (
      <button type="button" className="text-sm underline" onClick={() => {
        setCategoryId(null); setCategory(null); setPage(1)
      }}>← Ко всем трендам</button>
    ) : null}
    {error ? <div role="alert" className="space-y-2 text-sm">
      <p>{error}</p>
      <button type="button" className="underline" onClick={() => setRetry(x => x + 1)}>Повторить загрузку</button>
    </div> : null}
    {busy && !discovery && !category ? <p role="status" className="text-sm text-muted-foreground">Загружаем тренды…</p> : null}
    {categoryId !== null && category ? <>
      <h3 className="text-lg font-semibold">{category.category.emoji} {category.category.title}</h3>
      <div className="grid grid-cols-2 gap-3">
        {category.items.map(item => <TrendCard key={item.id} item={item} />)}
      </div>
      {category.has_more ? <button type="button" disabled={busy}
        onClick={() => setPage(value => value + 1)} className="w-full rounded-xl border border-border p-3 text-sm">
        {busy ? 'Загрузка…' : 'Показать ещё'}
      </button> : null}
    </> : null}
    {categoryId === null && discovery && 'categories' in discovery ? discovery.categories.map(group => (
      <div key={group.id} className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-base font-semibold">{group.emoji} {group.title}</h3>
          {group.total > group.items.length
            ? <button type="button" className="shrink-0 text-xs underline" onClick={() => {
                setCategoryId(group.id); setCategory(null); setPage(1)
              }}>Все ({group.total})</button>
            : null}
        </div>
        <div className="grid grid-cols-2 gap-3">
          {group.items.map(item => <TrendCard key={item.id} item={item} />)}
        </div>
      </div>
    )) : null}
    {categoryId === null && discovery && 'items' in discovery ? (
      <div className="grid grid-cols-2 gap-3">
        {discovery.items.map(item => <FeedCard key={item.id} item={item} />)}
      </div>
    ) : null}
    <p className="text-xs text-muted-foreground">
      Просмотр открыт без Telegram. Оплачиваемый повтор непосредственно в Mini App
      появится после подключения защищённого VK-баланса и создания задач.
      Пока генерация доступна в боте сообщества.
    </p>
  </section>
}
