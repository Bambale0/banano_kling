'use client'

import { useEffect, useRef, useState } from 'react'
import { parseMiniAppStartParam, startParamFromLocation } from '@/lib/start-params'
import { VkGenerationPanel } from './vk-generation-panel'
import { VkNativeCheckout, type VkCheckoutAttempt } from './vk-native-checkout'
import {
  fetchVkPublicCategory,
  fetchVkPublicDiscovery,
  fetchVkPublicTrend,
  fetchVkPublicFeedItem,
  likeVkFeed,
  fetchVkNativeState,
  fetchVkNativeCommerce,
  type VkNativeState,
  type VkNativeCommerce,
  type VkPublicCategoryPage,
  type VkPublicDiscovery,
  type VkPublicFeedItem,
  type VkPublicFeedLink,
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

function TrendCard({ item, onRepeat, onShare }: {
  item: VkPublicTrend
  onRepeat?: (item: VkPublicTrend) => void
  onShare?: (item: VkPublicTrend) => void
}) {
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
      {item.can_repeat_in_app && onRepeat ? <button type="button" onClick={() => onRepeat(item)}
        className="mt-1 w-full rounded-lg border border-primary px-2 py-2 text-xs font-medium text-primary">
        Повторить «{item.title}»
      </button> : null}
      {item.share_link && onShare ? <button type="button" onClick={() => onShare(item)}
        className="mt-1 w-full rounded-lg border border-border px-2 py-2 text-xs font-medium">
        Ссылка на «{item.title}»
      </button> : null}
    </div>
  </article>
}

function FeedCard({ item, onLike, liking, liked }: {
  item: VkPublicFeedItem
  onLike: (id: number) => void
  liking: boolean
  liked: boolean
}) {
  return <article className="min-w-0 rounded-2xl border border-border/70 bg-card p-2">
    <Preview
      image={item.preview_url || (item.generation_type === 'image' ? item.result_url : null)}
      video={item.generation_type === 'video' ? item.result_url : null}
      title="Опубликованная работа"
    />
    <p className="px-1 py-2 text-xs text-muted-foreground">
      {item.generation_type === 'video' ? '🎬 Видео' : '🖼 Фото'} · ❤ {item.likes_count}
    </p>
    {item.can_like_in_app && <button type="button"
      disabled={liking || liked}
      onClick={() => onLike(item.id)}
      className="w-full rounded-lg border border-border px-2 py-2 text-xs">
      {liked ? 'Вам нравится' : liking ? 'Сохраняем…' : 'Нравится'}
    </button>}
  </article>
}

export function VkStandaloneDiscovery() {
  const [view, setView] = useState<'trends' | 'feed' | 'mine'>('trends')
  const [native, setNative] = useState<VkNativeState | null>(null)
  const [commerce, setCommerce] = useState<VkNativeCommerce | null>(null)
  const [commerceError, setCommerceError] = useState('')
  const [checkoutAttempt, setCheckoutAttempt] = useState<VkCheckoutAttempt | null>(null)
  const [repeatItem, setRepeatItem] = useState<VkPublicTrend | null>(null)
  const [linkedTrendId, setLinkedTrendId] = useState<number | null>(null)
  const [linkedTrend, setLinkedTrend] = useState<VkPublicTrend | null>(null)
  const [linkedTrendError, setLinkedTrendError] = useState('')
  const [linkedTrendLoading, setLinkedTrendLoading] = useState(false)
  const [linkedFeedTarget, setLinkedFeedTarget] = useState<{ kind: 'feed' | 'remix'; genId: number } | null>(null)
  const [linkedFeed, setLinkedFeed] = useState<VkPublicFeedLink['item'] | null>(null)
  const [linkedFeedError, setLinkedFeedError] = useState('')
  const [linkedFeedLoading, setLinkedFeedLoading] = useState(false)
  const [likeBusyId, setLikeBusyId] = useState<number | null>(null)
  const [likedIds, setLikedIds] = useState<Set<number>>(() => new Set())
  const [likeError, setLikeError] = useState('')
  const likeInFlight = useRef<Set<number>>(new Set())
  const [shareLink, setShareLink] = useState('')
  const [shareTitle, setShareTitle] = useState('')
  const [shareCopyMessage, setShareCopyMessage] = useState('')
  const [createPhoto, setCreatePhoto] = useState(false)
  const [createVideo, setCreateVideo] = useState(false)
  const [nativeError, setNativeError] = useState('')
  const [nativeRetry, setNativeRetry] = useState(0)
  const [categoryId, setCategoryId] = useState<string | number | null>(null)
  const [page, setPage] = useState(1)
  const [discovery, setDiscovery] = useState<VkPublicDiscovery | null>(null)
  const [category, setCategory] = useState<VkPublicCategoryPage | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [retry, setRetry] = useState(0)
  // Poll only active tasks while the owner is watching their history. A
  // completed/failed result stops the timer; background tabs make no requests.
  // Treat an incomplete response as unavailable history, not an empty history.
  // Never let a malformed native-state response blank the whole VK catalog.
  // VK verifies launch query separately; the fragment only identifies a
  // publicly readable trend. Backend checks approval, category visibility
  // and bearer ownership before returning a sanitized card.
  useEffect(() => {
    const updateTarget = () => {
      const target = parseMiniAppStartParam(
        startParamFromLocation(window.location.search, window.location.hash),
      )
      setLinkedTrendId(target?.kind === 'prompt' ? target.promptId : null)
      setLinkedFeedTarget(target?.kind === 'feed' || target?.kind === 'remix'
        ? { kind: target.kind, genId: target.genId } : null)
    }
    updateTarget()
    window.addEventListener('hashchange', updateTarget)
    window.addEventListener('popstate', updateTarget)
    return () => {
      window.removeEventListener('hashchange', updateTarget)
      window.removeEventListener('popstate', updateTarget)
    }
  }, [])

  useEffect(() => {
    if (linkedTrendId === null) {
      setLinkedTrend(null)
      setLinkedTrendError('')
      setLinkedTrendLoading(false)
      return
    }
    const controller = new AbortController()
    setView('trends')
    setLinkedTrend(null)
    setLinkedTrendError('')
    setLinkedTrendLoading(true)
    fetchVkPublicTrend(linkedTrendId, controller.signal).then(result => {
      if (!controller.signal.aborted) setLinkedTrend(result.item)
    }).catch(error => {
      if (!controller.signal.aborted) {
        setLinkedTrendError(error instanceof Error ? error.message : 'Не удалось открыть тренд по ссылке.')
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLinkedTrendLoading(false)
    })
    return () => controller.abort()
  }, [linkedTrendId])

  useEffect(() => {
    if (!linkedFeedTarget) {
      setLinkedFeed(null)
      setLinkedFeedError('')
      setLinkedFeedLoading(false)
      return
    }
    const controller = new AbortController()
    setView('feed')
    setCategoryId(null)
    setLinkedFeed(null)
    setLinkedFeedError('')
    setLinkedFeedLoading(true)
    fetchVkPublicFeedItem(linkedFeedTarget.genId, controller.signal).then(result => {
      if (!controller.signal.aborted) setLinkedFeed(result.item)
    }).catch(error => {
      if (!controller.signal.aborted) {
        setLinkedFeedError(error instanceof Error ? error.message : 'Не удалось открыть публикацию.')
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLinkedFeedLoading(false)
    })
    return () => controller.abort()
  }, [linkedFeedTarget])

  const likeFeed = async (id: number) => {
    if (likeInFlight.current.has(id) || likedIds.has(id)) return
    likeInFlight.current.add(id)
    setLikeBusyId(id)
    setLikeError('')
    try {
      const result = await likeVkFeed(id)
      if (!result.ok || !result.liked || !Number.isSafeInteger(result.likes_count)
        || result.likes_count < 0) {
        throw new Error('Не удалось подтвердить реакцию на публикацию.')
      }
      setLikedIds(current => new Set(current).add(id))
      setLinkedFeed(current => current?.id === id
        ? { ...current, likes_count: result.likes_count } : current)
      setDiscovery(current => current && 'items' in current
        ? { ...current, items: current.items.map(item => item.id === id
          ? { ...item, likes_count: result.likes_count } : item) }
        : current)
    } catch (failure) {
      setLikeError(failure instanceof Error ? failure.message : 'Не удалось сохранить реакцию.')
    } finally {
      likeInFlight.current.delete(id)
      setLikeBusyId(value => value === id ? null : value)
    }
  }

  const closeLinkedFeed = () => {
    if (/^#(?:feed|remix)_/.test(window.location.hash)) {
      window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search)
    }
    setLinkedFeedTarget(null)
    setLinkedFeed(null)
    setLinkedFeedError('')
  }

  const closeLinkedTrend = () => {
    if (window.location.hash.startsWith('#prompt_')) {
      window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search)
    }
    setLinkedTrendId(null)
    setLinkedTrend(null)
    setLinkedTrendError('')
    setRepeatItem(null)
  }

  const openShareLink = (item: VkPublicTrend) => {
    const url = item.share_link || ''
    // Trusted app origin and public ID only, no signed session or private media.
    if (!/^https:\/\/vk\.com\/app[1-9][0-9]*(?:_-[1-9][0-9]*)?#prompt_[1-9][0-9]*$/.test(url)) return
    setShareTitle(item.title)
    setShareLink(url)
    setShareCopyMessage('')
  }

  const nativeTasks = Array.isArray(native?.tasks) ? native.tasks : null
  const hasActiveVkTask = nativeTasks?.some(task =>
    ['pending', 'submitting', 'processing', 'queued'].includes(task.status),
  ) === true

  useEffect(() => {
    if (view !== 'mine' || !hasActiveVkTask) return
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        setNativeRetry(current => current + 1)
      }
    }, 15000)
    return () => window.clearInterval(timer)
  }, [view, hasActiveVkTask])

  useEffect(() => {
    const controller = new AbortController()
    setNativeError('')
    fetchVkNativeState(controller.signal).then(value => {
      if (!controller.signal.aborted) setNative(value)
    }).catch(error => {
      if (!controller.signal.aborted) setNativeError(
        error instanceof Error ? error.message : 'Не удалось получить VK-баланс.',
      )
    })
    return () => controller.abort()
  }, [nativeRetry])

  useEffect(() => {
    if (view !== 'mine') return
    const controller = new AbortController()
    setCommerceError('')
    fetchVkNativeCommerce(controller.signal).then(result => {
      if (!controller.signal.aborted) setCommerce(result)
    }).catch(error => {
      if (!controller.signal.aborted) setCommerceError(
        error instanceof Error ? error.message : 'Не удалось получить историю оплат.',
      )
    })
    return () => controller.abort()
  }, [view, nativeRetry])

  useEffect(() => {
    const controller = new AbortController()
    if (view === 'mine') {
      setBusy(false)
      return () => controller.abort()
    }
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

  const switchView = (next: 'trends' | 'feed' | 'mine') => {
    closeLinkedTrend()
    closeLinkedFeed()
    setShareLink('')
    setView(next)
    setRepeatItem(null)
    setCreatePhoto(false)
    setCreateVideo(false)
    setCategoryId(null)
    setCategory(null)
    setDiscovery(null)
    setPage(1)
  }

  return <section aria-label="Каталог ВКонтакте" className="space-y-4">
    <div className="rounded-xl border border-border/70 bg-card p-3 text-sm">
      {native?.registered
        ? <strong>VK-баланс: {native.balance} 🍌</strong>
        : nativeError
          ? <div role="alert">{nativeError}
              <button type="button" className="ml-2 underline" onClick={() => setNativeRetry(v => v + 1)}>Обновить VK-баланс</button>
            </div>
          : native ? <span>Вы ещё не начинали работу в VK-боте.</span>
            : <span>Загружаем VK-баланс…</span>}
    </div>
    {((discovery && 'can_generate_in_app' in discovery && discovery.can_generate_in_app)
      || category?.can_generate_in_app) && <button type="button"
        className="w-full rounded-xl bg-primary p-3 font-semibold text-primary-foreground"
        onClick={() => { setRepeatItem(null); setCreateVideo(false); setCreatePhoto(true) }}>Создать фото</button>}
    {native?.video_generation_enabled === true && native.registered && !native.is_blocked
      ? <button type="button" className="w-full rounded-xl bg-primary p-3 font-semibold text-primary-foreground"
        onClick={() => { setRepeatItem(null); setCreatePhoto(false); setCreateVideo(true) }}>Создать видео</button>
      : null}
    {(createPhoto || repeatItem || createVideo) ? <VkGenerationPanel
      key={repeatItem?.id ?? (createVideo ? 'video' : 'new')}
      kind={createVideo ? 'video' : 'photo'}
      trend={repeatItem ?? undefined} onClose={() => {
        setCreatePhoto(false); setCreateVideo(false); setRepeatItem(null)
      }}
      onFinished={() => setNativeRetry(v => v + 1)} /> : null}
    <div className="flex flex-wrap gap-2">
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
      <button type="button" aria-pressed={view === 'mine'}
        onClick={() => switchView('mine')}
        className={'rounded-xl px-4 py-2 text-sm font-medium ' + (view === 'mine' ? 'bg-primary text-primary-foreground' : 'border border-border')}>
        Мои работы
      </button>
    </div>
    {shareLink ? <div role="dialog" aria-label="Поделиться трендом"
      className="space-y-3 rounded-xl border border-border bg-card p-3">
      <h3 className="text-sm font-semibold">Ссылка на «{shareTitle}»</h3>
      <input aria-label="Ссылка на тренд" type="text" readOnly value={shareLink}
        onFocus={event => event.currentTarget.select()}
        className="w-full rounded-lg border border-border bg-background p-2 text-xs" />
      <div className="flex flex-wrap gap-2">
        <button type="button" className="rounded-lg bg-primary p-2 text-sm text-primary-foreground"
          onClick={() => {
            if (!navigator.clipboard?.writeText) {
              setShareCopyMessage('Выделите ссылку в поле и скопируйте вручную.')
              return
            }
            void navigator.clipboard.writeText(shareLink).then(
              () => setShareCopyMessage('Ссылка скопирована'),
              () => setShareCopyMessage('Выделите ссылку в поле и скопируйте вручную.'),
            )
          }}>Копировать ссылку</button>
        <button type="button" className="rounded-lg border border-border p-2 text-sm"
          onClick={() => setShareLink('')}>Закрыть</button>
      </div>
      {shareCopyMessage ? <p role="status" className="text-sm">{shareCopyMessage}</p> : null}
    </div> : null}
    {view === 'trends' && linkedTrendId !== null ? <div aria-label="Тренд по ссылке"
      className="space-y-3 rounded-xl border border-border bg-card p-3">
      <h3 className="text-base font-semibold">Тренд по ссылке</h3>
      {linkedTrendLoading ? <p role="status">Загружаем тренд по ссылке…</p> : null}
      {linkedTrendError ? <p role="alert" className="text-destructive">{linkedTrendError}</p> : null}
      {linkedTrend ? <TrendCard item={linkedTrend}
        onRepeat={selected => { setRepeatItem(selected); setCreatePhoto(false) }}
        onShare={openShareLink} /> : null}
      <button type="button" onClick={closeLinkedTrend}
        className="rounded-lg border border-border p-2 text-sm">Вернуться к трендам</button>
    </div> : null}
    {view === 'feed' && linkedFeedTarget ? <section
      role="region"
      aria-label={linkedFeedTarget.kind === 'remix' ? 'Повтор публикации из ленты' : 'Публикация из ленты'}
      className="space-y-3 rounded-xl border border-border bg-card p-3">
      <h3 className="text-base font-semibold">
        {linkedFeedTarget.kind === 'remix' ? 'Повтор публикации из ленты' : 'Публикация из ленты'}
      </h3>
      {linkedFeedLoading ? <p role="status">Загружаем публикацию…</p> : null}
      {linkedFeedError ? <p role="alert" className="text-destructive">{linkedFeedError}</p> : null}
      {linkedFeed ? <>
        {linkedFeed.feed_blurred || linkedFeed.media_unavailable
          ? <p role="status">Медиа этой публикации сейчас недоступно.</p>
          : <Preview
              title="Публичная работа"
              image={linkedFeed.generation_type === 'image'
                ? linkedFeed.preview_url || linkedFeed.result_url
                : linkedFeed.preview_poster_url}
              video={linkedFeed.generation_type === 'video'
                ? linkedFeed.result_url || linkedFeed.preview_url : null}
            />}
        <p className="text-sm text-muted-foreground">
          {linkedFeed.generation_type === 'video' ? '🎬 Видео' : '🖼 Фото'}
          {' · '}{linkedFeed.model.charAt(0).toUpperCase() + linkedFeed.model.slice(1).replaceAll('_', ' ')}
          {' · ❤ '}{linkedFeed.likes_count}
        </p>
        {linkedFeed.can_like_in_app && <button type="button"
          disabled={likeBusyId === linkedFeed.id || likedIds.has(linkedFeed.id)}
          onClick={() => void likeFeed(linkedFeed.id)}
          className="rounded-lg border border-border px-3 py-2 text-sm">
          {likedIds.has(linkedFeed.id) ? 'Вам нравится' : 'Нравится'}
        </button>}
        {linkedFeedTarget.kind === 'remix'
          ? <p className="text-sm text-muted-foreground">
              Повтор этой публикации в VK Mini App пока не подключён к защищённому VK-балансу.
              Скрытые автором промпт и референсы не раскрываются.
            </p> : null}
      </> : null}
      <button type="button" onClick={closeLinkedFeed}
        className="rounded-lg border border-border p-2 text-sm">Вернуться к ленте</button>
    </section> : null}
    {view === 'mine' ? <div className="space-y-3">
      {commerce?.registered && commerce.payments_enabled === true &&
        <VkNativeCheckout packages={commerce.payment_packages}
          attempt={checkoutAttempt} onAttemptChange={setCheckoutAttempt} />}
      {commerce?.registered && <section aria-label="Мои оплаты и партнёрство ВКонтакте"
        className="space-y-2 rounded-xl border border-border/70 bg-card p-3 text-sm">
        <h3 className="text-base font-semibold">Оплаты и партнёрская программа</h3>
        <p>Рефералов первого уровня: {commerce.referrals.first_level_count}</p>
        <p>Второго уровня: {commerce.referrals.second_level_count}</p>
        <p>Партнёрский доход: {commerce.referrals.earned_rub} ₽</p>
        <h4 className="font-medium">Последние оплаты</h4>
        {commerce.payments.length ? <ul className="space-y-1">
          {commerce.payments.map((payment, index) => <li key={`${payment.created_at}-${index}`}>
            {payment.amount_rub} ₽ · {payment.status === 'paid' ? 'Зачислено' : payment.status === 'pending' ? 'Ожидает оплату' : 'Не оплачено'}
          </li>)}
        </ul> : <p>Пополнений пока нет.</p>}
      </section>}
      {commerceError && <p role="alert" className="text-sm">История оплат VK недоступна: {commerceError}</p>}
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-base font-semibold">Мои генерации ВКонтакте</h3>
        <button type="button" className="text-sm underline" onClick={() => setNativeRetry(v => v + 1)}>Обновить</button>
      </div>
      {!native && !nativeError ? <p role="status">Загружаем историю…</p> : null}
      {native?.is_blocked ? <p role="alert">Доступ VK-бота ограничен. Обратитесь в поддержку.</p> : null}
      {native && nativeTasks === null ? <p role="alert">История работ временно недоступна. Обновите список.</p> : null}
      {native && nativeTasks?.length === 0 ? <p>Генераций пока нет.</p> : null}
      {nativeTasks?.map(task => (
        <article key={task.task_id} className="space-y-1 rounded-xl border border-border/70 bg-card p-3 text-sm">
          <p className="font-medium">#{task.task_id} · {task.task_type === 'video' ? '🎬 Видео' : '🖼 Фото'} · {task.model}</p>
          <p className="text-muted-foreground">Статус: {task.status === 'completed' ? 'Готово' : task.status === 'failed' ? 'Ошибка' : 'В работе'} · {task.cost} 🍌</p>
          {mediaUrl(task.result_url) && <a
            className="text-primary underline" href={mediaUrl(task.result_url)} target="_blank" rel="noopener noreferrer">
            Открыть результат #{task.task_id}
          </a>}
        </article>
      ))}
    </div> : null}
    {view !== 'mine' && linkedTrendId === null && linkedFeedTarget === null && categoryId !== null ? (
      <button type="button" className="text-sm underline" onClick={() => {
        setCategoryId(null); setCategory(null); setPage(1)
      }}>← Ко всем трендам</button>
    ) : null}
    {likeError && <p role="alert" className="text-sm text-destructive">{likeError}</p>}
    {view !== 'mine' && linkedTrendId === null && linkedFeedTarget === null && error ? <div role="alert" className="space-y-2 text-sm">
      <p>{error}</p>
      <button type="button" className="underline" onClick={() => setRetry(x => x + 1)}>Повторить загрузку</button>
    </div> : null}
    {view !== 'mine' && linkedTrendId === null && linkedFeedTarget === null && busy && !discovery && !category ? <p role="status" className="text-sm text-muted-foreground">Загружаем тренды…</p> : null}
    {view !== 'mine' && linkedTrendId === null && linkedFeedTarget === null && categoryId !== null && category ? <>
      <h3 className="text-lg font-semibold">{category.category.emoji} {category.category.title}</h3>
      <div className="grid grid-cols-2 gap-3">
        {category.items.map(item => <TrendCard key={item.id} item={item}
          onRepeat={selected => { setRepeatItem(selected); setCreatePhoto(false) }} onShare={openShareLink} />)}
      </div>
      {category.has_more ? <button type="button" disabled={busy}
        onClick={() => setPage(value => value + 1)} className="w-full rounded-xl border border-border p-3 text-sm">
        {busy ? 'Загрузка…' : 'Показать ещё'}
      </button> : null}
    </> : null}
    {view !== 'mine' && linkedTrendId === null && linkedFeedTarget === null && categoryId === null && discovery && 'categories' in discovery ? discovery.categories.map(group => (
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
          {group.items.map(item => <TrendCard key={item.id} item={item}
            onRepeat={selected => { setRepeatItem(selected); setCreatePhoto(false) }} onShare={openShareLink} />)}
        </div>
      </div>
    )) : null}
    {view !== 'mine' && linkedTrendId === null && linkedFeedTarget === null && categoryId === null && discovery && 'items' in discovery ? (
      <div className="grid grid-cols-2 gap-3">
        {discovery.items.map(item => <FeedCard key={item.id} item={item}
          onLike={id => void likeFeed(id)}
          liking={likeBusyId === item.id}
          liked={likedIds.has(item.id)} />)}
      </div>
    ) : null}
    <p className="text-xs text-muted-foreground">
      {native?.video_generation_enabled === true
        ? 'Фото и видео создаются с VK-баланса. Видеореференсы и повторы видеотрендов пока доступны в боте сообщества.'
        : (discovery && 'can_generate_in_app' in discovery && discovery.can_generate_in_app) || category?.can_generate_in_app
          ? 'Фото и доступные фото-тренды создаются с VK-баланса. Видео пока доступно в боте сообщества.'
          : 'Просмотр открыт без Telegram. Оплачиваемый повтор непосредственно в Mini App появится после подключения защищённого VK-баланса и создания задач. Пока генерация доступна в боте сообщества.'}
    </p>
  </section>
}
