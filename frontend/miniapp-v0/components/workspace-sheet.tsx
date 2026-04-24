'use client'

import { useMemo, useState } from 'react'
import { Bot, BriefcaseBusiness, Copy, Headphones, ImagePlus, Layers, Loader2, PanelTopOpen, Send, Sparkles, Wand2 } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'
import { askAIAssistant, fetchPartnerOverview, photoToPrompt, uploadFile } from '@/lib/api'
import type { WorkspacePanel } from '@/lib/types'

type ChatRole = 'assistant' | 'user'
type ChatMessage = {
  id: string
  role: ChatRole
  text: string
}

const workspaceConfig: Record<
  WorkspacePanel,
  { title: string; description: string; icon: typeof Sparkles }
> = {
  assistant: {
    title: 'AI-помощник',
    description: 'Помогает выбрать модель, улучшить запрос и быстро определиться со сценарием.',
    icon: Bot,
  },
  'photo-prompt': {
    title: 'Промпт по фото',
    description: 'Собирает сильное описание по референсу и сразу подводит к запуску.',
    icon: Wand2,
  },
  partners: {
    title: 'Партнёрская программа',
    description: 'Показывает условия, выгоду и следующие шаги в одном окне.',
    icon: BriefcaseBusiness,
  },
  support: {
    title: 'Поддержка',
    description: 'Помогает быстро собрать обращение и не потерять важные детали по задаче.',
    icon: Headphones,
  },
  'batch-edit': {
    title: 'Batch Edit',
    description: 'Подходит для серии изображений, когда нужен один стиль и один набор правил.',
    icon: Layers,
  },
  more: {
    title: 'Ещё',
    description: 'Быстрые переходы к полезным разделам студии.',
    icon: PanelTopOpen,
  },
}

const assistantStarters = [
  'Какую модель взять для рекламного фото?',
  'Мне нужно видео до 15 секунд',
  'Помоги улучшить мой запрос',
]

