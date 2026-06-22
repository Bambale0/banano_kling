'use client'

import { useEffect, useMemo, useState } from 'react'
import { useApp } from '@/lib/app-context'
import type { PromptItem } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { deactivatePrompt, fetchPrompts, likePrompt, submitPrompt } from '@/lib/api'
import { Heart, Loader2, Plus, Send, Sparkles, Trash2, Wand2 } from 'lucide-react'

const sources = [
  { id: 'catalog', label: 'Каталог' },
  { id: 'popular', label: 'Популярные' },
  { id: 'top', label: 'Топ' },
  { id: 'my', label: 'Мои' },
] as const

const tagTabs = ['cinematic', 'realism', 'portrait']

export function PromptsTab() {
  const { state, setActiveTab, setPromptPreset } = useApp()
  const [source, setSource] = useState<(typeof sources)[number]['id']>('catalog')
  const [tag, setTag] = useState('')
  const [items, setItems] = useState<PromptItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitOpen, setIsSubmitOpen] = useState(false)
  const [draftTitle, setDraftTitle] = useState('')
  const [draftText, setDraftText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [removingPromptId, setRemovingPromptId] = useState<number | null>(null)

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
        const prompts = await fetchPrompts({
          source: tag ? 'tag' : source,
          tag,
          limit: 24,
        })
        if (!ignore) setItems(prompts)
      } catch (e) {
        if (!ignore) setError(e instanceof Error ? e.message : 'Не удалось загрузить библиотеку')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => {
      ignore = true
    }
  }, [isLive, source, tag])

  const emptyText = useMemo(() => {
    if (!isLive) return 'Откройте mini app из Telegram, чтобы увидеть опубликованные промпты.'
    if (source === 'my') return 'Ваши опубликованные промпты появятся здесь.'
    return 'В этой подборке пока пусто.'
  }, [isLive, source])

  const confirmPublication = () => {
    if (typeof window === 'undefined') return true
    return window.confirm(
      'Публикация в ленту промптов\n\n' +
        'Вы подтверждаете, что у вас есть права или согласие на текст промпта и прикреплённые материалы.\n\n' +
        'Ответственность за опубликованный пользовательский контент несёт пользователь. Администрация бота не проводит предварительную модерацию и не отвечает за материалы, которые пользователи выкладывают самостоятельно.'
    )
  }

  const applyPrompt = (prompt: PromptItem) => {
    setPromptPreset({
      promptId: prompt.id,
      title: prompt.title,
      prompt: prompt.prompt_text,
      model: prompt.model,
    })
    setActiveTab(1)
  }

  const handleLike = async (prompt: PromptItem) => {
    if (!isLive || prompt.status !== 'approved') return
    try {
      const updated = await likePrompt(prompt.id)
      setItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось поставить лайк')
    }
  }

  const handleSubmit = async () => {
    if (!draftText.trim() || submitting) return
    if (!confirmPublication()) return
    setSubmitting(true)
    setError(null)
    try {
      const created = await submitPrompt({
        title: draftTitle,
        description: '',
        promptText: draftText,
        tags: [],
      })
      setItems((prev) => [created, ...prev])
      setDraftTitle('')
      setDraftText('')
      setIsSubmitOpen(false)
      setSource('my')
      setTag('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось отправить промпт')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDeactivate = async (prompt: PromptItem) => {
    if (!isLive || removingPromptId) return
    setRemovingPromptId(prompt.id)
    try {
      await deactivatePrompt(prompt.id)
      setItems((prev) => prev.filter((item) => item.id !== prompt.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось убрать промпт')
    } finally {
      setRemovingPromptId(null)
    }
  }

  return (
    <div className="px-4 space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="font-serif text-xl font-semibold text-foreground">Библиотека промптов</h2>
          <p className="mt-1 text-sm text-muted-foreground">Готовые идеи для быстрого запуска фото.</p>
        </div>
        <Button
          type="button"
          size="icon"
          className="bg-gold text-primary-foreground hover:bg-gold/90"
          onClick={() => setIsSubmitOpen((value) => !value)}
          disabled={!isLive}
          aria-label="Добавить промпт"
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-1">
        {sources.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => {
              setSource(item.id)
              setTag('')
            }}
            className={cn(
              'rounded-lg border px-3 py-2 text-xs font-medium transition-colors',
              source === item.id && !tag
                ? 'border-gold/50 bg-gold/15 text-gold'
                : 'border-border/50 bg-secondary/50 text-muted-foreground'
            )}
          >
            {item.label}
          </button>
        ))}
        {tagTabs.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setTag(item)}
            className={cn(
              'rounded-lg border px-3 py-2 text-xs font-medium transition-colors',
              tag === item
                ? 'border-cyan/50 bg-cyan/15 text-cyan'
                : 'border-border/50 bg-secondary/50 text-muted-foreground'
            )}
          >
            #{item}
          </button>
        ))}
      </div>

      {isSubmitOpen && (
        <div className="glass rounded-2xl border border-border/50 p-4 space-y-3">
          <input
            value={draftTitle}
            onChange={(event) => setDraftTitle(event.target.value)}
            placeholder="Название"
            className="h-10 w-full rounded-lg border border-border/50 bg-secondary/50 px-3 text-sm outline-none focus:border-gold/50"
            maxLength={60}
          />
          <Textarea
            value={draftText}
            onChange={(event) => setDraftText(event.target.value)}
            placeholder="Полный prompt для каталога..."
            className="min-h-[130px] resize-none bg-secondary/50"
          />
          <Button
            type="button"
            className="w-full bg-gold text-primary-foreground hover:bg-gold/90"
            disabled={!draftText.trim() || submitting}
            onClick={handleSubmit}
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Опубликовать
          </Button>
        </div>
      )}

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
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((prompt) => (
            <article key={prompt.id} className="glass rounded-2xl border border-border/50 p-4">
              {prompt.preview_url ? (
                <img
                  src={prompt.preview_url}
                  alt=""
                  className="mb-3 aspect-square w-full rounded-xl object-cover"
                />
              ) : (
                <div className="mb-3 flex aspect-square w-full items-center justify-center rounded-xl bg-secondary/50">
                  <Wand2 className="h-8 w-8 text-gold" />
                </div>
              )}
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-semibold text-foreground">{prompt.title}</h3>
                  <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{prompt.description}</p>
                </div>
                <span className="rounded-md bg-secondary/70 px-2 py-1 text-[10px] text-muted-foreground">
                  {prompt.status}
                </span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {prompt.tags.slice(0, 3).map((item) => (
                  <span key={item} className="rounded-md bg-cyan/10 px-2 py-1 text-[10px] text-cyan">
                    #{item}
                  </span>
                ))}
              </div>
              <div className={cn('mt-4 grid gap-2', source === 'my' ? 'grid-cols-[1fr_auto_auto]' : 'grid-cols-[1fr_auto]')}>
                <Button
                  type="button"
                  size="sm"
                  className="bg-gold text-primary-foreground hover:bg-gold/90"
                  onClick={() => applyPrompt(prompt)}
                  disabled={prompt.status !== 'approved'}
                >
                  <Sparkles className="h-4 w-4" />
                  В фото
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => handleLike(prompt)}
                  disabled={prompt.status !== 'approved'}
                >
                  <Heart className="h-4 w-4" />
                  {prompt.likes}
                </Button>
                {source === 'my' && (
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => handleDeactivate(prompt)}
                    disabled={removingPromptId === prompt.id}
                    aria-label="Убрать промпт"
                  >
                    {removingPromptId === prompt.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  </Button>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="glass rounded-2xl border border-border/50 p-6 text-center text-sm text-muted-foreground">
          {emptyText}
        </div>
      )}
    </div>
  )
}
