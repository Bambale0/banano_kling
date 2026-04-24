'use client'

import { useMemo, useState } from 'react'
import { Bot, BriefcaseBusiness, Copy, Headphones, ImagePlus, Layers, Loader2, PanelTopOpen, Send, Sparkles, Wand2 } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'
import { askAIAssistant } from '@/lib/api'
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
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [subject, setSubject] = useState('Премиальный портрет')
  const [mood, setMood] = useState('кинематографично и дорого')
  const [focus, setFocus] = useState('свет, лицо, фактура ткани')

  const generatedPrompt = `Используй изображение как основной референс. Сохрани ${subject.toLowerCase()}, сделай акцент на ${focus}, подай сцену так, чтобы она выглядела ${mood}, с чистым светом, сильной композицией и аккуратной цветокоррекцией.`

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
        <label className="flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-border/60 bg-background/40 px-4 py-8 text-center">
          <ImagePlus className="mb-3 h-8 w-8 text-gold" />
          <span className="text-sm font-medium text-foreground">Загрузить референс</span>
          <span className="mt-1 text-xs text-muted-foreground">Фото останется здесь и поможет собрать более точное описание.</span>
          <input
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (!file) return
              setPreviewUrl(URL.createObjectURL(file))
            }}
          />
        </label>
        {previewUrl && (
          <div className="mt-4 overflow-hidden rounded-2xl border border-border/50">
            <img src={previewUrl} alt="Референс" className="h-56 w-full object-cover" />
          </div>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <InputCard label="Что важно сохранить" value={subject} onChange={setSubject} />
        <InputCard label="Какой нужен результат" value={mood} onChange={setMood} />
      </div>

      <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
        <p className="text-xs text-muted-foreground">Главные акценты</p>
        <textarea
          value={focus}
          onChange={(event) => setFocus(event.target.value)}
          rows={4}
          className="mt-3 w-full rounded-2xl border border-border/50 bg-background/50 px-4 py-3 text-sm text-foreground outline-none"
        />
      </div>

      <div className="rounded-2xl border border-gold/20 bg-gold/10 p-4">
        <p className="text-xs text-muted-foreground">Готовое описание</p>
        <p className="mt-2 text-sm leading-6 text-foreground">{generatedPrompt}</p>
        <div className="mt-4 flex gap-3">
          <Button
            onClick={() => {
              navigator.clipboard.writeText(generatedPrompt)
              toast.success('Описание скопировано')
            }}
            variant="outline"
            className="border-border/50 bg-background/40 hover:bg-background/60"
          >
            <Copy className="mr-2 h-4 w-4" />
            Копировать
          </Button>
          <Button onClick={onOpenPhoto} className="bg-gold text-primary-foreground hover:bg-gold/90">
            Перейти к фото
          </Button>
        </div>
      </div>
    </div>
  )
}

function PartnersPanel() {
  const cards = [
    { label: 'Вознаграждение', value: '20%', note: 'с оплат приглашённых пользователей' },
    { label: 'Минимальный вывод', value: '2 000 ₽', note: 'после накопления можно оформить заявку' },
    { label: 'Готовые материалы', value: 'Да', note: 'тексты, баннеры и короткие объяснения уже подготовлены' },
  ]

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        {cards.map((card) => (
          <div key={card.label} className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
            <p className="text-xs text-muted-foreground">{card.label}</p>
            <p className="mt-2 font-serif text-2xl text-foreground">{card.value}</p>
            <p className="mt-2 text-sm text-muted-foreground">{card.note}</p>
          </div>
        ))}
      </div>

      <div className="rounded-2xl border border-gold/20 bg-gold/10 p-4">
        <p className="text-xs text-muted-foreground">Как начать</p>
        <p className="mt-2 text-sm leading-6 text-foreground">
          Получаете ссылку, приглашаете авторов и отслеживаете результат в одном месте. Ничего не нужно искать по разным разделам.
        </p>
        <div className="mt-4 flex gap-3">
          <Button
            onClick={() => toast.success('Ссылка готова', { description: 'Можно скопировать её и отправить партнёрам.' })}
            className="bg-gold text-primary-foreground hover:bg-gold/90"
          >
            Получить ссылку
          </Button>
          <Button
            variant="outline"
            onClick={() => toast.success('Материалы открыты')}
            className="border-border/50 bg-background/40 hover:bg-background/60"
          >
            Материалы
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