export function WorkspaceSheet() {
  const { activeWorkspace, closeWorkspace, setActiveTab, openWorkspace } = useApp()
  const config = activeWorkspace ? workspaceConfig[activeWorkspace] : null
  const Icon = config?.icon || Sparkles

  return (
    <Sheet open={Boolean(activeWorkspace)} onOpenChange={(open) => !open && closeWorkspace()}>
      <SheetContent side="bottom" className="h-[86vh] rounded-t-[28px] border-border/50 bg-background/95 px-0">
        <SheetHeader className="px-5 pt-3 text-left">
          <div className="mb-2">
            <div className="mb-2 h-1 w-10 rounded-full bg-border/80" />
            <SheetTitle className="flex items-center gap-2 font-serif text-[2rem] leading-none text-foreground">
              <Icon className="h-5 w-5 text-gold" />
              {config?.title}
            </SheetTitle>
            <SheetDescription className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
              {config?.description}
            </SheetDescription>
          </div>
        </SheetHeader>

        <div className="h-[calc(86vh-98px)] overflow-auto px-5 pb-6">
          {activeWorkspace === 'assistant' && <AssistantChat starters={assistantStarters} />}
          {activeWorkspace === 'photo-prompt' && (
            <PhotoPromptPanel
              onOpenPhoto={() => {
                closeWorkspace()
                setActiveTab(1)
              }}
            />
          )}
          {activeWorkspace === 'partners' && <PartnersPanel />}
          {activeWorkspace === 'support' && <SupportPanel />}
          {activeWorkspace === 'batch-edit' && <BatchEditPanel />}
          {activeWorkspace === 'more' && (
            <MorePanel
              onPhoto={() => {
                closeWorkspace()
                setActiveTab(1)
              }}
              onVideo={() => {
                closeWorkspace()
                setActiveTab(2)
              }}
              onAssistant={() => openWorkspace('assistant')}
              onPartners={() => openWorkspace('partners')}
              onSupport={() => openWorkspace('support')}
            />
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function AssistantChat({ starters }: { starters: string[] }) {
  const { state, setActiveTab, closeWorkspace } = useApp()
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'assistant-1',
      role: 'assistant',
      text: `Я помогу быстро выбрать модель и собрать сильный запрос. Сейчас у вас ${state.user.credits}🍌. Что хотите сделать: фото, видео или доработать идею?`,
    },
  ])

  const sendMessage = async (text: string) => {
    const content = text.trim()
    if (!content || isLoading) return

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      text: content,
    }

    const nextHistory = [...messages, userMessage].slice(-6)
    setMessages(nextHistory)
    setInput('')
    setIsLoading(true)

    try {
      const historyForApi = nextHistory.map((m) => ({
        role: m.role,
        text: m.text,
      }))

      const { reply } = await askAIAssistant({
        message: content,
        history: historyForApi,
      })

      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        text: reply,
      }

      setMessages((prev) => [...prev, assistantMessage].slice(-6))
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Не удалось получить ответ'
      toast.error('AI-ассистент недоступен', { description: errorMessage })

      // Fallback на сценарный ответ, если backend недоступен
      const fallbackReply = buildFallbackReply(content, state.user.credits)
      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        text: fallbackReply,
      }
      setMessages((prev) => [...prev, assistantMessage].slice(-6))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {starters.map((starter) => (
          <button
            key={starter}
            type="button"
            onClick={() => sendMessage(starter)}
            disabled={isLoading}
            className="rounded-full border border-border/50 bg-secondary/20 px-3 py-2 text-xs text-foreground transition-colors hover:bg-secondary/40 disabled:opacity-50"
          >
            {starter}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {messages.map((message) => (
          <div
            key={message.id}
            className={cn(
              'max-w-[92%] rounded-2xl border px-4 py-3 text-sm leading-6',
              message.role === 'assistant'
                ? 'border-cyan/20 bg-cyan/10 text-foreground'
                : 'ml-auto border-gold/20 bg-gold/10 text-foreground'
            )}
          >
            {message.text}
          </div>
        ))}
        {isLoading && (
          <div className="flex max-w-[92%] items-center gap-2 rounded-2xl border border-cyan/20 bg-cyan/10 px-4 py-3 text-sm text-foreground">
            <Loader2 className="h-4 w-4 animate-spin text-cyan" />
            <span className="text-muted-foreground">Думаю…</span>
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-border/50 bg-secondary/20 p-3">
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          rows={3}
          disabled={isLoading}
          placeholder="Например: нужен ролик для карточки товара, вертикальный формат, спокойное движение камеры"
          className="w-full resize-none rounded-2xl border border-border/50 bg-background/60 px-4 py-3 text-sm text-foreground outline-none disabled:opacity-50"
        />
        <div className="mt-3 flex gap-3">
          <Button
            onClick={() => sendMessage(input)}
            disabled={isLoading || !input.trim()}
            className="flex-1 bg-gold text-primary-foreground hover:bg-gold/90 disabled:opacity-50"
          >
            {isLoading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-2 h-4 w-4" />
            )}
            {isLoading ? 'Думаю…' : 'Отправить'}
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              closeWorkspace()
              setActiveTab(1)
            }}
            className="border-border/50 bg-background/40 hover:bg-background/60"
          >
            Открыть Фото
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              closeWorkspace()
              setActiveTab(2)
            }}
            className="border-border/50 bg-background/40 hover:bg-background/60"
          >
            Открыть Видео
          </Button>
        </div>
      </div>
    </div>
  )
}

function buildFallbackReply(input: string, credits: number) {
  const text = input.toLowerCase()

  if (text.includes('15') || text.includes('видео')) {
    return `Для ролика до 15 секунд лучше начать с Kling 3.0 или Kling v3. Если нужен более выразительный результат, берите Kling 3.0. Если важнее скорость и аккуратный бюджет, подойдет Kling v3. Сразу выбирайте формат, длительность и коротко опишите движение камеры.`
  }

  if (text.includes('реклам') || text.includes('товар') || text.includes('карточк')) {
    return `Для рекламного фото я бы начал с Nano Banana Pro, а если нужно точнее править исходник — с Seedream 4.5 Edit. В запросе лучше отдельно прописать ракурс, свет, материал, фон и что именно должно выглядеть дороже.`
  }

  if (text.includes('улучш') || text.includes('запрос') || text.includes('prompt')) {
    return `Хороший запрос лучше строить так: что в кадре, какой ракурс, какой свет, какая атмосфера и что важно не потерять. Если хотите, напишите вашу идею одной фразой, а я превращу её в более сильный вариант.`
  }

  if (text.includes('баланс') || text.includes('сколько')) {
    return `Сейчас у вас ${credits}🍌. Если задача тестовая, начните с одного варианта и короткого запроса. Когда понравится направление, можно усиливать качество, длительность или количество результатов.`
  }

  return `Понял задачу. Я бы сейчас уточнил три вещи: что должно быть в центре внимания, какой нужен формат и какое настроение вы хотите получить. После этого выбор модели и настройка запуска становятся намного точнее.`
}

