'use client'

import { useEffect, useMemo, useState } from 'react'
import { useApp } from '@/lib/app-context'
import type { FeedComment, FeedItem, ProfileSummary, ScenarioType } from '@/lib/types'
import { cn, isHttpUrl } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import {
  addFeedComment,
  fetchFeedComments,
  fetchMyFeed,
  fetchPartnerOverview,
  fetchProfileFeed,
  saveProfileChannel,
  shareFeedItem,
} from '@/lib/api'
import {
  Check,
  Copy,
  ExternalLink,
  Grid3X3,
  Heart,
  ImageOff,
  Link2,
  Loader2,
  MessageCircle,
  Play,
  Radio,
  Repeat2,
  Save,
  Send,
  Share2,
  Sparkles,
  UserRound,
  Video,
  Wallet,
  X,
} from 'lucide-react'

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function formatCompactNumber(value: number) {
  return new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function formatRub(value?: number) {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(Number(value || 0))
}

const videoScenarios = new Set<ScenarioType>(['text', 'imgtxt', 'video', 'avatar', 'audio', 'character'])

function normalizeVideoScenario(value?: string | null): ScenarioType {
  return videoScenarios.has(value as ScenarioType) ? (value as ScenarioType) : 'text'
}

function profileInitials(firstName?: string, lastName?: string, username?: string) {
  const value = `${firstName?.[0] || ''}${lastName?.[0] || ''}` || username?.[0] || 'U'
  return value.toUpperCase()
}

export function ProfileTab() {
  const { state, viewedProfileCode, setActiveTab, setPromptPreset, setVideoPromptPreset } = useApp()
  const { user } = state
  const [items, setItems] = useState<FeedItem[]>([])
  const [profile, setProfile] = useState<ProfileSummary | null>(null)
  const [previewItem, setPreviewItem] = useState<FeedItem | null>(null)
  const [commentsItem, setCommentsItem] = useState<FeedItem | null>(null)
  const [comments, setComments] = useState<FeedComment[]>([])
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [commentText, setCommentText] = useState('')
  const [ownChannelUrl, setOwnChannelUrl] = useState(user.channelUrl || '')
  const [channelInput, setChannelInput] = useState(user.channelUrl || '')
  const [channelSaving, setChannelSaving] = useState(false)
  const [partnerStats, setPartnerStats] = useState<{
    prompt_repeat_balance_rub: number
    prompt_repeat_total_rub: number
  } | null>(null)
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [copied, setCopied] = useState<'profile' | number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const isLive = state.mode === 'live'
  const ownReferralCode = String(user.referralCode || '').trim().toUpperCase()
  const targetReferralCode = String(viewedProfileCode || '').trim().toUpperCase()
  const isOwnProfile = !targetReferralCode || targetReferralCode === ownReferralCode
  const displayName = isOwnProfile
    ? [user.firstName, user.lastName].filter(Boolean).join(' ') || user.username || 'Профиль'
    : profile?.display_name || profile?.username || 'Профиль'
  const handle = isOwnProfile
    ? user.username
      ? `@${user.username}`
      : user.telegramId
        ? `id${user.telegramId}`
        : '@profile'
    : profile?.username
      ? `@${profile.username}`
      : profile?.referral_code
        ? profile.referral_code
        : '@profile'
  const avatarUrl = isOwnProfile ? user.photoUrl : profile?.photo_url
  const avatarFallback = profileInitials(
    isOwnProfile ? user.firstName : profile?.first_name,
    isOwnProfile ? user.lastName : profile?.last_name,
    isOwnProfile ? user.username : profile?.username
  )
  const profileShareLink =
    isOwnProfile
      ? user.profileLink ||
        (user.botUsername && ownReferralCode
          ? `https://t.me/${user.botUsername}?start=posts_${ownReferralCode}_ref_${ownReferralCode}`
          : '')
      : ''
  const displayChannelUrl = isOwnProfile ? ownChannelUrl : profile?.channel_url || ''
  const repeatBalance =
    partnerStats?.prompt_repeat_balance_rub ?? user.promptRepeatBalanceRub ?? 0
  const repeatTotal =
    partnerStats?.prompt_repeat_total_rub ?? user.promptRepeatTotalRub ?? 0

  const demoItems = useMemo(() => {
    return state.recentTasks.reduce<FeedItem[]>((acc, task, index) => {
      const url = task.result_url || ''
      if (!['image', 'video'].includes(task.type) || task.status !== 'completed' || !isHttpUrl(url)) {
        return acc
      }
      const urls = (task.result_urls || []).filter(isHttpUrl)
      if (!urls.includes(url)) {
        urls.unshift(url)
      }
      acc.push({
        id: task.feed_id || index + 1,
        task_id: task.task_id,
        model: task.model_label || task.model,
        gen_type: task.type === 'video' ? 'video' : 'image',
        result_url: url,
        result_urls: urls,
        prompt: task.prompt_preview,
        likes_count: Math.max(2, 18 - index * 3),
        shares_count: Math.max(0, 5 - index),
        aspect_ratio: task.aspect_ratio || '1:1',
        duration: task.duration || null,
        scenario: task.type === 'video' ? 'text' : null,
        author: displayName,
        author_referral_code: ownReferralCode || null,
        author_photo_url: user.photoUrl || null,
        is_mine: true,
        remixes: Math.max(0, 4 - index),
        score: 0,
        created_at: task.created_at,
        prompt_hidden: task.prompt_hidden,
        prompt_actions_allowed: task.prompt_actions_allowed,
      })
      return acc
    }, [])
  }, [displayName, ownReferralCode, state.recentTasks, user.photoUrl])

  const profileItems = isLive ? items : demoItems
  const totals = useMemo(() => {
    return profileItems.reduce(
      (acc, item) => ({
        posts: acc.posts + 1,
        likes: acc.likes + item.likes_count,
        shares: acc.shares + item.shares_count,
        remixes: acc.remixes + item.remixes,
      }),
      { posts: 0, likes: 0, shares: 0, remixes: 0 }
    )
  }, [profileItems])

  useEffect(() => {
    let ignore = false

    async function loadProfileFeed() {
      if (!isLive) {
        setItems([])
        setProfile(null)
        setError(null)
        return
      }

      setLoading(true)
      setError(null)
      try {
        if (isOwnProfile) {
          const feed = await fetchMyFeed(120)
          if (!ignore) {
            setItems(feed)
            setProfile(null)
          }
          return
        }

        const result = await fetchProfileFeed(targetReferralCode, 120)
        if (!ignore) {
          setItems(result.feed)
          setProfile(result.profile)
        }
      } catch (e) {
        if (!ignore) setError(getErrorMessage(e, 'Не удалось загрузить профиль'))
      } finally {
        if (!ignore) setLoading(false)
      }
    }

    loadProfileFeed()
    return () => {
      ignore = true
    }
  }, [isLive, isOwnProfile, targetReferralCode])

  useEffect(() => {
    if (!isOwnProfile) return
    setOwnChannelUrl(user.channelUrl || '')
    setChannelInput(user.channelUrl || '')
  }, [isOwnProfile, user.channelUrl])

  useEffect(() => {
    let ignore = false

    async function loadPartnerStats() {
      if (!isLive || !isOwnProfile) {
        setPartnerStats(null)
        return
      }
      try {
        const data = await fetchPartnerOverview()
        if (!ignore) {
          setPartnerStats({
            prompt_repeat_balance_rub: data.prompt_repeat_balance_rub || 0,
            prompt_repeat_total_rub: data.prompt_repeat_total_rub || 0,
          })
          setOwnChannelUrl(data.channel_url || user.channelUrl || '')
          setChannelInput(data.channel_url || user.channelUrl || '')
        }
      } catch {
        if (!ignore) setPartnerStats(null)
      }
    }

    loadPartnerStats()
    return () => {
      ignore = true
    }
  }, [isLive, isOwnProfile, user.channelUrl])

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

  async function copyText(text: string, marker: 'profile' | number) {
    if (!text || typeof navigator === 'undefined' || !navigator.clipboard) return
    await navigator.clipboard.writeText(text)
    setCopied(marker)
    window.setTimeout(() => setCopied(null), 1500)
  }

  async function handleCopyProfileLink() {
    if (!isOwnProfile || !profileShareLink) return
    try {
      await copyText(profileShareLink, 'profile')
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось скопировать ссылку'))
    }
  }

  async function handleCopyPostLink(item: FeedItem) {
    if (!isLive) return
    setBusyId(item.id)
    try {
      const { item: updated, link } = await shareFeedItem(item.id)
      setItems((prev) => prev.map((feedItem) => (feedItem.id === updated.id ? updated : feedItem)))
      await copyText(link, item.id)
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось создать ссылку на пост'))
    } finally {
      setBusyId(null)
    }
  }

  async function handleSaveChannel() {
    if (!isLive || !isOwnProfile) return
    setChannelSaving(true)
    setError(null)
    try {
      const nextUrl = await saveProfileChannel(channelInput)
      setOwnChannelUrl(nextUrl)
      setChannelInput(nextUrl)
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось сохранить канал'))
    } finally {
      setChannelSaving(false)
    }
  }

  async function handleSubmitComment() {
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
      setCommentsItem((prev) => (prev ? { ...prev, comments_count: commentsCount } : prev))
      setPreviewItem((prev) =>
        prev?.id === commentsItem.id ? { ...prev, comments_count: commentsCount } : prev
      )
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось отправить комментарий'))
    } finally {
      setBusyId(null)
    }
  }

  function handleRemix(item: FeedItem) {
    if (item.gen_type === 'video') {
      const modelExists = state.videoModels.some((model) => model.id === item.model)
      setVideoPromptPreset({
        title: 'Повторить видео из ленты',
        prompt: item.prompt || '',
        model: modelExists ? item.model : state.videoModels[0]?.id || 'v3_pro',
        scenario: normalizeVideoScenario(item.scenario),
        ratio: item.aspect_ratio || '16:9',
        duration: item.duration || 5,
        sourceFeedGenId: isLive ? item.id : null,
        promptHidden: item.prompt_hidden,
      })
      setActiveTab(2)
      return
    }
    const modelExists = state.imageModels.some((model) => model.id === item.model)
    setPromptPreset({
      promptId: null,
      title: 'Повторить публикацию',
      prompt: item.prompt || '',
      model: modelExists ? item.model : state.imageModels[0]?.id || 'banana_pro',
      ratio: item.aspect_ratio || '1:1',
      sourceFeedGenId: isLive ? item.id : null,
      promptHidden: item.prompt_hidden,
    })
    setActiveTab(1)
  }

  return (
    <div className="px-4 pb-28">
      <section className="space-y-5">
        <div className="flex items-center gap-4">
          <div className="rounded-full bg-gradient-to-tr from-gold via-cyan to-chart-4 p-0.5">
            <Avatar className="size-24 border-4 border-background bg-secondary">
              {isHttpUrl(avatarUrl) ? (
                <AvatarImage src={avatarUrl} alt={displayName} className="object-cover" />
              ) : null}
              <AvatarFallback className="bg-secondary text-2xl font-semibold text-foreground">
                {avatarFallback}
              </AvatarFallback>
            </Avatar>
          </div>

          <div className="grid min-w-0 flex-1 grid-cols-3 gap-2 text-center">
            <div>
              <div className="text-lg font-bold text-foreground">{formatCompactNumber(totals.posts)}</div>
              <div className="text-[11px] text-muted-foreground">постов</div>
            </div>
            <div>
              <div className="text-lg font-bold text-foreground">{formatCompactNumber(totals.likes)}</div>
              <div className="text-[11px] text-muted-foreground">лайков</div>
            </div>
            <div>
              <div className="text-lg font-bold text-foreground">{formatCompactNumber(totals.remixes)}</div>
              <div className="text-[11px] text-muted-foreground">ремиксов</div>
            </div>
          </div>
        </div>

        <div className="min-w-0 space-y-1.5">
          <h2 className="truncate text-xl font-semibold text-foreground">{displayName}</h2>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <UserRound className="h-4 w-4 shrink-0" />
            <span className="truncate">{handle}</span>
          </div>
          {profileShareLink ? (
            <div className="flex items-center gap-2 text-sm text-cyan">
              <Link2 className="h-4 w-4 shrink-0" />
              <span className="truncate">{profileShareLink}</span>
            </div>
          ) : null}
        </div>

        {isOwnProfile ? (
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-border/50 bg-card/45 p-3">
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Wallet className="h-3.5 w-3.5" />
                <span>Повторы</span>
              </div>
              <div className="mt-1 text-base font-semibold text-foreground">
                {formatRub(repeatBalance)} ₽
              </div>
            </div>
            <div className="rounded-lg border border-border/50 bg-card/45 p-3">
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Sparkles className="h-3.5 w-3.5" />
                <span>Всего</span>
              </div>
              <div className="mt-1 text-base font-semibold text-foreground">
                {formatRub(repeatTotal)} ₽
              </div>
            </div>
          </div>
        ) : null}

        {isOwnProfile ? (
          <div className="rounded-lg border border-border/50 bg-card/45 p-3">
            <div className="mb-2 flex items-center gap-2 text-sm font-medium text-foreground">
              <Radio className="h-4 w-4 text-cyan" />
              <span>Канал</span>
            </div>
            <div className="grid grid-cols-[1fr_auto] gap-2">
              <input
                value={channelInput}
                onChange={(event) => setChannelInput(event.target.value)}
                maxLength={160}
                className="h-10 min-w-0 rounded-lg border border-border/60 bg-background px-3 text-sm text-foreground outline-none focus:border-cyan"
                placeholder="@channel"
              />
              <Button
                type="button"
                size="icon"
                className="h-10 w-10 rounded-lg"
                disabled={channelSaving || !isLive}
                onClick={handleSaveChannel}
                aria-label="Сохранить канал"
              >
                {channelSaving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
              </Button>
            </div>
            {displayChannelUrl ? (
              <a
                href={displayChannelUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-2 flex min-w-0 items-center gap-1.5 text-sm text-cyan"
              >
                <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{displayChannelUrl}</span>
              </a>
            ) : null}
          </div>
        ) : displayChannelUrl ? (
          <Button asChild type="button" variant="secondary" className="h-10 rounded-lg">
            <a href={displayChannelUrl} target="_blank" rel="noreferrer">
              <Radio className="h-4 w-4" />
              <span className="truncate">Канал автора</span>
            </a>
          </Button>
        ) : null}

        {isOwnProfile ? (
          <div className="grid grid-cols-[1fr_auto] gap-2">
            <Button
              type="button"
              variant="secondary"
              className="h-10 min-w-0 rounded-lg px-3"
              disabled={!profileShareLink}
              onClick={handleCopyProfileLink}
            >
              {copied === 'profile' ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              <span className="truncate">{copied === 'profile' ? 'Скопировано' : 'Ссылка на профиль'}</span>
            </Button>
            {profileShareLink ? (
              <Button asChild type="button" variant="secondary" size="icon" className="h-10 w-10 rounded-lg">
                <a href={profileShareLink} target="_blank" rel="noreferrer" aria-label="Открыть профиль">
                  <ExternalLink className="h-4 w-4" />
                </a>
              </Button>
            ) : (
              <Button type="button" variant="secondary" size="icon" className="h-10 w-10 rounded-lg" disabled>
                <ExternalLink className="h-4 w-4" />
              </Button>
            )}
          </div>
        ) : null}
      </section>

      <div className="mt-6 flex items-center justify-center border-t border-border/60 py-3 text-gold">
        <Grid3X3 className="h-5 w-5" />
      </div>

      {error ? (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex justify-center py-10 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : profileItems.length ? (
        <div className="grid grid-cols-4 gap-px sm:grid-cols-5">
          {profileItems.map((item) => (
            <article key={item.id} className="relative aspect-square min-w-0 overflow-hidden bg-secondary/80">
              <button
                type="button"
                className="group h-full w-full text-left"
                onClick={() => setPreviewItem(item)}
                aria-label="Открыть публикацию"
              >
                {isHttpUrl(item.result_url) ? (
                  item.gen_type === 'video' ? (
                    <video
                      src={item.result_url}
                      muted
                      playsInline
                      preload="metadata"
                      className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]"
                    />
                  ) : (
                    <img
                      src={item.result_url}
                      alt=""
                      loading="lazy"
                      className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]"
                    />
                  )
                ) : (
                  <span className="flex h-full w-full items-center justify-center text-muted-foreground">
                    <ImageOff className="h-5 w-5" />
                  </span>
                )}
                {item.gen_type === 'video' ? (
                  <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
                    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-background/75 text-foreground backdrop-blur">
                      <Play className="h-4 w-4 fill-current" />
                    </span>
                  </span>
                ) : null}
                <span className="pointer-events-none absolute inset-0 bg-background/0 transition-colors group-hover:bg-background/35" />
                <span className="pointer-events-none absolute left-1 top-1 hidden rounded bg-background/75 px-1 py-0.5 text-[9px] font-medium text-foreground opacity-0 backdrop-blur transition-opacity group-hover:opacity-100 min-[420px]:block">
                  {item.gen_type === 'video' ? (
                    <span className="inline-flex items-center gap-0.5">
                      <Video className="h-3 w-3" />
                      {item.duration ? `${item.duration}с` : item.aspect_ratio || 'video'}
                    </span>
                  ) : (
                    item.aspect_ratio || '1:1'
                  )}
                </span>
                <span className="pointer-events-none absolute bottom-1 left-1 hidden items-center gap-0.5 rounded bg-background/75 px-1 py-0.5 text-[9px] font-medium text-foreground opacity-0 backdrop-blur transition-opacity group-hover:opacity-100 min-[420px]:flex">
                  <Heart className="h-3 w-3" />
                  {formatCompactNumber(item.likes_count)}
                </span>
                <span className="pointer-events-none absolute bottom-1 right-1 hidden items-center gap-0.5 rounded bg-background/75 px-1 py-0.5 text-[9px] font-medium text-foreground opacity-0 backdrop-blur transition-opacity group-hover:opacity-100 min-[420px]:flex">
                  <Sparkles className="h-3 w-3" />
                  {formatCompactNumber(item.remixes)}
                </span>
              </button>
              <button
                type="button"
                className={cn(
                  'absolute bottom-1 left-1 flex h-6 w-6 items-center justify-center rounded-full',
                  'bg-background/80 text-foreground backdrop-blur transition-colors hover:bg-background',
                  (!isLive || busyId === item.id) && 'opacity-60'
                )}
                disabled={!isLive || busyId === item.id}
                onClick={() => handleCopyPostLink(item)}
                aria-label="Скопировать ссылку на пост"
              >
                {busyId === item.id ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : copied === item.id ? (
                  <Check className="h-3 w-3" />
                ) : (
                  <Share2 className="h-3 w-3" />
                )}
              </button>
              <button
                type="button"
                className="absolute bottom-1 right-1 flex h-6 min-w-6 items-center justify-center gap-0.5 rounded-full bg-background/80 px-1.5 text-[10px] font-medium text-foreground backdrop-blur transition-colors hover:bg-background disabled:opacity-60"
                disabled={!isLive}
                onClick={() => setCommentsItem(item)}
                aria-label="Комментарии"
              >
                <MessageCircle className="h-3 w-3" />
                {item.comments_count || 0}
              </button>
            </article>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-border/50 bg-card/45 p-6 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-muted-foreground">
            <Grid3X3 className="h-6 w-6" />
          </div>
          <p className="mt-3 text-sm font-medium text-foreground">Публикаций пока нет</p>
          <p className="mt-1 text-sm text-muted-foreground">В профиле появятся фото и видео, опубликованные в ленте.</p>
          <Button
            type="button"
            variant="secondary"
            className="mt-4 rounded-lg"
            onClick={() => setActiveTab(4)}
          >
            Открыть ленту
          </Button>
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
            previewItem.gen_type === 'video' ? (
              <video
                src={previewItem.result_url}
                className="max-h-full w-auto max-w-full object-contain"
                controls
                autoPlay
                playsInline
              />
            ) : (
              <img
                src={previewItem.result_url}
                alt=""
                className="max-h-full w-auto max-w-full object-contain"
              />
            )
          ) : (
            <div className="flex h-48 w-full items-center justify-center text-muted-foreground">
              <ImageOff className="h-8 w-8" />
            </div>
          )}
          <div className="absolute bottom-4 left-3 right-3 flex justify-center gap-2">
            <Button
              type="button"
              variant="secondary"
              className="h-10 rounded-full bg-secondary/90 px-4"
              disabled={!isLive}
              onClick={() => setCommentsItem(previewItem)}
            >
              <MessageCircle className="h-4 w-4" />
              {previewItem.comments_count || 0}
            </Button>
            <Button
              type="button"
              className="h-10 rounded-full px-4"
              onClick={() => handleRemix(previewItem)}
            >
              <Repeat2 className="h-4 w-4" />
              <span>Повторить</span>
            </Button>
          </div>
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
                disabled={!commentText.trim() || busyId === commentsItem.id || !isLive}
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