function PhotoPromptPanel({ onOpenPhoto }: { onOpenPhoto: () => void }) {
  const [reference, setReference] = useState<{ name: string; url: string } | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [preserve, setPreserve] = useState('композицию, лицо/объект, свет, цвета и стиль')
  const [goal, setGoal] = useState('максимально похожее изображение для повторной генерации')
  const [isUploading, setIsUploading] = useState(false)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [result, setResult] = useState<{
    prompt_en: string
    prompt_ru: string
    negative_prompt: string
    model_hint: string
  } | null>(null)

  async function handleUpload(file: File) {
    setIsUploading(true)
    setResult(null)

    try {
      setPreviewUrl(URL.createObjectURL(file))
      const uploaded = await uploadFile('image_reference', file)
      setReference({
        name: uploaded.name,
        url: uploaded.url,
      })
      toast.success('Фото загружено')
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось загрузить фото'
      toast.error('Ошибка загрузки', { description: message })
    } finally {
      setIsUploading(false)
    }
  }

  async function analyzePhoto() {
    if (!reference) {
      toast.error('Сначала загрузите фото')
      return
    }

    setIsAnalyzing(true)
    setResult(null)

    try {
      const data = await photoToPrompt({
        imageUrl: reference.url,
        preserve,
        goal,
      })
      setResult(data)
      toast.success('Промпт собран')
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось собрать промпт'
      toast.error('Ошибка анализа', { description: message })
    } finally {
      setIsAnalyzing(false)
    }
  }

  async function copyText(text: string, label: string) {
    await navigator.clipboard.writeText(text)
    toast.success(`${label} скопирован`)
  }

  return (
    <div className="space-y-5 pb-10">
      <div className="rounded-[1.75rem] border border-gold/20 bg-gradient-to-br from-gold/[0.12] via-card/70 to-cyan/[0.08] p-5">
        <p className="text-[11px] uppercase tracking-[0.18em] text-gold">Prompt Lab</p>
        <h3 className="mt-2 font-serif text-2xl text-foreground">Фото → точный prompt</h3>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Загрузите референс. AI разберёт кадр и соберёт промпт для генерации похожего изображения:
          композиция, объект, свет, стиль, цвета и важные детали.
        </p>
      </div>

      <div className="rounded-[1.75rem] border border-border/60 bg-card/45 p-4">
        <label className="block cursor-pointer">
          <input
            type="file"
            accept="image/*"
            className="sr-only"
            disabled={isUploading || isAnalyzing}
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (!file) return
              handleUpload(file)
              event.target.value = ''
            }}
          />

          <div className="rounded-2xl border border-dashed border-border/70 bg-background/45 px-4 py-6 text-center transition-colors hover:border-gold/40">
            <ImagePlus className="mx-auto mb-3 h-8 w-8 text-gold" />
            <p className="font-medium text-foreground">
              {isUploading ? 'Загружаю фото…' : reference ? reference.name : 'Загрузить референс'}
            </p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Лучше использовать чёткий кадр без сильного блюра и лишних объектов.
            </p>
          </div>
        </label>

        {previewUrl && (
          <div className="mt-4 overflow-hidden rounded-2xl border border-border/50">
            <img src={previewUrl} alt="Референс" className="h-64 w-full object-cover" />
          </div>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
          <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
            Что сохранить
          </p>
          <textarea
            value={preserve}
            onChange={(event) => setPreserve(event.target.value)}
            rows={3}
            className="mt-3 w-full resize-none rounded-2xl border border-border/50 bg-background/50 px-4 py-3 text-sm text-foreground outline-none"
          />
        </div>

        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
          <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
            Какой результат нужен
          </p>
          <textarea
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            rows={3}
            className="mt-3 w-full resize-none rounded-2xl border border-border/50 bg-background/50 px-4 py-3 text-sm text-foreground outline-none"
          />
        </div>
      </div>

      <Button
        onClick={analyzePhoto}
        disabled={!reference || isUploading || isAnalyzing}
        className="h-14 w-full rounded-2xl bg-gold text-primary-foreground hover:bg-gold/90 disabled:opacity-50"
      >
        {isAnalyzing ? (
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        ) : (
          <Wand2 className="mr-2 h-5 w-5" />
        )}
        {isAnalyzing ? 'Анализирую фото…' : 'Собрать точный промпт'}
      </Button>

      {result && (
        <div className="space-y-3">
          <PromptResultCard
            title="Prompt EN"
            text={result.prompt_en}
            onCopy={() => copyText(result.prompt_en, 'Prompt EN')}
          />
          <PromptResultCard
            title="Prompt RU"
            text={result.prompt_ru}
            onCopy={() => copyText(result.prompt_ru, 'Prompt RU')}
          />
          <PromptResultCard
            title="Negative prompt"
            text={result.negative_prompt}
            onCopy={() => copyText(result.negative_prompt, 'Negative prompt')}
          />

          <div className="rounded-2xl border border-cyan/20 bg-cyan/10 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-cyan/80">Рекомендация</p>
            <p className="mt-2 text-sm leading-6 text-foreground">{result.model_hint}</p>
          </div>

          <div className="flex gap-3">
            <Button
              variant="outline"
              onClick={() => copyText(result.prompt_en, 'Prompt EN')}
              className="flex-1 border-border/50 bg-background/40 hover:bg-background/60"
            >
              <Copy className="mr-2 h-4 w-4" />
              Скопировать
            </Button>
            <Button onClick={onOpenPhoto} className="flex-1 bg-gold text-primary-foreground hover:bg-gold/90">
              Открыть фото
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function PromptResultCard({
  title,
  text,
  onCopy,
}: {
  title: string
  text: string
  onCopy: () => void
}) {
  return (
    <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs uppercase tracking-[0.16em] text-gold/80">{title}</p>
        <button
          type="button"
          onClick={onCopy}
          className="rounded-full border border-border/50 bg-background/40 px-3 py-1.5 text-xs text-foreground transition-colors hover:bg-background/70"
        >
          Копировать
        </button>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-foreground">{text}</p>
    </div>
  )
}


function PartnersPanel() {
  const [isLoading, setIsLoading] = useState(false)
  const [partner, setPartner] = useState<{
    is_partner: boolean
    referrals_count: number
    balance_rub: number
    referral_link: string
    status: string
  } | null>(null)

  async function loadPartnerData() {
    setIsLoading(true)
    try {
      const data = await fetchPartnerOverview()
      setPartner(data)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось загрузить партнёрку'
      toast.error('Партнёрская программа недоступна', { description: message })
    } finally {
      setIsLoading(false)
    }
  }

  useMemo(() => {
    if (!partner && !isLoading) {
      loadPartnerData()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const referralLink = partner?.referral_link || ''

  return (
    <div className="space-y-4">
      <div className="rounded-[1.75rem] border border-gold/20 bg-gradient-to-br from-gold/[0.12] via-card/70 to-cyan/[0.08] p-5">
        <p className="text-[11px] uppercase tracking-[0.18em] text-gold">
          Partner program
        </p>
        <h3 className="mt-2 font-serif text-2xl text-foreground">
          Партнёрская программа
        </h3>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Реальная статистика из backend-партнёрки: статус, приглашённые пользователи,
          баланс и ваша реферальная ссылка.
        </p>
      </div>

      {isLoading && (
        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin text-gold" />
            Загружаю данные партнёрки…
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
          <p className="text-xs text-muted-foreground">Статус</p>
          <p className="mt-2 font-serif text-xl text-foreground">
            {partner?.status === 'partner' ? 'Партнёр' : 'Базовый'}
          </p>
        </div>

        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
          <p className="text-xs text-muted-foreground">Рефералов</p>
          <p className="mt-2 font-serif text-xl text-foreground">
            {partner?.referrals_count ?? '—'}
          </p>
        </div>

        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
          <p className="text-xs text-muted-foreground">Баланс</p>
          <p className="mt-2 font-serif text-xl text-foreground">
            {partner ? `${partner.balance_rub} ₽` : '—'}
          </p>
        </div>
      </div>

      <div className="rounded-2xl border border-gold/20 bg-gold/10 p-4">
        <p className="text-xs uppercase tracking-[0.16em] text-gold/80">
          Реферальная ссылка
        </p>

        <div className="mt-3 rounded-2xl border border-border/50 bg-background/45 p-3">
          <p className="break-all text-sm leading-6 text-foreground">
            {referralLink || 'Ссылка пока недоступна'}
          </p>
        </div>

        <div className="mt-4 flex gap-3">
          <Button
            disabled={!referralLink}
            onClick={() => {
              navigator.clipboard.writeText(referralLink)
              toast.success('Реферальная ссылка скопирована')
            }}
            className="flex-1 bg-gold text-primary-foreground hover:bg-gold/90 disabled:opacity-50"
          >
            <Copy className="mr-2 h-4 w-4" />
            Скопировать
          </Button>

          <Button
            variant="outline"
            onClick={loadPartnerData}
            disabled={isLoading}
            className="border-border/50 bg-background/40 hover:bg-background/60"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Обновить'}
          </Button>
        </div>
      </div>
    </div>
  )
}

function SupportPanel() {
  const tips = [
    'Проверьте, хватает ли баланса для выбранной модели и длительности.',
    'Если задача долго выполняется, откройте её детали и обновите статус.',
    'Для редактирования и анимации обязательно добавьте исходный файл.',
  ]

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
        <p className="text-xs text-muted-foreground">Перед обращением</p>
        <div className="mt-3 space-y-2">
          {tips.map((tip) => (
            <div key={tip} className="rounded-xl border border-border/40 bg-background/30 px-3 py-3 text-sm text-foreground">
              {tip}
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-2xl border border-cyan/20 bg-cyan/10 p-4">
        <p className="text-xs text-muted-foreground">Сообщение в поддержку</p>
        <p className="mt-2 text-sm leading-6 text-foreground">
          Здравствуйте. Нужна помощь по задаче. Укажу номер задачи, выбранную модель и коротко опишу, что ожидал получить.
        </p>
        <Button
          onClick={() => toast.success('Текст скопирован')}
          className="mt-4 bg-cyan text-background hover:bg-cyan/90"
        >
          Скопировать текст
        </Button>
      </div>
    </div>
  )
}

function BatchEditPanel() {
  const presets = ['Удалить фон', 'Сделать единый стиль', 'Подготовить для карточек товара', 'Собрать набор превью']
  const [selectedPreset, setSelectedPreset] = useState(presets[0])

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
        <p className="text-xs text-muted-foreground">Выберите задачу</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {presets.map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={() => setSelectedPreset(preset)}
              className={cn(
                'rounded-full border px-3 py-2 text-xs',
                selectedPreset === preset
                  ? 'border-gold/40 bg-gold/10 text-foreground'
                  : 'border-border/50 bg-background/30 text-muted-foreground'
              )}
            >
              {preset}
            </button>
          ))}
        </div>
      </div>
      <div className="rounded-2xl border border-gold/20 bg-gold/10 p-4">
        <p className="text-xs text-muted-foreground">Следующий шаг</p>
        <p className="mt-2 text-sm text-foreground">
          Выбрано: {selectedPreset}. Дальше можно загрузить серию изображений и применить к ним один аккуратный сценарий.
        </p>
        <Button onClick={() => toast.success('Серия подготовлена')} className="mt-4 bg-gold text-primary-foreground hover:bg-gold/90">
          Подготовить серию
        </Button>
      </div>
    </div>
  )
}

function MorePanel({
  onPhoto,
  onVideo,
  onAssistant,
  onPartners,
  onSupport,
}: {
  onPhoto: () => void
  onVideo: () => void
  onAssistant: () => void
  onPartners: () => void
  onSupport: () => void
}) {
  const actions = [
    { label: 'Фото', description: 'Перейти к генерации изображений', action: onPhoto },
    { label: 'Видео', description: 'Перейти к генерации роликов', action: onVideo },
    { label: 'AI-помощник', description: 'Быстро уточнить идею и модель', action: onAssistant },
    { label: 'Партнёрам', description: 'Посмотреть выгоду и материалы', action: onPartners },
    { label: 'Поддержка', description: 'Собрать обращение и не забыть детали', action: onSupport },
  ]

  return (
    <div className="grid gap-3 md:grid-cols-2">
      {actions.map((item) => (
        <button
          key={item.label}
          type="button"
          onClick={item.action}
          className="rounded-2xl border border-border/50 bg-secondary/20 p-4 text-left transition-colors hover:bg-secondary/40"
        >
          <p className="font-medium text-foreground">{item.label}</p>
          <p className="mt-1 text-sm text-muted-foreground">{item.description}</p>
        </button>
      ))}
    </div>
  )
}

function InputCard({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-3 w-full rounded-2xl border border-border/50 bg-background/50 px-4 py-3 text-sm text-foreground outline-none"
      />
    </div>
  )
}
