import {
  Activity,
  Atom,
  ArrowUp,
  BadgePercent,
  BarChart3,
  Bot,
  BrainCircuit,
  Boxes,
  Camera,
  Clapperboard,
  CreditCard,
  ExternalLink,
  FileText,
  AudioWaveform,
  Mic,
  History,
  Image,
  ImagePlus,
  Languages,
  Layers,
  Megaphone,
  MessageCircle,
  Orbit,
  PanelsTopLeft,
  Play,
  RefreshCw,
  Repeat,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Upload,
  Wand2,
  WandSparkles,
  Users,
  Wallet,
  ScanText,
  Video,
  X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { normalizeLang, translate, type Lang } from './i18n'

type AdminTab =
  | 'dashboard'
  | 'users'
  | 'payments'
  | 'subscriptions'
  | 'generations'
  | 'feed'
  | 'packages'
  | 'promos'
  | 'partners'
  | 'automation'
  | 'system'

type UserTab = 'home' | 'create' | 'history' | 'feed' | 'gpt55' | 'billing' | 'partner' | 'settings'
type Mode = 'studio' | 'admin'
type CreateDraft = {
  flow: string
  prompt?: string
  model?: string
  aspect_ratio?: string
  duration?: string
  count?: string
}

type AppState = {
  user: Record<string, unknown>
  is_admin: boolean
  stats: Record<string, unknown>
  settings: Record<string, unknown>
  packages: Record<string, unknown>[]
  payments: Record<string, unknown>[]
  tasks: Record<string, unknown>[]
  feed: Record<string, unknown>[]
  partner: Record<string, unknown>
  withdrawals: Record<string, unknown>[]
  recurring: Record<string, unknown> | null
  gpt55_history: Record<string, unknown>[]
  features: Record<string, unknown>
  support: Record<string, unknown>
}

type ApiState = {
  admin: Record<string, unknown>
  dashboard: Record<string, number | string | boolean>
  limits: Record<string, unknown>
  users: Record<string, unknown>[]
  payments: Record<string, unknown>[]
  subscriptions: Record<string, unknown>[]
  recurring: Record<string, unknown>[]
  generations: Record<string, unknown>[]
  feed: Record<string, unknown>[]
  packages: Record<string, unknown>[]
  promos: Record<string, unknown>[]
  partners: Record<string, unknown>[]
  withdrawals: Record<string, unknown>[]
  referrals: { config: Record<string, unknown>; payouts: Record<string, unknown>[] }
  push: { config: Record<string, unknown>; due_events: Record<string, unknown>[] }
  system: Record<string, unknown>
}

type Mutate = (fn: () => Promise<unknown>, message?: string) => Promise<void>

const userTabs: Array<[UserTab, typeof BarChart3, string]> = [
  ['home', BarChart3, 'home'],
  ['create', Wand2, 'create'],
  ['history', History, 'history'],
  ['feed', Image, 'feed'],
  ['gpt55', MessageCircle, 'chat'],
  ['settings', Settings, 'settings'],
]

const userTitle: Record<UserTab, string> = {
  home: 'home',
  create: 'create',
  history: 'history',
  feed: 'feedWorks',
  gpt55: 'ChatGPT',
  billing: 'billing',
  partner: 'partner',
  settings: 'settings',
}

const tabs: Array<[AdminTab, typeof BarChart3, string]> = [
  ['dashboard', BarChart3, 'dashboard'],
  ['users', Users, 'users'],
  ['payments', CreditCard, 'payments'],
  ['subscriptions', Repeat, 'subscriptions'],
  ['generations', Sparkles, 'generations'],
  ['feed', Image, 'feed'],
  ['packages', Boxes, 'packages'],
  ['promos', BadgePercent, 'promos'],
  ['partners', Wallet, 'partners'],
  ['automation', Megaphone, 'automation'],
  ['system', Settings, 'system'],
]

const adminCollections: Record<AdminTab, string[]> = {
  dashboard: ['payments', 'partners'],
  users: ['users'],
  payments: ['payments'],
  subscriptions: ['subscriptions', 'recurring'],
  generations: ['generations'],
  feed: ['feed'],
  packages: ['packages'],
  promos: ['promos'],
  partners: ['partners', 'referrals', 'withdrawals'],
  automation: ['push'],
  system: ['system'],
}

const createFlows: Array<{ id: string; label: string; accent: string; accent2: string }> = [
  { id: 'photo_to_prompt', label: 'photoToPrompt', accent: '#67ffce', accent2: '#ff6be8' },
  { id: 'prompt_builder', label: 'promptBuilder', accent: '#41f2ff', accent2: '#a177ff' },
  { id: 'image', label: 'createPhoto', accent: '#41f2ff', accent2: '#ff6be8' },
  { id: 'image_edit', label: 'editPhoto', accent: '#67ffce', accent2: '#41f2ff' },
  { id: 'multi_photo', label: 'multiPhoto', accent: '#67ffce', accent2: '#3ed8ff' },
  { id: 'video_text', label: 'createVideo', accent: '#c9ff5f', accent2: '#36e7ff' },
  { id: 'image_to_video', label: 'imageToVideo', accent: '#b7ff5f', accent2: '#41f2ff' },
  { id: 'video_edit', label: 'videoEffect', accent: '#a177ff', accent2: '#ff74dc' },
  { id: 'motion_control', label: 'motionControl', accent: '#ffb85c', accent2: '#ff63c8' },
  { id: 'gemini_omni', label: 'Gemini Omni', accent: '#ff74dc', accent2: '#7d86ff' },
  { id: 'upscale', label: 'upscale', accent: '#e9ff9a', accent2: '#41f2ff' },
]

const createSections: Array<{ id: string; label: string; flows: string[]; icon: string; accent: string; accent2: string }> = [
  { id: 'photo', label: 'photoSection', flows: ['image', 'image_edit', 'multi_photo', 'upscale'], icon: 'image', accent: '#41f2ff', accent2: '#ff6be8' },
  { id: 'video', label: 'videoSection', flows: ['video_text', 'image_to_video', 'video_edit', 'gemini_omni'], icon: 'video_text', accent: '#c9ff5f', accent2: '#36e7ff' },
  { id: 'motion', label: 'motionSection', flows: ['motion_control'], icon: 'motion_control', accent: '#ffb85c', accent2: '#ff63c8' },
  { id: 'tools', label: 'toolsSection', flows: ['photo_to_prompt', 'prompt_builder'], icon: 'prompt_builder', accent: '#67ffce', accent2: '#a177ff' },
]

const videoFlows = ['video_text', 'image_to_video', 'video_edit', 'motion_control', 'gemini_omni']
const utilityFlows = ['photo_to_prompt', 'prompt_builder']

type OptionItem = { id: string; label: string; hint?: string }

const imageModelOptions: OptionItem[] = [
  { id: 'banana_pro', label: 'Nano Banana Pro', hint: 'детально' },
  { id: 'banana_2', label: 'Nano Banana', hint: 'быстро' },
  { id: 'gpt_image_2', label: 'GPT Image', hint: 'текст и стиль' },
  { id: 'seedream_5_lite', label: 'Seedream', hint: 'легкая' },
]

const textVideoModelOptions: OptionItem[] = [
  { id: 'v3_std', label: 'Kling Standard', hint: 'оптимально' },
  { id: 'v3_pro', label: 'Kling Pro', hint: 'качество' },
  { id: 'runway', label: 'Runway', hint: 'кино' },
  { id: 'seedance2', label: 'Seedance 2', hint: 'динамика' },
]

const imageVideoModelOptions: OptionItem[] = [
  { id: 'v3_std', label: 'Kling I2V Standard', hint: 'оптимально' },
  { id: 'v3_pro', label: 'Kling I2V Pro', hint: 'качество' },
  { id: 'runway', label: 'Runway I2V', hint: 'кино' },
  { id: 'seedance2', label: 'Seedance 2', hint: 'динамика' },
]

const motionModelOptions: OptionItem[] = [
  { id: 'v3_std', label: 'Motion Standard', hint: 'быстро' },
  { id: 'v3_pro', label: 'Motion Pro', hint: 'плавнее' },
]

const remixPhotoModels = ['banana_2', 'grok_i2i', 'gpt_image_2']

const geminiOmniModelOptions: OptionItem[] = [
  { id: 'gemini_omni', label: 'Gemini Omni', hint: 'omni' },
]

const imageRatios: OptionItem[] = [
  { id: '1:1', label: 'Квадрат', hint: '1:1' },
  { id: '9:16', label: 'Stories', hint: '9:16' },
  { id: '16:9', label: 'Wide', hint: '16:9' },
  { id: '4:3', label: 'Классика', hint: '4:3' },
]

const videoRatios: OptionItem[] = [
  { id: '16:9', label: 'Wide', hint: '16:9' },
  { id: '9:16', label: 'Stories', hint: '9:16' },
  { id: '1:1', label: 'Квадрат', hint: '1:1' },
]

const durationOptions: OptionItem[] = [
  { id: '5', label: '5 сек' },
  { id: '10', label: '10 сек' },
  { id: '15', label: '15 сек' },
]

const tg = () => window.Telegram?.WebApp
const initData = () => tg()?.initData || ''
const hasInitData = () => Boolean(initData())
const wsUrl = (path: string) => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const params = new URLSearchParams({ initData: initData() })
  return `${protocol}//${window.location.host}${path}?${params.toString()}`
}
const fmtMoney = (value: unknown, lang: Lang = 'ru') => `${Number(value || 0).toLocaleString(lang === 'en' ? 'en-US' : 'ru-RU')} ₽`
const fmtNum = (value: unknown, lang: Lang = 'ru') => Number(value || 0).toLocaleString(lang === 'en' ? 'en-US' : 'ru-RU')
const boolText = (value: unknown, lang: Lang = 'ru') => (value ? translate(lang, 'on') : translate(lang, 'off'))
const cls = (...items: Array<string | false | undefined>) => items.filter(Boolean).join(' ')
const fieldLabels: Record<string, string> = {
  id: 'ID',
  telegram_id: 'Telegram ID',
  order_id: 'Номер заказа',
  amount_rub: 'Сумма',
  original_amount_rub: 'Сумма без скидки',
  status: 'Статус',
  provider: 'Платежная система',
  payment_id: 'ID платежа',
  promo_code: 'Промокод',
  promo_discount_percent: 'Скидка %',
  created_at: 'Создано',
  updated_at: 'Обновлено',
  task_id: 'Задача',
  type: 'Тип',
  model: 'Нейронка',
  preset_id: 'Режим',
  cost: 'Стоимость',
  package_id: 'Пакет',
  expires_at: 'Истекает',
  images_used: 'Фото использовано',
  videos_used: 'Видео использовано',
  next_charge_at: 'Следующее списание',
  last_order_id: 'Последний заказ',
  last_error: 'Последняя ошибка',
  users_count: 'Пользователи',
  payments_count: 'Оплаты',
  revenue_rub: 'Выручка',
  commission_rub: 'Комиссия',
  balance_rub: 'Баланс',
  partner: 'Партнер',
  comment: 'Комментарий',
  scenario_key: 'Сценарий',
  title: 'Название',
  due_at: 'К отправке',
  key: 'Параметр',
  value: 'Значение',
  name: 'Название',
  kind: 'Тип',
  period: 'Период',
  price_rub: 'Цена',
  credits: 'Бумкоины',
  bonus_credits: 'Бонус',
  subscription_days: 'Дней подписки',
  image_limit: 'Лимит фото',
  video_limit: 'Лимит видео',
  discount_percent: 'Скидка',
  popular: 'Популярный',
  hidden: 'Скрыт',
  includes_pro: 'PRO включен',
  priority: 'Приоритет',
  used_count: 'Использовано',
  max_uses: 'Лимит',
  is_active: 'Активен',
  referrer_bonus_credits: 'Бонус пригласившему',
  friend_bonus_credits: 'Бонус другу',
  bonus_trigger: 'Когда начислять',
  daily_referral_limit: 'Дневной лимит',
}
const valueLabels: Record<string, string> = {
  pending: 'ожидает',
  processing: 'в работе',
  completed: 'готово',
  failed: 'ошибка',
  cancelled: 'отменено',
  paid: 'выплачено',
  frozen: 'заморожено',
  active: 'активно',
  inactive: 'неактивно',
  enabled: 'включено',
  disabled: 'выключено',
  credits: 'Бумкоины',
  subscription: 'Подписка',
  discount: 'Скидка',
  bananas: 'Бумкоины',
  generation: 'Генерации',
  image: 'Фото',
  video: 'Видео',
  feed: 'Лента',
  basic: 'Базовый',
  signup: 'при регистрации',
  first_payment: 'после первой оплаты',
}
const packageFieldHelp: Record<string, string> = {
  id: 'Короткий код без пробелов: например video_pack. Нужен системе, пользователи его не видят.',
  name: 'Название, которое увидит пользователь при покупке.',
  kind: 'Бумкоины дают баланс. Подписка дает период и лимиты генераций.',
  period: 'Короткое описание срока: 24 часа, неделя, месяц.',
  price_rub: 'Цена пакета в рублях.',
  credits: 'Сколько Бумкоинов начислить после оплаты. Для лимитных подписок можно оставить 0.',
  bonus_credits: 'Дополнительные Бумкоины сверху. Если не нужно - 0.',
  subscription_days: 'На сколько дней включить подписку. Для пакета Бумкоинов можно поставить 0.',
  image_limit: 'Сколько фото можно сделать по подписке. 0 - не давать лимит фото.',
  video_limit: 'Сколько видео можно сделать по подписке. 0 - не давать лимит видео.',
  discount_percent: 'Визуальная скидка для карточки пакета. На оплату влияет цена выше.',
  popular: 'Подсветить пакет как популярный.',
  hidden: 'Скрыть пакет от пользователей, но оставить в админке.',
  includes_pro: 'Разрешить PRO-нейронки в рамках подписки.',
  priority: 'Повышенный приоритет для генераций по подписке.',
}
const packageFieldHelpText = (field: string) => packageFieldHelp[field] || ''
const fieldLabel = (field: string) => fieldLabels[field] || field
const statusKeys: Record<string, string> = {
  pending: 'statusPending',
  processing: 'statusProcessing',
  completed: 'statusCompleted',
  failed: 'statusFailed',
  cancelled: 'statusCancelled',
  active: 'statusActive',
  inactive: 'statusInactive',
}
const displayValue = (value: unknown, lang: Lang = 'ru') => {
  const raw = String(value ?? '-')
  if (statusKeys[raw]) return translate(lang, statusKeys[raw])
  return valueLabels[raw] || raw
}
const readableMessage = (value: unknown): string => {
  if (value == null) return ''
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
      try {
        return readableMessage(JSON.parse(trimmed))
      } catch {
        return trimmed
      }
    }
    return trimmed
  }
  if (Array.isArray(value)) {
    return value.map(readableMessage).filter(Boolean).join('\n')
  }
  if (typeof value === 'object') {
    const item = value as Record<string, unknown>
    return readableMessage(item.text ?? item.input_text ?? item.output_text ?? item.content ?? '')
  }
  return String(value)
}
const getInitialLang = (): Lang => {
  const saved = window.localStorage.getItem('boom_lang')
  if (saved) return normalizeLang(saved)
  return normalizeLang(tg()?.initDataUnsafe?.user?.language_code || navigator.language)
}
const errorMessage = (value: string) => {
  try {
    const parsed = JSON.parse(value) as { error?: unknown; message?: unknown }
    return String(parsed.error || parsed.message || value)
  } catch {
    return value
  }
}
const roleLabel = (role: unknown, lang: Lang) => (String(role) === 'assistant' ? translate(lang, 'assistantRole') : translate(lang, 'userRole'))
const authorName = (row: Record<string, unknown>) => {
  if (row.username) return `@${String(row.username)}`
  const fullName = [row.first_name, row.last_name].filter(Boolean).join(' ').trim()
  return fullName || String(row.author_code || 'creator')
}
const authorInitial = (row: Record<string, unknown>) => authorName(row).replace('@', '').trim().slice(0, 1).toUpperCase() || 'U'
const authorHue = (row: Record<string, unknown>) => {
  const seed = String(row.author_code || row.username || row.task_id || '0')
  return Array.from(seed).reduce((sum, char) => sum + char.charCodeAt(0), 0) % 360
}

async function api<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(initData() ? { 'X-Telegram-Init-Data': initData() } : {}),
      ...(options.headers || {}),
    },
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(errorMessage(text) || `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

const postAction = <T,>(url: string, body: Record<string, unknown> = {}) => {
  tg()?.HapticFeedback?.impactOccurred('medium')
  return api<T>(url, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

async function streamGpt55(
  message: string,
  onDelta: (delta: string) => void,
): Promise<Record<string, unknown> | null> {
  const response = await fetch('/api/tma/app/gpt55/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(initData() ? { 'X-Telegram-Init-Data': initData() } : {}),
    },
    body: JSON.stringify({ message }),
  })
  if (!response.ok || !response.body) {
    throw new Error(errorMessage(await response.text()) || `HTTP ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let donePayload: Record<string, unknown> | null = null

  const processEvent = (raw: string) => {
    const lines = raw.split('\n').map((line) => line.trim()).filter(Boolean)
    let eventName = 'message'
    const dataLines: string[] = []
    for (const line of lines) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim()
      if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    if (!dataLines.length) return
    const payload = JSON.parse(dataLines.join('\n')) as Record<string, unknown>
    if (eventName === 'delta') onDelta(String(payload.delta || ''))
    if (eventName === 'done') donePayload = payload
    if (eventName === 'error') throw new Error(String(payload.error || 'gpt_unavailable'))
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let index = buffer.indexOf('\n\n')
    while (index >= 0) {
      processEvent(buffer.slice(0, index))
      buffer = buffer.slice(index + 2)
      index = buffer.indexOf('\n\n')
    }
  }
  if (buffer.trim()) processEvent(buffer)
  return donePayload
}

async function uploadReference(file: File): Promise<string> {
  const body = new FormData()
  body.append('file', file)
  const response = await fetch('/api/tma/app/upload', {
    method: 'POST',
    headers: {
      ...(initData() ? { 'X-Telegram-Init-Data': initData() } : {}),
    },
    body,
  })
  if (!response.ok) {
    throw new Error(errorMessage(await response.text()) || `HTTP ${response.status}`)
  }
  const result = (await response.json()) as { ok: boolean; url?: string; error?: string }
  if (!result.ok || !result.url) {
    throw new Error(result.error || 'upload_failed')
  }
  return result.url
}

async function analyzePhotoToPrompt(file: File): Promise<string> {
  const body = new FormData()
  body.append('file', file)
  const response = await fetch('/api/tma/app/photo-to-prompt', {
    method: 'POST',
    headers: {
      ...(initData() ? { 'X-Telegram-Init-Data': initData() } : {}),
    },
    body,
  })
  if (!response.ok) {
    throw new Error(errorMessage(await response.text()) || `HTTP ${response.status}`)
  }
  const result = (await response.json()) as { ok: boolean; prompt?: string; error?: string }
  if (!result.ok || !result.prompt) {
    throw new Error(result.error || 'analysis_failed')
  }
  return result.prompt
}

export default function App() {
  const [mode, setMode] = useState<Mode>('studio')
  const [tab, setTab] = useState<UserTab>('home')
  const [adminTab, setAdminTab] = useState<AdminTab>('dashboard')
  const [initialFlow, setInitialFlow] = useState('')
  const [initialDraft, setInitialDraft] = useState<CreateDraft | null>(null)
  const [appData, setAppData] = useState<AppState | null>(null)
  const [data, setData] = useState<ApiState | null>(null)
  const [loading, setLoading] = useState(true)
  const [adminLoading, setAdminLoading] = useState(false)
  const [sectionLoading, setSectionLoading] = useState('')
  const [error, setError] = useState('')
  const [adminError, setAdminError] = useState('')
  const [toast, setToast] = useState('')
  const [lang, setLang] = useState<Lang>(getInitialLang)
  const t = (key: string) => translate(lang, key)

  const switchLang = () => {
    const next = lang === 'ru' ? 'en' : 'ru'
    setLang(next)
    window.localStorage.setItem('boom_lang', next)
  }

  const loadApp = async () => {
    setLoading(true)
    setError('')
    try {
      if (!hasInitData()) {
        throw new Error(t('openViaTelegram'))
      }
      const result = await api<{ ok: boolean; data: AppState }>('/api/tma/app/bootstrap')
      setAppData(result.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('appLoadFailed'))
    } finally {
      setLoading(false)
    }
  }

  const loadAdmin = async () => {
    setAdminLoading(true)
    setAdminError('')
    try {
      const result = await api<{ ok: boolean; data: ApiState }>('/api/tma/admin/bootstrap')
      setData(result.data)
    } catch (err) {
      setData(null)
      const message = err instanceof Error ? err.message : 'Админка недоступна'
      setAdminError(message)
      setToast(message)
    } finally {
      setAdminLoading(false)
    }
  }

  const loadAdminSection = async (tabName: AdminTab = adminTab, force = false) => {
    if (!data) return
    const collections = adminCollections[tabName] || []
    const pending = collections.filter((name) => {
      if (force) return true
      const value = data[name as keyof ApiState] as unknown
      if (Array.isArray(value)) return value.length === 0
      if (value && typeof value === 'object') return Object.keys(value as Record<string, unknown>).length === 0
      return !value
    })
    if (!pending.length) return
    setSectionLoading(tabName)
    try {
      const patches = await Promise.all(
        pending.map((name) =>
          api<Record<string, unknown>>(`/api/tma/admin/${name}?limit=120`),
        ),
      )
      setData((current) =>
        current
          ? Object.assign({}, current, ...patches.map(({ ok: _ok, ...patch }) => patch))
          : current,
      )
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Раздел не загрузился'
      setToast(message)
    } finally {
      setSectionLoading('')
    }
  }

  const mutateApp = async (fn: () => Promise<unknown>, message = t('done')) => {
    try {
      await fn()
      setToast(message)
      await loadApp()
    } catch (err) {
      setToast(err instanceof Error ? err.message : t('actionError'))
    } finally {
      window.setTimeout(() => setToast(''), 3200)
    }
  }

  const mutate = async (fn: () => Promise<unknown>, message = t('done')) => {
    try {
      await fn()
      setToast(message)
      await loadAdminSection(adminTab, true)
    } catch (err) {
      setToast(err instanceof Error ? err.message : t('actionError'))
    } finally {
      window.setTimeout(() => setToast(''), 3200)
    }
  }

  useEffect(() => {
    tg()?.ready()
    tg()?.expand()
    loadApp()
  }, [])

  useEffect(() => {
    if (mode === 'admin' && appData?.is_admin && !data) {
      loadAdmin()
    }
  }, [mode, appData?.is_admin])

  useEffect(() => {
    if (mode === 'admin' && data) {
      loadAdminSection(adminTab)
    }
  }, [mode, adminTab, Boolean(data)])

  useEffect(() => {
    if (!hasInitData() || !appData) return
    const socket = new WebSocket(wsUrl('/api/tma/app/ws'))
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { type?: string; task?: Record<string, unknown> }
        if (payload.type !== 'task_update' || !payload.task?.task_id) return
        const taskUpdate = payload.task
        setAppData((current) => {
          if (!current) return current
          const taskId = String(taskUpdate.task_id)
          const exists = current.tasks.some((task) => String(task.task_id) === taskId)
          const tasks = exists
            ? current.tasks.map((task) => (String(task.task_id) === taskId ? { ...task, ...taskUpdate } : task))
            : [taskUpdate, ...current.tasks]
          return { ...current, tasks }
        })
        if (taskUpdate.status === 'completed') setToast(t('taskReady'))
        if (taskUpdate.status === 'failed') setToast(t('statusFailed'))
        window.setTimeout(() => setToast(''), 3200)
      } catch {
        // Ignore malformed websocket events.
      }
    }
    return () => socket.close()
  }, [Boolean(appData), lang])

  const nav = mode === 'admin' ? tabs : userTabs
  const title = mode === 'admin' ? t(tabs.find(([id]) => id === adminTab)?.[2] || '') : t(userTitle[tab])
  const isHome = mode === 'studio' && tab === 'home'

  return (
    <div className={cls('app', isHome && 'home-app')}>
      <aside className="rail">
        <div className="brand">
            <Bot size={24} />
	            <div>
	              <strong>BooM Studio</strong>
	              <span>{mode === 'admin' ? t('controlCenter') : t('miniApp')}</span>
	            </div>
          </div>
        <nav>
          {nav.map(([id, Icon, label]) => (
            <button
	              key={id}
	              className={(mode === 'admin' ? adminTab === id : tab === id) ? 'active' : ''}
	              onClick={() => {
	                if (mode === 'admin') {
	                  setAdminTab(id as AdminTab)
	                } else {
	                  if (id === 'create') {
                      setInitialFlow('')
                      setInitialDraft(null)
                    }
	                  setTab(id as UserTab)
	                }
	              }}
            >
              <Icon size={17} />
	              <span>{t(label)}</span>
            </button>
          ))}
        </nav>
      </aside>

      <main className="workspace">
        <header className="top">
          <div>
            <p>BOOM Studio</p>
            <h1>{title}</h1>
          </div>
          <div className="top-actions">
            {mode === 'studio' && appData ? (
              <span className="balance-pill">
	                {fmtNum(appData.stats.credits, lang)} <b>{t('boomcoins')}</b>
	              </span>
            ) : null}
            {appData?.is_admin ? (
              <button onClick={() => setMode(mode === 'admin' ? 'studio' : 'admin')}>
	                <ShieldCheck size={16} /> {mode === 'admin' ? t('studio') : t('admin')}
	              </button>
	            ) : null}
	            <button onClick={switchLang}><Languages size={16} /> {lang === 'ru' ? 'EN' : 'RU'}</button>
	            <button onClick={() => (mode === 'admin' ? loadAdminSection(adminTab, true) : loadApp())}>
	              <RefreshCw size={16} /> {t('refresh')}
	            </button>
          </div>
        </header>

        {loading && <StateCard title={t('loadingData')} text={t('loadingDataText')} />}
        {!loading && error && <StateCard title={t('accessClosed')} text={error} danger />}
        {!loading && mode === 'studio' && appData && (
          <>
            {tab === 'home' && <StudioHome data={appData} lang={lang} setTab={setTab} openCreateFlow={(flow) => { setInitialDraft(null); setInitialFlow(flow); setTab('create') }} />}
            {tab === 'create' && <CreatePage data={appData} lang={lang} mutate={mutateApp} initialFlow={initialFlow} initialDraft={initialDraft} />}
            {tab === 'history' && <HistoryPage data={appData} lang={lang} mutate={mutateApp} />}
            {tab === 'feed' && <UserFeedPage data={appData} lang={lang} mutate={mutateApp} openRepeat={(draft) => { setInitialDraft(draft); setInitialFlow(draft.flow); setTab('create') }} />}
            {tab === 'gpt55' && <GPTPage data={appData} lang={lang} mutate={mutateApp} />}
            {tab === 'billing' && <BillingPage data={appData} lang={lang} mutate={mutateApp} />}
            {tab === 'partner' && <PartnerUserPage data={appData} lang={lang} mutate={mutateApp} />}
            {tab === 'settings' && <SettingsUserPage data={appData} lang={lang} setTab={setTab} setMode={setMode} />}
          </>
        )}
        {!loading && mode === 'admin' && adminLoading && <StateCard title="Загружаю админку" text="Подтягиваю рабочие данные." />}
        {!loading && mode === 'admin' && !adminLoading && adminError && !data && (
          <section className="state-card danger">
            <ShieldCheck size={26} />
            <h2>Админка недоступна</h2>
            <p>{adminError}</p>
            <div className="inline-actions">
              <button onClick={loadAdmin}><RefreshCw size={16} /> Повторить</button>
              <button onClick={() => setMode('studio')}>В студию</button>
            </div>
          </section>
        )}
        {!loading && mode === 'admin' && data && (
          <>
            {sectionLoading === adminTab && <StateCard title="Загружаю раздел" text="Подтягиваю данные этого экрана." />}
            {adminTab === 'dashboard' && <Dashboard data={data} mutate={mutate} setTab={setAdminTab} />}
            {adminTab === 'users' && <UsersPage data={data} mutate={mutate} />}
            {adminTab === 'payments' && <PaymentsPage rows={data.payments} mutate={mutate} />}
            {adminTab === 'subscriptions' && <SubscriptionsPage data={data} mutate={mutate} />}
            {adminTab === 'generations' && <GenerationsPage rows={data.generations} mutate={mutate} />}
            {adminTab === 'feed' && <FeedPage rows={data.feed} mutate={mutate} />}
            {adminTab === 'packages' && <PackagesPage rows={data.packages} mutate={mutate} />}
            {adminTab === 'promos' && <PromosPage data={data} mutate={mutate} />}
            {adminTab === 'partners' && <PartnersPage data={data} mutate={mutate} />}
            {adminTab === 'automation' && <AutomationPage data={data} mutate={mutate} />}
            {adminTab === 'system' && <SystemPage data={data} mutate={mutate} />}
          </>
        )}
      </main>
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}

function StateCard({ title, text, danger }: { title: string; text: string; danger?: boolean }) {
  return (
    <section className={cls('state-card', danger && 'danger')}>
      <ShieldCheck size={26} />
      <h2>{title}</h2>
      <p>{text}</p>
    </section>
  )
}

function FeedAuthor({ row }: { row: Record<string, unknown> }) {
  const hue = authorHue(row)
  return (
    <div className="feed-author">
      <span
        className="feed-avatar"
        style={{ background: `linear-gradient(135deg, hsl(${hue} 85% 58%), hsl(${(hue + 58) % 360} 92% 66%))` }}
      >
        {authorInitial(row)}
      </span>
      <strong>{authorName(row)}</strong>
      <small>{String(row.type || 'Фото')}</small>
    </div>
  )
}

function isVideoUrl(url: string) {
  return /\.(mp4|webm|mov|m4v)(\?|#|$)/i.test(url)
}

function FeedPreview({ url, variant = 'default', onOpen }: { url: unknown; variant?: 'default' | 'pin'; onOpen?: () => void }) {
  const [loaded, setLoaded] = useState(false)
  const src = String(url || '')
  if (!src) return null
  if (isVideoUrl(src)) {
    return (
      <button type="button" className={cls('feed-media', variant === 'pin' && 'pin-media', onOpen && 'openable', !loaded && 'loading')} onClick={onOpen}>
        <video
          src={src}
          muted
          playsInline
          preload="metadata"
          onLoadedData={() => setLoaded(true)}
        />
      </button>
    )
  }
  return (
    <button type="button" className={cls('feed-media', variant === 'pin' && 'pin-media', onOpen && 'openable', !loaded && 'loading')} onClick={onOpen}>
      <img
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        onLoad={() => setLoaded(true)}
      />
    </button>
  )
}

function FeedLightbox({ row, lang, onClose, onRepeat }: { row: Record<string, unknown>; lang: Lang; onClose: () => void; onRepeat: () => void }) {
  const t = (key: string) => translate(lang, key)
  const src = String(row.result_url || '')
  if (!src) return null
  return (
    <div className="lightbox" role="dialog" aria-modal="true">
      <button className="lightbox-backdrop" type="button" onClick={onClose} aria-label="close" />
      <div className="lightbox-view">
        <div className="lightbox-actions">
          <a href={src} target="_blank" rel="noreferrer"><ExternalLink size={18} /> {t('open')}</a>
          <button type="button" onClick={onRepeat}><RefreshCw size={18} /> {t('repeat')}</button>
          <button className="icon-only" type="button" onClick={onClose} aria-label="close"><X size={20} /></button>
        </div>
        {isVideoUrl(src) ? (
          <video src={src} controls autoPlay playsInline />
        ) : (
          <img src={src} alt="" />
        )}
      </div>
    </div>
  )
}

function FlowGlyph({ id }: { id: string }) {
  if (id === 'photo_to_prompt') {
    return <span className="flow-glyph"><ScanText className="glyph-single" strokeWidth={1.75} /></span>
  }
  if (id === 'prompt_builder') {
    return <span className="flow-glyph"><WandSparkles className="glyph-single" strokeWidth={1.75} /></span>
  }
  if (id === 'image') return <span className="flow-glyph"><ImagePlus className="glyph-single" strokeWidth={1.75} /></span>
  if (id === 'image_edit') return <span className="flow-glyph"><Wand2 className="glyph-single" strokeWidth={1.75} /></span>
  if (id === 'multi_photo') return <span className="flow-glyph"><PanelsTopLeft className="glyph-single" strokeWidth={1.75} /></span>
  if (id === 'video_text') return <span className="flow-glyph"><Video className="glyph-single" strokeWidth={1.75} /></span>
  if (id === 'image_to_video') return <span className="flow-glyph"><Play className="glyph-single" strokeWidth={1.75} /></span>
  if (id === 'video_edit') return <span className="flow-glyph"><Clapperboard className="glyph-single" strokeWidth={1.75} /></span>
  if (id === 'motion_control') return <span className="flow-glyph"><AudioWaveform className="glyph-single" strokeWidth={1.75} /></span>
  if (id === 'gemini_omni') {
    return <span className="flow-glyph"><Orbit className="glyph-single" strokeWidth={1.7} /></span>
  }
  return <span className="flow-glyph"><Sparkles className="glyph-single" strokeWidth={1.75} /></span>
}

function StudioHome({ data, lang, setTab, openCreateFlow }: { data: AppState; lang: Lang; setTab: (tab: UserTab) => void; openCreateFlow: (flow: string) => void }) {
  const t = (key: string) => translate(lang, key)
  const topFlows = createFlows.filter((item) => ['photo_to_prompt', 'prompt_builder'].includes(item.id))
  const mainFlows = createFlows.filter((item) => ['image', 'multi_photo', 'video_text', 'motion_control', 'gemini_omni'].includes(item.id))
  const homeLabel = (_id: string, label: string) => label
  return (
    <section className="studio-home" aria-label={t('home')}>
      <div className="home-shortcuts" aria-label={t('promptBuilder')}>
        {topFlows.map(({ id, label, accent, accent2 }) => (
          <button
            key={id}
            type="button"
            className="flow-card home-card home-card-small"
            style={{ '--accent': accent, '--accent-2': accent2 } as CSSProperties}
            onClick={() => openCreateFlow(id)}
          >
            <span className="flow-icon" style={{ color: accent }} aria-hidden="true"><FlowGlyph id={id} /></span>
            <strong>{homeLabel(id, t(label))}</strong>
          </button>
        ))}
      </div>

      <h2 className="home-section-title">{t('generation')}</h2>

      <div className="home-main-grid" aria-label={t('generation')}>
        {mainFlows.map(({ id, label, accent, accent2 }) => (
            <button
              key={id}
              type="button"
              className={cls('flow-card home-card', id === 'motion_control' && 'home-card-wide')}
              style={{ '--accent': accent, '--accent-2': accent2 } as CSSProperties}
              onClick={() => openCreateFlow(id)}
            >
              <span className="flow-icon" style={{ color: accent }} aria-hidden="true"><FlowGlyph id={id} /></span>
              <strong>{homeLabel(id, t(label))}</strong>
            </button>
        ))}
      </div>

      <button className="home-profile-link" onClick={() => setTab('settings')}>
        {String(data.user.username ? `@${data.user.username}` : data.stats.telegram_id)}
      </button>
    </section>
  )
}

function modelOptionsForFlow(flow: string) {
  if (flow === 'gemini_omni') return geminiOmniModelOptions
  if (flow === 'motion_control') return motionModelOptions
  if (flow === 'image_to_video' || flow === 'video_edit') return imageVideoModelOptions
  if (videoFlows.includes(flow)) return textVideoModelOptions
  return imageModelOptions
}

function defaultModelForFlow(flow: string, data: AppState) {
  const options = modelOptionsForFlow(flow)
  const saved = flow === 'image_to_video' || flow === 'video_edit'
    ? String(data.settings.preferred_i2v_model || data.settings.preferred_video_model || '')
    : videoFlows.includes(flow)
      ? String(data.settings.preferred_video_model || '')
      : String(data.settings.image_service || '')
  return options.some((item) => item.id === saved) ? saved : options[0].id
}

function normalizeModelForFlow(flow: string, model: string, data: AppState) {
  const options = modelOptionsForFlow(flow)
  return options.some((item) => item.id === model) ? model : defaultModelForFlow(flow, data)
}

function flowNeedsReferences(flow: string) {
  return ['image_edit', 'multi_photo', 'image_to_video', 'video_edit', 'motion_control', 'gemini_omni', 'upscale'].includes(flow)
}

function modelSupportsReferences(config: Record<string, unknown>) {
  return Boolean(config.supports_refs || config.requires_refs)
}

function flowNeedsPrompt(flow: string) {
  return !utilityFlows.includes(flow)
}

function ChoiceGroup({ label, options, value, onChange }: { label: string; options: OptionItem[]; value: string; onChange: (value: string) => void }) {
  const compactCount = options.length <= 4 ? Math.max(options.length, 1) : 0
  return (
    <div className="choice-group">
      <span>{label}</span>
      <div
        className={cls('choice-list', compactCount > 0 && 'compact', options.length === 2 && 'binary')}
        style={compactCount ? { '--choice-count': compactCount } as CSSProperties : undefined}
      >
        {options.map((option) => (
          <button
            key={option.id}
            type="button"
            className={cls('choice-chip', value === option.id && 'active')}
            onClick={() => onChange(option.id)}
          >
            <strong>{option.label}</strong>
            {option.hint ? <small>{option.hint}</small> : null}
          </button>
        ))}
      </div>
    </div>
  )
}

function ModelSelect({ label, options, value, onChange }: { label: string; options: OptionItem[]; value: string; onChange: (value: string) => void }) {
  const selected = options.find((option) => option.id === value)
  return (
    <label className="model-select">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}{option.hint ? ` · ${option.hint}` : ''}
          </option>
        ))}
      </select>
      {selected?.hint ? <small>{selected.hint}</small> : null}
    </label>
  )
}

function ModelInfo({ text }: { text: string }) {
  if (!text) return null
  return <p className="model-info">{text}</p>
}

function stripEmoji(value: unknown) {
  return String(value || '').replace(/^[^\p{L}\p{N}]+/u, '').trim()
}

function generationConfig(data: AppState) {
  return (data.features?.generation || {}) as Record<string, unknown>
}

function configMap(data: AppState, key: 'image_models' | 'video_models') {
  const map = generationConfig(data)[key]
  return (map && typeof map === 'object' ? map : {}) as Record<string, Record<string, unknown>>
}

function modelOptionsFromConfig(data: AppState, flow: string): OptionItem[] {
  if (utilityFlows.includes(flow)) return []
  if (flow === 'motion_control') {
    return motionModelOptions.map((option) => {
      const costs = costMap(data, 'video_models')[option.id]
      const values = costs && typeof costs === 'object'
        ? Object.values(costs as Record<string, unknown>).map(Number).filter((value) => value > 0)
        : []
      return { ...option, hint: values.length ? `от ${Math.min(...values)} БК` : option.hint }
    })
  }
  if (flow === 'multi_photo') {
    return [{ id: 'mix_photo', label: 'Remix', hint: '3 ИИ' }]
  }
  if (['image', 'image_edit', 'multi_photo', 'upscale'].includes(flow)) {
    return Object.entries(configMap(data, 'image_models'))
      .filter(([, cfg]) => (flow === 'multi_photo' || flow === 'image_edit' || flow === 'upscale') ? Boolean(cfg.supports_refs || cfg.requires_refs) : true)
      .map(([id, cfg]) => ({
        id,
        label: stripEmoji(cfg.label || id),
        hint: modelCostHint(data, flow, id, cfg),
      }))
  }
  const neededType = flow === 'video_text' ? 'text' : flow === 'video_edit' ? 'video' : flow === 'gemini_omni' ? 'text' : 'imgtxt'
  return Object.entries(configMap(data, 'video_models'))
    .filter(([id, cfg]) => {
      if (flow === 'gemini_omni') return id === 'gemini_omni'
      const types = Array.isArray(cfg.v_types) ? cfg.v_types.map(String) : []
      return types.includes(neededType)
    })
    .map(([id, cfg]) => ({
      id,
      label: stripEmoji(cfg.label || id),
      hint: modelCostHint(data, flow, id, cfg),
    }))
}

const modelDescriptions: Record<string, string> = {
  banana_pro: 'Детальная универсальная фото-модель: хорошо держит стиль, лица и качество.',
  banana_2: 'Быстрая базовая фото-модель для простых генераций и референсов.',
  gpt_image_2: 'Сильна в сложных промптах, тексте на изображении и аккуратной композиции.',
  grok_t2i: 'Текст в изображение без референсов, быстрые идеи и стилизация.',
  grok_i2i: 'Изображение в изображение: меняет кадр по референсу и промпту.',
  seedream_5_lite: 'Легкая image-to-image модель для правок и микса референсов.',
  seedream_edit: 'Редактирование и микс фото, когда важна управляемость изменений.',
  ideogram_character: 'Персонажи и узнаваемость по референсу.',
  v3_std: 'Стандартное видео: оптимальный баланс цены и качества.',
  v3_pro: 'Видео Pro: лучше детализация, движение и стабильность.',
  gemini_omni: 'Omni-режим для смешанных фото, видео, аудио и промпта.',
  runway: 'Кинематографичные видео и плавная динамика.',
  seedance2: 'Динамичные image-to-video ролики по референсу.',
  grok_imagine: 'Быстрые I2V-ролики с выразительной стилизацией.',
}

function modelDescription(model: string, flow: string) {
  if (flow === 'multi_photo') {
    return 'Remix отправляет один промпт и фото сразу в 3 ИИ: Banana 2, Grok Img→Img и GPT Image 2.'
  }
  if (flow === 'motion_control') {
    return 'Motion Control берет фото персонажа и отдельный видео-референс движения.'
  }
  return modelDescriptions[model] || ''
}

function assistantDefaults(flow: string) {
  return {
    improve_prompt: false,
    face_preservation: flowNeedsReferences(flow) ? 'strict' : 'none',
  }
}

function modelConfigForForm(data: AppState, flow: string, model: string) {
  if (flow === 'multi_photo') return configMap(data, 'image_models').banana_2 || {}
  const key = videoFlows.includes(flow) ? 'video_models' : 'image_models'
  return configMap(data, key)[model] || {}
}

function isVideoReference(url: string) {
  return /\.(mp4|mov|webm|m4v)(\?|#|$)/i.test(url)
}

function costMap(data: AppState, key: 'image_models' | 'video_models') {
  const generation = generationConfig(data)
  const costs = generation.costs && typeof generation.costs === 'object' ? generation.costs as Record<string, unknown> : {}
  const map = costs[key]
  return (map && typeof map === 'object' ? map : {}) as Record<string, unknown>
}

function generationCost(data: AppState, flow: string, model: string, duration: string | number, cfg: Record<string, unknown>) {
  if (!model || utilityFlows.includes(flow)) return 0
  if (flow === 'multi_photo') {
    const imageCosts = costMap(data, 'image_models')
    return remixPhotoModels.reduce((sum, item) => sum + Number(imageCosts[item] ?? 0), 0)
  }
  if (videoFlows.includes(flow)) {
    const modelCosts = costMap(data, 'video_models')[model]
    const costs = modelCosts && typeof modelCosts === 'object' ? modelCosts as Record<string, unknown> : {}
    return Number(costs[String(duration)] ?? costs[String(Number(duration || 5))] ?? Object.values(costs)[0] ?? 0)
  }
  const key = String(cfg.cost_key || model)
  const imageCosts = costMap(data, 'image_models')
  return Number(imageCosts[model] ?? imageCosts[key] ?? 0)
}

function supportsImageVariations(flow: string) {
  return ['image', 'image_edit', 'upscale'].includes(flow)
}

function modelCostHint(data: AppState, flow: string, model: string, cfg: Record<string, unknown>) {
  if (flow === 'motion_control') return ''
  if (videoFlows.includes(flow)) {
    const modelCosts = costMap(data, 'video_models')[model]
    const values = modelCosts && typeof modelCosts === 'object'
      ? Object.values(modelCosts as Record<string, unknown>).map(Number).filter((value) => value > 0)
      : []
    return values.length ? `от ${Math.min(...values)} БК` : ''
  }
  const cost = generationCost(data, flow, model, 0, cfg)
  return cost ? `${cost} БК` : ''
}

function optionItems(values: unknown[], labeler = (value: unknown) => String(value)): OptionItem[] {
  return values.map((value) => ({ id: String(value), label: labeler(value) }))
}

function defaultOptionsForModel(data: AppState, flow: string, model: string) {
  const cfg = modelConfigForForm(data, flow, model)
  const defaults = (cfg.defaults && typeof cfg.defaults === 'object' ? cfg.defaults : {}) as Record<string, unknown>
  return { ...defaults, ...assistantDefaults(flow) }
}

function firstAspectRatio(data: AppState, flow: string, model: string) {
  const cfg = modelConfigForForm(data, flow, model)
  const ratios = Array.isArray(cfg.aspect_ratios) ? cfg.aspect_ratios.map(String) : []
  if (ratios.length) return ratios[0]
  return videoFlows.includes(flow) ? '16:9' : '1:1'
}

function firstDuration(data: AppState, flow: string, model: string) {
  const cfg = modelConfigForForm(data, flow, model)
  const durations = Array.isArray(cfg.durations) ? cfg.durations.map(String) : []
  return durations[0] || '5'
}

function optionLabel(optionName: string, value: unknown) {
  if (typeof value === 'boolean') return value ? 'Вкл' : 'Выкл'
  const labels: Record<string, Record<string, string>> = {
    resolution: { '720p': 'HD', '1080p': 'Full HD', '4k': '4K', '2K': '2K', '4K': '4K', '768P': '768P', '1080P': '1080P' },
    output_format: { png: 'PNG', jpg: 'JPG' },
    quality: { basic: 'Basic', high: 'High', '720p': 'HD', '1080p': 'Full HD' },
    mode: { normal: 'Normal', fun: 'Fun', spicy: 'Spicy' },
    rendering_speed: { TURBO: 'Turbo', BALANCED: 'Balanced', QUALITY: 'Quality' },
    style: { AUTO: 'Auto', REALISTIC: 'Realistic', FICTION: 'Fiction' },
    audio_setting: { auto: 'Auto', keep: 'Keep', remove: 'Remove' },
    face_preservation: { strict: 'Максимально', enhance: 'Мягко улучшить', none: 'Не сохранять' },
  }
  return labels[optionName]?.[String(value)] || String(value)
}

function optionNameLabel(optionName: string) {
  const labels: Record<string, string> = {
    resolution: 'Разрешение',
    output_format: 'Файл',
    enable_pro: 'Pro режим',
    quality: 'Качество',
    nsfw_checker: 'NSFW check',
    rendering_speed: 'Скорость',
    style: 'Стиль',
    expand_prompt: 'Улучшение промпта',
    improve_prompt: 'Улучшить промпт',
    face_preservation: 'Сохранить лицо',
    sound: 'Звук',
    web_search: 'Web search',
    mode: 'Режим',
    motion_quality: 'Motion',
    character_orientation: 'Ориентация',
    keep_original_sound: 'Ориг. звук',
    prompt_optimizer: 'Оптимизация',
    enable_translation: 'Перевод',
    prompt_extend: 'Улучшение',
    watermark: 'Watermark',
    audio_setting: 'Аудио',
  }
  return labels[optionName] || optionName
}

function sectionForFlow(flow: string) {
  return createSections.find((section) => section.flows.includes(flow))?.id || ''
}

function CreatePage({ data, lang, mutate, initialFlow, initialDraft }: { data: AppState; lang: Lang; mutate: Mutate; initialFlow: string; initialDraft: CreateDraft | null }) {
  const t = (key: string) => translate(lang, key)
  const draftFlow = initialDraft?.flow || initialFlow
  const [activeFlow, setActiveFlow] = useState(draftFlow)
  const [activeSection, setActiveSection] = useState(sectionForFlow(draftFlow))
  const initialModel = draftFlow ? defaultModelForFlow(draftFlow, data) : ''
  const [form, setForm] = useState({
    flow: draftFlow,
    prompt: initialDraft?.prompt || '',
    model: initialModel,
    aspect_ratio: draftFlow ? firstAspectRatio(data, draftFlow, initialModel) : '1:1',
    duration: draftFlow ? firstDuration(data, draftFlow, initialModel) : '5',
    count: initialDraft?.count || '1',
    options: draftFlow ? defaultOptionsForModel(data, draftFlow, initialModel) : {} as Record<string, unknown>,
  })
  const [refs, setRefs] = useState<string[]>([])
  const [motionPhoto, setMotionPhoto] = useState('')
  const [motionVideo, setMotionVideo] = useState('')
  const [uploadingRefs, setUploadingRefs] = useState(false)
  const [uploadError, setUploadError] = useState('')
  useEffect(() => {
    const nextFlow = initialDraft?.flow || initialFlow
    setActiveFlow(nextFlow)
    setActiveSection(sectionForFlow(nextFlow))
    if (!nextFlow) return
    const nextOptions = modelOptionsFromConfig(data, nextFlow)
    const draftModel = initialDraft?.model || form.model
    const nextModel = nextOptions.some((item) => item.id === draftModel) ? draftModel : nextOptions[0]?.id || defaultModelForFlow(nextFlow, data)
    setForm((current) => ({
      ...current,
      flow: nextFlow,
      prompt: initialDraft?.prompt ?? current.prompt,
      model: nextModel,
      aspect_ratio: initialDraft?.aspect_ratio || firstAspectRatio(data, nextFlow, nextModel),
      duration: initialDraft?.duration || firstDuration(data, nextFlow, nextModel),
      count: initialDraft?.count || current.count || '1',
      options: defaultOptionsForModel(data, nextFlow, nextModel),
    }))
  }, [initialFlow, initialDraft, data.settings.preferred_video_model, data.settings.image_service])
  const selectedFlow = activeFlow || form.flow
  const isUtility = utilityFlows.includes(selectedFlow)
  const isVideo = videoFlows.includes(selectedFlow)
  const modelOptions = modelOptionsFromConfig(data, selectedFlow)
  const currentModel = modelOptions.some((item) => item.id === form.model) ? form.model : modelOptions[0]?.id || form.model
  const currentCfg = modelConfigForForm(data, selectedFlow, currentModel)
  const ratioValues = Array.isArray(currentCfg.aspect_ratios) ? currentCfg.aspect_ratios.map(String) : []
  const durationValues = Array.isArray(currentCfg.durations) ? currentCfg.durations.map(String) : []
  const modelSpecificOptions = (currentCfg.options && typeof currentCfg.options === 'object' ? currentCfg.options : {}) as Record<string, unknown[]>
  const showReferences = flowNeedsReferences(selectedFlow) || modelSupportsReferences(currentCfg)
  const showPrompt = flowNeedsPrompt(selectedFlow)
  const currentCost = generationCost(data, selectedFlow, currentModel, form.duration, currentCfg)
  const generationCount = supportsImageVariations(selectedFlow) ? Math.max(1, Math.min(Number(form.count || 1), 6)) : 1
  const totalCost = currentCost * generationCount
  const formOptions = form.options as Record<string, unknown>
  const openFlow = (flow: string) => {
    const nextModel = modelOptionsFromConfig(data, flow)[0]?.id || defaultModelForFlow(flow, data)
    setActiveFlow(flow)
    setActiveSection(sectionForFlow(flow))
    setRefs([])
    setMotionPhoto('')
    setMotionVideo('')
    setForm({
      flow,
      prompt: '',
      model: nextModel,
      aspect_ratio: firstAspectRatio(data, flow, nextModel),
      duration: firstDuration(data, flow, nextModel),
      count: '1',
      options: defaultOptionsForModel(data, flow, nextModel),
    })
  }
  const closeFlow = () => {
    setActiveFlow('')
    setRefs([])
    setMotionPhoto('')
    setMotionVideo('')
    setUploadError('')
  }
  const set = (key: string, value: string | boolean) => {
    if (key === 'model') {
      const nextModel = String(value)
      setForm({
        ...form,
        model: nextModel,
        aspect_ratio: firstAspectRatio(data, selectedFlow, nextModel),
        duration: firstDuration(data, selectedFlow, nextModel),
        options: defaultOptionsForModel(data, selectedFlow, nextModel),
      })
      return
    }
    setForm({ ...form, [key]: value })
  }
  const setOption = (key: string, value: unknown) => {
    setForm({ ...form, options: { ...form.options, [key]: value } })
  }
  const upload = async (files: FileList | null) => {
    if (!files?.length) return
    const remainingSlots = Math.max(0, 14 - refs.length)
    if (!remainingSlots) return
    setUploadingRefs(true)
    setUploadError('')
    const uploaded: string[] = []
    let failed = 0
    for (const file of Array.from(files).slice(0, remainingSlots)) {
      try {
        uploaded.push(await uploadReference(file))
      } catch {
        failed += 1
      }
    }
    if (uploaded.length) {
      setRefs((current) => [...current, ...uploaded].slice(0, 14))
    }
    if (failed) {
      setUploadError(`${t('actionError')}: ${failed}`)
    }
    setUploadingRefs(false)
  }
  const uploadMotionAsset = async (files: FileList | null, kind: 'photo' | 'video') => {
    const file = files?.[0]
    if (!file) return
    setUploadingRefs(true)
    setUploadError('')
    try {
      const url = await uploadReference(file)
      if (kind === 'photo') setMotionPhoto(url)
      if (kind === 'video') setMotionVideo(url)
    } catch {
      setUploadError(t('actionError'))
    } finally {
      setUploadingRefs(false)
    }
  }
  if (!activeFlow && !activeSection) {
    return (
      <div className="stack">
        <section className="panel create-surface">
          <div className="panel-title"><h2>{t('generationMode')}</h2><span>{fmtNum(data.stats.credits, lang)} {t('boomcoins')}</span></div>
          <div className="flow-picker" aria-label={t('generationMode')}>
            {createSections.map(({ id, label, icon, accent, accent2 }) => (
              <button
                key={id}
                type="button"
                className="flow-card"
                style={{ '--accent': accent, '--accent-2': accent2 } as CSSProperties}
                onClick={() => setActiveSection(id)}
              >
                <span className="flow-icon" style={{ color: accent }} aria-hidden="true"><FlowGlyph id={icon} /></span>
                <strong>{t(label)}</strong>
              </button>
            ))}
          </div>
        </section>
      </div>
    )
  }
  if (!activeFlow && activeSection) {
    const section = createSections.find((item) => item.id === activeSection)
    const sectionFlows = createFlows.filter((flow) => section?.flows.includes(flow.id))
    return (
      <div className="stack">
        <section className="panel create-surface">
          <div className="create-detail-head">
            <button type="button" onClick={() => setActiveSection('')}>{t('generationMode')}</button>
            <div>
              <span>{t('create')}</span>
              <h2>{section ? t(section.label) : t('generationMode')}</h2>
            </div>
            <strong>{fmtNum(data.stats.credits, lang)} {t('boomcoins')}</strong>
          </div>
          <div className={cls('flow-picker', 'flow-picker-sub', sectionFlows.length === 1 && 'single')} aria-label={section ? t(section.label) : t('generationMode')}>
            {sectionFlows.map(({ id, label, accent, accent2 }) => (
              <button
                key={id}
                type="button"
                className="flow-card"
                style={{ '--accent': accent, '--accent-2': accent2 } as CSSProperties}
                onClick={() => openFlow(id)}
              >
                <span className="flow-icon" style={{ color: accent }} aria-hidden="true"><FlowGlyph id={id} /></span>
                <strong>{t(label)}</strong>
              </button>
            ))}
          </div>
        </section>
      </div>
    )
  }
  const activeFlowMeta = createFlows.find((item) => item.id === selectedFlow)
  return (
    <div className="stack">
      <section className="panel create-flow-head">
        <div className="create-detail-head">
          <button type="button" onClick={closeFlow}>{activeSection ? t(createSections.find((item) => item.id === activeSection)?.label || 'generationMode') : t('generationMode')}</button>
          <div>
            <span>{t('generation')}</span>
            <h2>{activeFlowMeta ? t(activeFlowMeta.label) : t('create')}</h2>
          </div>
          <strong>{fmtNum(data.stats.credits, lang)} {t('boomcoins')}</strong>
        </div>
      </section>
      {!isUtility ? (
        <section className="panel smart-settings">
          {modelOptions.length > 1 ? (
            modelOptions.length > 4 ? (
              <ModelSelect label={t('modelChoice')} options={modelOptions} value={currentModel} onChange={(value) => set('model', value)} />
            ) : (
              <ChoiceGroup label={t('modelChoice')} options={modelOptions} value={currentModel} onChange={(value) => set('model', value)} />
            )
          ) : null}
          {currentModel ? <ModelInfo text={modelDescription(currentModel, selectedFlow)} /> : null}
          {ratioValues.length ? (
            <ChoiceGroup label={t('formatChoice')} options={optionItems(ratioValues)} value={form.aspect_ratio} onChange={(value) => set('aspect_ratio', value)} />
          ) : null}
          {isVideo && durationValues.length ? (
            <ChoiceGroup label={t('durationChoice')} options={optionItems(durationValues, (value) => `${value} сек`)} value={form.duration} onChange={(value) => set('duration', value)} />
          ) : null}
          {supportsImageVariations(selectedFlow) ? (
            <ChoiceGroup label={t('variations')} options={optionItems([1, 2, 3, 4, 5, 6], (value) => `${value}×`)} value={String(generationCount)} onChange={(value) => set('count', value)} />
          ) : null}
          {Object.entries(modelSpecificOptions)
            .filter(([key]) => !['aspect_ratio'].includes(key))
            .map(([key, values]) => (
              <ChoiceGroup
                key={key}
                label={optionNameLabel(key)}
                options={optionItems(Array.isArray(values) ? values : [], (value) => optionLabel(key, value))}
                value={String(formOptions[key] ?? '')}
                onChange={(value) => {
                  const source = Array.isArray(values) ? values.find((item) => String(item) === value) : value
                  setOption(key, source ?? value)
                }}
              />
            ))}
          {showPrompt ? (
            <ChoiceGroup
              label={optionNameLabel('improve_prompt')}
              options={optionItems([false, true], (value) => optionLabel('improve_prompt', value))}
              value={String(Boolean(formOptions.improve_prompt))}
              onChange={(value) => setOption('improve_prompt', value === 'true')}
            />
          ) : null}
          {showReferences ? (
            <ChoiceGroup
              label={optionNameLabel('face_preservation')}
              options={optionItems(['strict', 'enhance', 'none'], (value) => optionLabel('face_preservation', value))}
              value={String(formOptions.face_preservation ?? 'strict')}
              onChange={(value) => setOption('face_preservation', value)}
            />
          ) : null}
          {totalCost ? <PriceSummary lang={lang} cost={totalCost} balance={data.stats.credits} /> : null}
        </section>
      ) : null}
      <section className="panel create-workspace-panel">
        {selectedFlow === 'photo_to_prompt' ? (
          <PhotoToPromptPanel lang={lang} mutate={mutate} />
        ) : selectedFlow === 'prompt_builder' ? (
          <PromptBuilderPanel lang={lang} mutate={mutate} />
        ) : selectedFlow === 'motion_control' ? (
          <MotionControlPanel
            lang={lang}
            form={form}
            currentModel={currentModel}
            motionPhoto={motionPhoto}
            motionVideo={motionVideo}
            cost={currentCost}
            uploading={uploadingRefs}
            uploadError={uploadError}
            setPrompt={(value) => set('prompt', value)}
            uploadMotionAsset={uploadMotionAsset}
            clearPhoto={() => setMotionPhoto('')}
            clearVideo={() => setMotionVideo('')}
            submit={() =>
              mutate(
                () => postAction('/api/tma/app/generation', {
                  ...form,
                  flow: selectedFlow,
                  model: currentModel,
                  duration: Number(form.duration || 5),
                  motion_photo_url: motionPhoto,
                  motion_video_url: motionVideo,
                  references: [motionPhoto, motionVideo].filter(Boolean),
                }),
                t('taskSent'),
              )
            }
          />
        ) : selectedFlow === 'multi_photo' ? (
          <MultiPhotoPanel
            lang={lang}
            form={form}
            refs={refs}
            uploading={uploadingRefs}
            uploadError={uploadError}
            cost={currentCost}
            setPrompt={(value) => set('prompt', value)}
            upload={upload}
            clearRefs={() => setRefs([])}
            submit={() =>
              mutate(
                () => postAction('/api/tma/app/generation', { ...form, flow: selectedFlow, model: currentModel, duration: Number(form.duration || 5), references: refs }),
                t('taskSent'),
              )
            }
          />
        ) : (
          <>
            {showPrompt ? <textarea value={form.prompt} onChange={(e) => set('prompt', e.target.value)} placeholder={t('promptPlaceholder')} /> : null}
            <div className="inline-actions">
              {showReferences ? (
                <>
                  <label className="upload-button">
                    <Upload size={16} /> {uploadingRefs ? t('loadingData') : `${t('refs')} ${refs.length}/14`}
                    <input
                      type="file"
                      multiple
                      accept="image/*,video/*"
                      disabled={uploadingRefs}
                      onChange={(e) => {
                        upload(e.target.files)
                        e.currentTarget.value = ''
                      }}
                    />
                  </label>
                  {refs.length ? <button onClick={() => setRefs([])}>{t('clearRefs')}</button> : null}
                </>
              ) : null}
              <button
                onClick={() =>
                  mutate(
                    () => postAction('/api/tma/app/generation', { ...form, flow: selectedFlow, model: currentModel, duration: Number(form.duration || 5), count: generationCount, references: refs }),
                    t('taskSent'),
                  )
                }
              >
                <Play size={16} /> {totalCost ? `${t('run')} · ${fmtNum(totalCost, lang)} ${t('boomcoins')}` : t('run')}
              </button>
            </div>
            {uploadError ? <div className="form-error">{uploadError}</div> : null}
            {refs.length ? <div className="ref-strip">{refs.map((url) => <span key={url}>{url.split('/').pop()}</span>)}</div> : null}
          </>
        )}
      </section>
    </div>
  )
}

function PriceSummary({ lang, cost, balance }: { lang: Lang; cost: number; balance: unknown }) {
  const t = (key: string) => translate(lang, key)
  const enough = Number(balance || 0) >= cost
  return (
    <div className={cls('price-summary', !enough && 'warning')}>
      <span>{t('chargeNow')}</span>
      <strong>{fmtNum(cost, lang)} {t('boomcoins')}</strong>
    </div>
  )
}

function MotionControlPanel({
  lang,
  form,
  currentModel,
  motionPhoto,
  motionVideo,
  cost,
  uploading,
  uploadError,
  setPrompt,
  uploadMotionAsset,
  clearPhoto,
  clearVideo,
  submit,
}: {
  lang: Lang
  form: { prompt: string; duration: string; options: Record<string, unknown> }
  currentModel: string
  motionPhoto: string
  motionVideo: string
  cost: number
  uploading: boolean
  uploadError: string
  setPrompt: (value: string) => void
  uploadMotionAsset: (files: FileList | null, kind: 'photo' | 'video') => void
  clearPhoto: () => void
  clearVideo: () => void
  submit: () => void
}) {
  const t = (key: string) => translate(lang, key)
  const canRun = Boolean(motionPhoto && motionVideo && form.prompt.trim().length >= 3)
  const modelLabel = currentModel === 'v3_pro' ? 'Motion Pro' : 'Motion Standard'
  return (
    <div className="motion-control-screen">
      <textarea value={form.prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={t('promptPlaceholder')} />
      <div className="motion-upload-grid">
        <MotionAssetSlot
          icon={<Image size={18} />}
          title={t('motionPhotoRef')}
          value={motionPhoto}
          accept="image/*"
          busy={uploading}
          onUpload={(files) => uploadMotionAsset(files, 'photo')}
          onClear={clearPhoto}
        />
        <MotionAssetSlot
          icon={<Video size={18} />}
          title={t('motionVideoRef')}
          value={motionVideo}
          accept="video/*"
          busy={uploading}
          onUpload={(files) => uploadMotionAsset(files, 'video')}
          onClear={clearVideo}
        />
      </div>
      {uploadError ? <div className="form-error">{uploadError}</div> : null}
      <div className="motion-summary">
        <span>{modelLabel}</span>
        <span>{Number(form.duration || 5)} сек</span>
        {cost ? <span>{cost} {t('boomcoins')}</span> : null}
      </div>
      <div className="inline-actions">
        <button disabled={!canRun || uploading} onClick={submit}>
          <Play size={16} /> {cost ? `${t('run')} · ${fmtNum(cost, lang)} ${t('boomcoins')}` : t('run')}
        </button>
      </div>
    </div>
  )
}

function MultiPhotoPanel({
  lang,
  form,
  refs,
  uploading,
  uploadError,
  cost,
  setPrompt,
  upload,
  clearRefs,
  submit,
}: {
  lang: Lang
  form: { prompt: string }
  refs: string[]
  uploading: boolean
  uploadError: string
  cost: number
  setPrompt: (value: string) => void
  upload: (files: FileList | null) => void
  clearRefs: () => void
  submit: () => void
}) {
  const t = (key: string) => translate(lang, key)
  const canRun = refs.length >= 2 && form.prompt.trim().length >= 3 && !uploading
  return (
    <div className="multi-photo-screen">
      <div className="multi-photo-hero">
        <strong>{t('multiPhoto')}</strong>
        <span>{refs.length}/14</span>
      </div>
      <textarea
        value={form.prompt}
        onChange={(event) => setPrompt(event.target.value)}
        placeholder={t('multiPhotoPrompt')}
      />
      <div className="inline-actions">
        <label className="upload-button primary-upload">
          <Upload size={16} /> {uploading ? t('loadingData') : t('multiPhotoUpload')}
          <input
            type="file"
            multiple
            accept="image/*"
            disabled={uploading}
            onChange={(event) => {
              upload(event.target.files)
              event.currentTarget.value = ''
            }}
          />
        </label>
        {refs.length ? <button onClick={clearRefs}>{t('clearRefs')}</button> : null}
      </div>
      <div className={cls('multi-photo-state', refs.length >= 2 && 'ready')}>
        <span>{refs.length >= 2 ? t('multiPhotoReady') : t('multiPhotoNeed')}</span>
      </div>
      {uploadError ? <div className="form-error">{uploadError}</div> : null}
      {refs.length ? (
        <div className="ref-strip ref-strip-grid">
          {refs.map((url, index) => <span key={url}>{index + 1}. {url.split('/').pop()}</span>)}
        </div>
      ) : null}
      <div className="inline-actions">
        <button disabled={!canRun} onClick={submit}>
          <Play size={16} /> {cost ? `${t('run')} · ${fmtNum(cost, lang)} ${t('boomcoins')}` : t('run')}
        </button>
      </div>
    </div>
  )
}

function MotionAssetSlot({
  icon,
  title,
  value,
  accept,
  busy,
  onUpload,
  onClear,
}: {
  icon: ReactNode
  title: string
  value: string
  accept: string
  busy: boolean
  onUpload: (files: FileList | null) => void
  onClear: () => void
}) {
  return (
    <div className={cls('motion-slot', value && 'filled')}>
      <div>
        {icon}
        <strong>{title}</strong>
      </div>
      {value ? <span>{value.split('/').pop()}</span> : null}
      <div className="inline-actions">
        <label className="upload-button">
          <Upload size={16} /> {busy ? 'Загрузка' : value ? 'Заменить' : 'Загрузить'}
          <input
            type="file"
            accept={accept}
            disabled={busy}
            onChange={(event) => {
              onUpload(event.target.files)
              event.currentTarget.value = ''
            }}
          />
        </label>
        {value ? <button onClick={onClear}>Очистить</button> : null}
      </div>
    </div>
  )
}

function PhotoToPromptPanel({ lang, mutate }: { lang: Lang; mutate: Mutate }) {
  const t = (key: string) => translate(lang, key)
  const [prompt, setPrompt] = useState('')
  const [fileName, setFileName] = useState('')
  const run = async (files: FileList | null) => {
    const file = files?.[0]
    if (!file) return
    setFileName(file.name)
    const result = await analyzePhotoToPrompt(file)
    setPrompt(result)
  }
  return (
    <div className="tool-panel">
      <label className="upload-button primary-upload">
        <Image size={16} /> {t('uploadPhoto')}
        <input type="file" accept="image/*" onChange={(event) => mutate(() => run(event.target.files), t('promptReady'))} />
      </label>
      {fileName ? <span className="tool-note">{fileName}</span> : null}
      {prompt ? <textarea className="result-box" readOnly value={prompt} /> : null}
    </div>
  )
}

function PromptBuilderPanel({ lang, mutate }: { lang: Lang; mutate: Mutate }) {
  const t = (key: string) => translate(lang, key)
  const [idea, setIdea] = useState('')
  const [prompt, setPrompt] = useState('')
  const build = async () => {
    const result = await postAction<{ prompt?: string }>('/api/tma/app/prompt-builder', { idea })
    setPrompt(result.prompt || '')
  }
  return (
    <div className="tool-panel">
      <textarea value={idea} onChange={(event) => setIdea(event.target.value)} placeholder={t('ideaPlaceholder')} />
      <button onClick={() => mutate(build, t('promptBuilt'))}><Wand2 size={16} /> {t('buildPrompt')}</button>
      {prompt ? <textarea className="result-box" readOnly value={prompt} /> : null}
    </div>
  )
}

function HistoryPage({ data, lang, mutate }: { data: AppState; lang: Lang; mutate: Mutate }) {
  const t = (key: string) => translate(lang, key)
  if (!data.tasks.length) {
    return <StateCard title={t('history')} text={t('emptyHistoryText')} />
  }
  return (
    <div className="cards">
      {data.tasks.map((row) => (
        <article className="row-card history-card" key={String(row.task_id)}>
          {row.result_url ? (
            <FeedPreview url={row.result_url} />
          ) : (
            <div className="feed-media history-placeholder"><Sparkles size={26} /></div>
          )}
          <div className="history-info">
            <div>
              <strong>{String(row.model || row.preset_id || displayValue(row.type, lang))}</strong>
              <span>{String(row.task_id)} · {displayValue(row.status, lang)} · {fmtNum(row.cost, lang)} {t('boomcoins')}</span>
            </div>
            <div className="inline-actions">
              {row.result_url ? <a href={String(row.result_url)} target="_blank">{t('open')}</a> : null}
              {row.result_url ? <button onClick={() => mutate(() => postAction(`/api/tma/app/feed/${row.task_id}/action`, { action: 'publish' }), t('published'))}>{t('publishToFeed')}</button> : null}
            </div>
          </div>
        </article>
      ))}
    </div>
  )
}

function createDraftFromFeedRow(row: Record<string, unknown>): CreateDraft {
  const preset = String(row.preset_id || '')
  const knownFlow = createFlows.some((item) => item.id === preset) ? preset : ''
  return {
    flow: knownFlow || (String(row.type || '') === 'video' ? 'video_text' : 'image'),
    prompt: String(row.prompt || ''),
    model: row.model ? String(row.model) : undefined,
    aspect_ratio: row.aspect_ratio ? String(row.aspect_ratio) : undefined,
    duration: row.duration ? String(row.duration) : undefined,
    count: '1',
  }
}

function UserFeedPage({ data, lang, mutate, openRepeat }: { data: AppState; lang: Lang; mutate: Mutate; openRepeat: (draft: CreateDraft) => void }) {
  const t = (key: string) => translate(lang, key)
  const [opened, setOpened] = useState<Record<string, unknown> | null>(null)
  if (!data.feed.length) {
    return <StateCard title={t('emptyFeed')} text={t('emptyFeedText')} />
  }
  return (
    <>
      <div className="feed-grid pinterest-feed">
        {data.feed.map((row) => (
          <article className="feed-card pin-card" key={String(row.task_id)}>
            <FeedPreview url={row.result_url} variant="pin" onOpen={() => setOpened(row)} />
            {!row.is_public_feed ? <span className="feed-badge pin-badge">{t('newWork')}</span> : null}
            <div className="pin-overlay">
              <FeedAuthor row={row} />
              {row.prompt ? <p>{String(row.prompt || '').slice(0, 140)}</p> : null}
              <span>{fmtNum(row.likes_count, lang)} {t('likes')} · {fmtNum(row.shares_count, lang)} {t('repeats')}</span>
              <div className="pin-actions">
                <button className="pin-like" type="button" aria-label={t('like')} title={t('like')} onClick={() => mutate(() => postAction(`/api/tma/app/feed/${row.task_id}/action`, { action: 'like' }), t('likeAdded'))}>♥</button>
                <button className="pin-repeat" type="button" title={t('repeat')} onClick={() => openRepeat(createDraftFromFeedRow(row))}><RefreshCw size={14} /> {t('repeat')}</button>
              </div>
            </div>
          </article>
        ))}
      </div>
      {opened ? (
        <FeedLightbox
          row={opened}
          lang={lang}
          onClose={() => setOpened(null)}
          onRepeat={() => {
            openRepeat(createDraftFromFeedRow(opened))
            setOpened(null)
          }}
        />
      ) : null}
    </>
  )
}

type ChatLine = { role: string; content: string; streaming?: boolean }

function GPTPage({ data, lang, mutate }: { data: AppState; lang: Lang; mutate: Mutate }) {
  const t = (key: string) => translate(lang, key)
  const [message, setMessage] = useState('')
  const [streaming, setStreaming] = useState(false)
  const endRef = useRef<HTMLDivElement | null>(null)
  const [history, setHistory] = useState<ChatLine[]>(() =>
    data.gpt55_history
      .map((item) => ({
        role: roleLabel(item.role, lang),
        content: readableMessage(item.content),
      }))
      .filter((item) => item.content),
  )
  useEffect(() => {
    setHistory(
      data.gpt55_history
        .map((item) => ({
          role: roleLabel(item.role, lang),
          content: readableMessage(item.content),
        }))
        .filter((item) => item.content),
    )
  }, [data.gpt55_history, lang])
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [history, streaming])

  const send = async () => {
    const text = message.trim()
    if (!text || streaming) return
    setMessage('')
    setStreaming(true)
    setHistory((items) => [
      ...items,
      { role: t('userRole'), content: text },
      { role: t('assistantRole'), content: '', streaming: true },
    ])
    try {
      const done = await streamGpt55(text, (delta) => {
        setHistory((items) => {
          const next = [...items]
          const last = next[next.length - 1]
          if (last?.role === t('assistantRole')) {
            next[next.length - 1] = { ...last, content: `${last.content}${delta}`, streaming: true }
          }
          return next
        })
      })
      const rawHistory = done?.history
      if (Array.isArray(rawHistory)) {
        setHistory(
          rawHistory
            .map((item) => ({
              role: roleLabel((item as Record<string, unknown>).role, lang),
              content: readableMessage((item as Record<string, unknown>).content),
            }))
            .filter((item) => item.content),
        )
      } else {
        setHistory((items) => items.map((item, index) => index === items.length - 1 ? { ...item, streaming: false } : item))
      }
    } catch (err) {
      setHistory((items) => {
        const next = [...items]
        const last = next[next.length - 1]
        if (last?.role === t('assistantRole')) {
          next[next.length - 1] = { ...last, content: err instanceof Error ? err.message : t('actionError'), streaming: false }
        }
        return next
      })
    } finally {
      setStreaming(false)
    }
  }

  const clearChat = async () => {
    setHistory([])
    await mutate(() => postAction('/api/tma/app/gpt55/clear'), t('contextCleared'))
  }

  return (
    <div className="chatgpt-shell">
      <section className="chatgpt-panel">
        <div className="chatgpt-head">
          <div>
            <span>BOOM Studio</span>
            <h2>ChatGPT</h2>
          </div>
          <button onClick={clearChat} disabled={streaming}>{t('clear')}</button>
        </div>
        <div className="chat-history">
          {!history.length ? (
            <div className="chat-empty">
              <h3>{t('gptWelcome')}</h3>
              <p>{t('gptWelcomeText')}</p>
            </div>
          ) : null}
          {history.map((item, index) => (
            <article className={cls('chat-message', item.role === t('userRole') ? 'from-user' : 'from-assistant')} key={index}>
              <div className="chat-avatar">{item.role === t('userRole') ? 'Y' : 'GPT'}</div>
              <div>
                <strong>{item.role}</strong>
                <p>{item.content || (item.streaming ? t('typing') : '')}</p>
              </div>
            </article>
          ))}
          <div ref={endRef} />
        </div>
        <div className="chat-composer">
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                void send()
              }
            }}
            placeholder={t('messagePlaceholder')}
            disabled={streaming}
          />
          <button onClick={() => void send()} disabled={streaming || !message.trim()}>
            <ArrowUp size={17} />
          </button>
        </div>
      </section>
    </div>
  )
}

function BillingPage({ data, lang, mutate }: { data: AppState; lang: Lang; mutate: Mutate }) {
  const t = (key: string) => translate(lang, key)
  const [promo, setPromo] = useState<Record<string, unknown> | null>(null)
  const [code, setCode] = useState('')
  const buy = async (pkg: Record<string, unknown>, recurring = false) => {
    const result = await postAction<{ payment_url?: string }>('/api/tma/app/payment', { package_id: pkg.id, provider: 'tbank', recurring, promo: promo || undefined })
    if (result.payment_url) window.open(result.payment_url, '_blank')
  }
  return (
    <div className="stack">
      <section className="panel form-grid">
        <input value={code} onChange={(e) => setCode(e.target.value)} placeholder={t('promoCode')} />
        <button onClick={() => mutate(async () => {
          const result = await postAction<{ promo?: Record<string, unknown> }>('/api/tma/app/promo', { code })
          setPromo(result.promo || null)
        }, t('promoApplied'))}>{t('apply')}</button>
        <button onClick={() => mutate(() => postAction('/api/tma/app/recurring/disable'), t('recurringDisabled'))}>{t('disableRecurring')}</button>
      </section>
      <div className="cards packages">
        {data.packages.map((pkg) => (
          <PackageCard key={String(pkg.id)} pkg={pkg} lang={lang} onBuy={(recurring) => mutate(() => buy(pkg, recurring), t('paymentCreated'))} />
        ))}
      </div>
      <section className="panel">
        <div className="panel-title"><h2>{t('payments')}</h2><span>{data.payments.length}</span></div>
        <div className="cards">
          {data.payments.map((payment) => (
            <article className="row-card" key={String(payment.order_id)}>
              <div>
                <strong>{fmtMoney(payment.amount_rub, lang)} · {displayValue(payment.status, lang)}</strong>
                <span>{String(payment.order_id)} · {displayValue(payment.provider, lang)}</span>
              </div>
              <div className="inline-actions">
                <button onClick={() => mutate(() => postAction(`/api/tma/app/payment/${payment.order_id}/check`), t('paymentStatusUpdated'))}>
                  {t('checkPayment')}
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}

function PackageCard({ pkg, lang, onBuy }: { pkg: Record<string, unknown>; lang: Lang; onBuy: (recurring: boolean) => void }) {
  const t = (key: string) => translate(lang, key)
  const credits = Number(pkg.credits || 0)
  const bonus = Number(pkg.bonus_credits || 0)
  const totalCredits = credits + bonus
  const isSubscription = String(pkg.kind || '') === 'subscription' || Number(pkg.subscription_days || 0) > 0
  const details = [
    totalCredits ? `${fmtNum(totalCredits, lang)} ${t('boomcoins')}` : '',
    pkg.period ? String(pkg.period) : '',
    pkg.photo_limit_text ? String(pkg.photo_limit_text) : '',
    pkg.video_limit_text ? String(pkg.video_limit_text) : '',
  ].filter(Boolean)
  const badges = [
    bonus ? `+${fmtNum(bonus, lang)} бонус` : '',
    pkg.includes_pro ? 'PRO' : '',
    pkg.priority ? 'Приоритет' : '',
    pkg.popular ? 'Популярный' : '',
  ].filter(Boolean)
  const description = String(pkg.description || (isSubscription ? 'Доступ к генерациям по подписке и запас Бумкоинов для доплат.' : 'Разовое пополнение баланса для фото, видео и дополнительных генераций.'))
  return (
    <article className="edit-card package-card">
      <div className="package-head">
        <div>
          <strong>{String(pkg.name)}</strong>
          <span>{isSubscription ? 'Подписка' : 'Баланс'}</span>
        </div>
        <b>{fmtMoney(pkg.price_rub, lang)}</b>
      </div>
      <p>{description}</p>
      <div className="package-facts">
        {details.map((item) => <span key={item}>{item}</span>)}
      </div>
      {badges.length ? <div className="package-badges">{badges.map((item) => <span key={item}>{item}</span>)}</div> : null}
      <div className="inline-actions package-actions">
        <button onClick={() => onBuy(false)}>{t('buy')}</button>
        {isSubscription ? <button onClick={() => onBuy(true)}>{t('recurring')}</button> : null}
      </div>
    </article>
  )
}

function PartnerUserPage({ data, lang, mutate }: { data: AppState; lang: Lang; mutate: Mutate }) {
  const t = (key: string) => translate(lang, key)
  const [form, setForm] = useState({ amount_rub: '', requisites: '', recipient_name: '', phone: '', credits: '' })
  const set = (key: string, value: string) => setForm({ ...form, [key]: value })
  return (
    <div className="stack">
      <div className="metrics">
        <Metric label={t('billing')} value={fmtMoney(data.partner.balance_rub, lang)} />
        <Metric label={t('referrals')} value={fmtNum(data.partner.referrals_count, lang)} />
        <Metric label={t('paymentCount')} value={fmtNum(data.partner.total_payments, lang)} />
        <Metric label={t('level')} value={String(data.partner.tier || 'basic')} />
      </div>
      <section className="panel form-grid">
        <button onClick={() => mutate(() => postAction('/api/tma/app/partner', { action: 'accept' }), t('partnerActivated'))}>{t('acceptOffer')}</button>
        <input value={form.credits} onChange={(e) => set('credits', e.target.value)} placeholder={t('boomcoins')} />
        <button onClick={() => mutate(() => postAction('/api/tma/app/partner', { action: 'convert', credits: Number(form.credits || 0) }), t('converted'))}>{t('convert')}</button>
        <input value={form.amount_rub} onChange={(e) => set('amount_rub', e.target.value)} placeholder="₽" />
        <input value={form.recipient_name} onChange={(e) => set('recipient_name', e.target.value)} placeholder={t('recipientName')} />
        <input value={form.phone} onChange={(e) => set('phone', e.target.value)} placeholder={t('phone')} />
        <input value={form.requisites} onChange={(e) => set('requisites', e.target.value)} placeholder={t('requisites')} />
        <button onClick={() => mutate(() => postAction('/api/tma/app/partner', { action: 'withdraw', ...form, amount_rub: Number(form.amount_rub || 0) }), t('withdrawalCreated'))}>{t('withdraw')}</button>
      </section>
      <MiniList title={t('requests')} rows={data.withdrawals} fields={['id', 'amount_rub', 'status', 'created_at']} />
    </div>
  )
}

function SettingsUserPage({ data, lang, setTab, setMode }: { data: AppState; lang: Lang; setTab: (tab: UserTab) => void; setMode: (mode: Mode) => void }) {
  const t = (key: string) => translate(lang, key)
  const stats = data.stats
  const user = data.user || {}
  const subscription = (stats.subscription && typeof stats.subscription === 'object' ? stats.subscription : null) as Record<string, unknown> | null
  const activeTasks = data.tasks.filter((task) => ['pending', 'processing'].includes(String(task.status || '')))
  const completedTasks = data.tasks.filter((task) => String(task.status || '') === 'completed')
  const lastTasks = data.tasks.slice(0, 3)
  const lastPayments = data.payments.slice(0, 3)
  const fullName = [user.first_name, user.last_name].filter(Boolean).join(' ').trim() || authorName({ telegram_id: stats.telegram_id, username: stats.username })
  return (
    <div className="stack">
      <div className="metrics">
        <Metric label={t('billing')} value={`${fmtNum(data.stats.credits, lang)} ${t('boomcoins')}`} />
        <Metric label={t('history')} value={fmtNum(completedTasks.length, lang)} />
        <Metric label="В работе" value={fmtNum(activeTasks.length, lang)} />
      </div>
      <section className="panel profile-actions">
        <button onClick={() => setTab('billing')}><CreditCard size={17} /> {t('billing')}</button>
        <button onClick={() => setTab('partner')}><Wallet size={17} /> {t('partner')}</button>
        <button onClick={() => setTab('feed')}><Image size={17} /> {t('feed')}</button>
        {data.is_admin ? <button onClick={() => setMode('admin')}><ShieldCheck size={17} /> {t('admin')}</button> : null}
      </section>
      <section className="panel account-panel">
        <div className="panel-title"><h2>Личный кабинет</h2><span>ID {String(stats.telegram_id || user.id || '-')}</span></div>
        <div className="account-grid">
          <InfoTile label="Имя" value={fullName} />
          <InfoTile label="Username" value={stats.username ? `@${String(stats.username)}` : 'не указан'} />
          <InfoTile label="С нами" value={String(stats.member_since || '-')} />
          <InfoTile label="Статус" value={stats.is_banned ? 'заблокирован' : 'активен'} />
        </div>
      </section>
      <section className="panel account-panel">
        <div className="panel-title"><h2>Подписка и лимиты</h2><span>{subscription ? displayValue(subscription.status, lang) : 'нет активной'}</span></div>
        <div className="account-grid">
          <InfoTile label="Пакет" value={subscription ? String(subscription.package_name || subscription.package_id || '-') : 'без подписки'} />
          <InfoTile label="Фото" value={subscription ? `${fmtNum(subscription.images_used, lang)} / ${fmtNum(subscription.image_limit, lang)}` : 'по балансу'} />
          <InfoTile label="Видео" value={subscription ? `${fmtNum(subscription.videos_used, lang)} / ${fmtNum(subscription.video_limit, lang)}` : 'по балансу'} />
          <InfoTile label="Pro" value={subscription?.includes_pro ? 'доступен' : 'по тарифу'} />
        </div>
      </section>
      <section className="panel account-panel">
        <div className="panel-title"><h2>Партнерская программа</h2><span>{fmtMoney(data.partner.balance_rub, lang)}</span></div>
        <div className="account-grid">
          <InfoTile label="Реферальный код" value={String(stats.referral_code || '-')} />
          <InfoTile label="Приглашено" value={fmtNum(stats.referrals_count, lang)} />
          <InfoTile label="Начислено" value={`${fmtNum(stats.referral_earned, lang)} ${t('boomcoins')}`} />
          <InfoTile label="Уровень" value={String(data.partner.tier || 'basic')} />
        </div>
      </section>
      <section className="panel account-panel">
        <div className="panel-title"><h2>Последние генерации</h2><button onClick={() => setTab('history')}>{t('open')}</button></div>
        <div className="compact-list">
          {lastTasks.length ? lastTasks.map((task) => (
            <div className="compact-row" key={String(task.task_id)}>
              <span>{displayValue(task.type, lang)} · {String(task.model || task.preset_id || '-')}</span>
              <strong>{displayValue(task.status, lang)}</strong>
            </div>
          )) : <span className="muted-line">Генераций пока нет</span>}
        </div>
      </section>
      <section className="panel account-panel">
        <div className="panel-title"><h2>Последние оплаты</h2><button onClick={() => setTab('billing')}>{t('open')}</button></div>
        <div className="compact-list">
          {lastPayments.length ? lastPayments.map((payment) => (
            <div className="compact-row" key={String(payment.order_id)}>
              <span>{fmtMoney(payment.amount_rub, lang)} · {String(payment.provider || '-')}</span>
              <strong>{displayValue(payment.status, lang)}</strong>
            </div>
          )) : <span className="muted-line">Оплат пока нет</span>}
        </div>
      </section>
    </div>
  )
}

function InfoTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="info-tile">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function Dashboard({ data, mutate, setTab }: { data: ApiState; mutate: Mutate; setTab: (tab: AdminTab) => void }) {
  const d = data.dashboard
  return (
    <div className="stack">
      <div className="metrics">
        <Metric label="Пользователи" value={fmtNum(d.total_users)} />
        <Metric label="Выручка" value={fmtMoney(d.total_revenue)} />
        <Metric label="Сегодня" value={fmtMoney(d.today_revenue)} />
        <Metric label="Генерации" value={fmtNum(d.total_generations)} />
        <Metric label="Оплаты" value={fmtNum(d.total_transactions)} />
        <Metric label="Рефералы" value={fmtNum(d.total_referrals)} />
      </div>
      <section className="panel">
        <div className="panel-title">
          <h2>Оперативное управление</h2>
          <span>Очередь: {fmtNum(d.active_tasks)} · Ошибки: {fmtNum(d.failed_tasks)}</span>
        </div>
        <div className="command-grid">
          <button onClick={() => setTab('users')}><Users size={16} /> Пользователи</button>
          <button onClick={() => setTab('payments')}><CreditCard size={16} /> Оплаты</button>
          <button onClick={() => setTab('partners')}><Wallet size={16} /> Партнеры</button>
          <button
            onClick={() =>
              mutate(
                () =>
                  postAction('/api/tma/admin/settings', { maintenance: !d.maintenance }),
                'Техрежим обновлен',
              )
            }
          >
            <Activity size={16} /> Техрежим: {boolText(d.maintenance)}
          </button>
        </div>
      </section>
      <section className="two-col">
        <MiniList title="Последние оплаты" rows={data.payments.slice(0, 8)} fields={['telegram_id', 'amount_rub', 'status']} />
        <MiniList title="Партнеры" rows={data.partners.slice(0, 8)} fields={['telegram_id', 'users_count', 'revenue_rub']} />
      </section>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function UsersPage({ data, mutate }: { data: ApiState; mutate: Mutate }) {
  const [query, setQuery] = useState('')
  const [rows, setRows] = useState(data.users)
  const [amountById, setAmountById] = useState<Record<string, string>>({})

  useEffect(() => setRows(data.users), [data.users])

  const search = async () => {
    const result = await api<{ users: Record<string, unknown>[] }>(`/api/tma/admin/users?search=${encodeURIComponent(query)}&limit=80`)
    setRows(result.users)
  }

  return (
    <div className="stack">
      <form className="search" onSubmit={(event) => { event.preventDefault(); search() }}>
        <Search size={16} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="ID, ник или имя" />
        <button type="submit">Найти</button>
      </form>
      <div className="cards">
        {rows.map((user) => {
          const id = String(user.telegram_id)
          return (
            <article className="row-card" key={id}>
              <div>
                <strong>{user.username ? `@${user.username}` : id}</strong>
                <span>ID {id} · {fmtNum(user.credits)} Бумкоины · бан: {boolText(user.is_banned)}</span>
              </div>
              <div className="inline-actions">
                <input
                  value={amountById[id] || ''}
                  onChange={(event) => setAmountById({ ...amountById, [id]: event.target.value })}
                  placeholder="сумма"
                  inputMode="numeric"
                />
                <button onClick={() => mutate(() => postAction(`/api/tma/admin/users/${id}/action`, { action: 'add_credits', amount: Number(amountById[id] || 0) }), 'Баланс пополнен')}>+</button>
                <button onClick={() => mutate(() => postAction(`/api/tma/admin/users/${id}/action`, { action: 'deduct_credits', amount: Number(amountById[id] || 0) }), 'Баланс списан')}>-</button>
                <button onClick={() => mutate(() => postAction(`/api/tma/admin/users/${id}/action`, { action: user.is_banned ? 'unban' : 'ban' }), 'Статус обновлен')}>
                  {user.is_banned ? 'Разбан' : 'Бан'}
                </button>
              </div>
            </article>
          )
        })}
      </div>
    </div>
  )
}

function PaymentsPage({ rows, mutate }: { rows: Record<string, unknown>[]; mutate: Mutate }) {
  const keys = useMemo(() => ['order_id', 'telegram_id', 'amount_rub', 'credits', 'status', 'provider', 'payment_id', 'promo_code', 'created_at'], [])
  const completed = rows.filter((row) => row.status === 'completed')
  const pending = rows.filter((row) => row.status === 'pending')
  const cancelled = rows.filter((row) => ['cancelled', 'failed'].includes(String(row.status)))
  const completedRevenue = completed.reduce((sum, row) => sum + Number(row.amount_rub || 0), 0)
  return (
    <div className="stack">
      <div className="metrics">
        <Metric label="Оплачено" value={fmtNum(completed.length)} />
        <Metric label="Выручка" value={fmtMoney(completedRevenue)} />
        <Metric label="Ожидает" value={fmtNum(pending.length)} />
        <Metric label="Ошибки/отмены" value={fmtNum(cancelled.length)} />
        <Metric label="Всего счетов" value={fmtNum(rows.length)} />
      </div>
      <section className="panel">
        <div className="panel-title"><h2>Оплаты</h2><span>все счета: {rows.length}</span></div>
        <div className="table-wrap">
          <table>
            <thead><tr>{keys.map((key) => <th key={key}>{fieldLabel(key)}</th>)}<th>Действия</th></tr></thead>
            <tbody>
              {rows.map((row, index) => {
                const canCheckProvider = ['tbank', 'tbank_recurring'].includes(String(row.provider))
                return (
                  <tr key={String(row.order_id || index)}>
                    {keys.map((key) => <td key={key}>{displayValue(row[key])}</td>)}
                    <td>
                      <div className="table-actions">
                        {canCheckProvider ? (
                          <button onClick={() => mutate(() => postAction(`/api/tma/admin/payments/${row.order_id}/action`, { action: 'check_provider' }), 'Статус проверен')}>Проверить TBank</button>
                        ) : null}
                        <button onClick={() => mutate(() => postAction(`/api/tma/admin/payments/${row.order_id}/action`, { action: 'mark_completed' }), 'Оплата закрыта')}>Оплачено</button>
                        <button onClick={() => mutate(() => postAction(`/api/tma/admin/payments/${row.order_id}/action`, { action: 'mark_failed' }), 'Оплата отклонена')}>Ошибка</button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function SubscriptionsPage({ data, mutate }: { data: ApiState; mutate: Mutate }) {
  return (
    <div className="stack">
      <section className="two-col">
        <MiniList title="Активные подписки" rows={data.subscriptions} fields={['telegram_id', 'package_id', 'status', 'expires_at', 'images_used', 'videos_used']} />
        <MiniList title="Автосписания" rows={data.recurring} fields={['telegram_id', 'status', 'next_charge_at', 'last_order_id', 'last_error']} />
      </section>
      <div className="cards">
        {data.recurring.map((row) => (
          <article className="row-card" key={String(row.telegram_id)}>
            <div>
              <strong>{String(row.username ? `@${row.username}` : row.telegram_id)}</strong>
              <span>{displayValue(row.status)} · следующее {String(row.next_charge_at || '-')} · {String(row.rebill_id || '-')}</span>
            </div>
            <button onClick={() => mutate(() => postAction(`/api/tma/admin/recurring/${row.telegram_id}/action`, { action: 'disable' }), 'Автосписание отключено')}>
              Отключить
            </button>
          </article>
        ))}
      </div>
    </div>
  )
}

function GenerationsPage({ rows, mutate }: { rows: Record<string, unknown>[]; mutate: Mutate }) {
  return (
    <div className="cards">
      {rows.map((row) => (
        <article className="row-card" key={String(row.task_id)}>
          <div>
            <strong>{String(row.model || row.preset_id || displayValue(row.type))}</strong>
            <span>{String(row.task_id)} · {displayValue(row.status)} · {fmtNum(row.cost)} Бумкоины</span>
          </div>
          <div className="inline-actions">
            {row.result_url ? <a href={String(row.result_url)} target="_blank">Открыть</a> : null}
            <button onClick={() => mutate(() => postAction(`/api/tma/admin/generations/${row.task_id}/action`, { action: 'refund' }), 'Ресурс возвращен')}>Вернуть ресурс</button>
            <button onClick={() => mutate(() => postAction(`/api/tma/admin/generations/${row.task_id}/action`, { action: 'fail' }), 'Задача помечена ошибкой')}>Ошибка</button>
            <button onClick={() => mutate(() => postAction(`/api/tma/admin/generations/${row.task_id}/action`, { action: 'publish_feed' }), 'Добавлено в ленту')}>В ленту</button>
          </div>
        </article>
      ))}
    </div>
  )
}

function FeedPage({ rows, mutate }: { rows: Record<string, unknown>[]; mutate: Mutate }) {
  return (
    <div className="feed-grid">
      {rows.map((row) => (
        <article className="feed-card" key={String(row.task_id)}>
          <FeedPreview url={row.result_url} />
          <FeedAuthor row={row} />
          <strong>{String(row.model || row.preset_id || 'feed')}</strong>
          <p>{String(row.prompt || '').slice(0, 220)}</p>
          <span>{fmtNum(row.likes_count)} лайков · {fmtNum(row.shares_count)} повторов</span>
          <div className="inline-actions">
            <button onClick={() => mutate(() => postAction(`/api/tma/admin/feed/${row.task_id}/action`, { action: 'like' }), 'Лайк добавлен')}>Нравится</button>
            <button onClick={() => mutate(() => postAction(`/api/tma/admin/feed/${row.task_id}/action`, { action: 'share' }), 'Счётчик обновлен')}>+ повтор</button>
            <button className="danger-button" onClick={() => mutate(() => postAction(`/api/tma/admin/feed/${row.task_id}/action`, { action: 'remove' }), 'Публикация скрыта')}>Скрыть</button>
          </div>
        </article>
      ))}
    </div>
  )
}

function PackagesPage({ rows, mutate }: { rows: Record<string, unknown>[]; mutate: Mutate }) {
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({})
  const [newPackage, setNewPackage] = useState({
    id: '',
    name: '',
    kind: 'credits',
    period: '',
    price_rub: '990',
    credits: '0',
    bonus_credits: '0',
    subscription_days: '30',
    image_limit: '0',
    video_limit: '0',
  })
  const setDraft = (id: string, field: string, value: string) => {
    setDrafts({ ...drafts, [id]: { ...(drafts[id] || {}), [field]: value } })
  }
  const setNew = (field: string, value: string) => setNewPackage({ ...newPackage, [field]: value })
  const save = (id: string, field: string, value: unknown) =>
    mutate(() => postAction(`/api/tma/admin/packages/${id}`, { field, value }), 'Пакет обновлен')

  return (
    <div className="stack">
      <section className="panel admin-help">
        <div className="panel-title"><h2>Как редактировать пакеты</h2><span>для админа</span></div>
        <p>Меняйте поля и нажимайте <b>Сохранить</b> в нужной строке. Изменения сразу попадут в оплату мини-приложения и бота.</p>
        <p><b>Бумкоины</b> начисляются на баланс. <b>Лимиты фото/видео</b> тратятся внутри подписки. Чтобы не давать и бумкоины, и лимиты одновременно, оставьте ненужное поле равным 0.</p>
        <p><b>PRO включен</b> разрешает PRO-нейронки по подписке. Если выключено, PRO остается только за Бумкоины.</p>
      </section>
      <section className="panel">
        <div className="panel-title"><h2>Добавить пакет</h2><span>сразу появится в оплате</span></div>
        <div className="package-form-grid">
          <label><span>Код пакета</span><input placeholder="video_pack" value={newPackage.id} onChange={(e) => setNew('id', e.target.value)} /><small>{packageFieldHelpText('id')}</small></label>
          <label><span>Название</span><input placeholder="Пакет для видео" value={newPackage.name} onChange={(e) => setNew('name', e.target.value)} /><small>{packageFieldHelpText('name')}</small></label>
          <label><span>Тип пакета</span><select value={newPackage.kind} onChange={(e) => setNew('kind', e.target.value)}>
              <option value="credits">Бумкоины</option>
              <option value="subscription">Подписка</option>
            </select><small>{packageFieldHelpText('kind')}</small></label>
          <label><span>Период</span><input placeholder="месяц" value={newPackage.period} onChange={(e) => setNew('period', e.target.value)} /><small>{packageFieldHelpText('period')}</small></label>
          <label><span>Цена, ₽</span><input placeholder="990" value={newPackage.price_rub} onChange={(e) => setNew('price_rub', e.target.value)} /><small>{packageFieldHelpText('price_rub')}</small></label>
          <label><span>Бумкоины</span><input placeholder="0" value={newPackage.credits} onChange={(e) => setNew('credits', e.target.value)} /><small>{packageFieldHelpText('credits')}</small></label>
          <label><span>Бонус</span><input placeholder="0" value={newPackage.bonus_credits} onChange={(e) => setNew('bonus_credits', e.target.value)} /><small>{packageFieldHelpText('bonus_credits')}</small></label>
          <label><span>Дней подписки</span><input placeholder="30" value={newPackage.subscription_days} onChange={(e) => setNew('subscription_days', e.target.value)} /><small>{packageFieldHelpText('subscription_days')}</small></label>
          <label><span>Лимит фото</span><input placeholder="0" value={newPackage.image_limit} onChange={(e) => setNew('image_limit', e.target.value)} /><small>{packageFieldHelpText('image_limit')}</small></label>
          <label><span>Лимит видео</span><input placeholder="0" value={newPackage.video_limit} onChange={(e) => setNew('video_limit', e.target.value)} /><small>{packageFieldHelpText('video_limit')}</small></label>
          <button onClick={() => mutate(() => postAction('/api/tma/admin/packages', {
            ...newPackage,
            price_rub: Number(newPackage.price_rub || 0),
            credits: Number(newPackage.credits || 0),
            bonus_credits: Number(newPackage.bonus_credits || 0),
            subscription_days: Number(newPackage.subscription_days || 0),
            image_limit: Number(newPackage.image_limit || 0),
            video_limit: Number(newPackage.video_limit || 0),
          }), 'Пакет создан')}>Создать</button>
        </div>
      </section>
      <div className="cards packages">
        {rows.map((pkg) => {
          const id = String(pkg.id)
          return (
            <article className="edit-card" key={id}>
              <div className="panel-title">
                <h2>{String(pkg.name)}</h2>
                <span>{id}</span>
              </div>
              {['name', 'kind', 'period'].map((field) => (
                <label className="field" key={field}>
                <span>{fieldLabel(field)}</span>
                <small>{packageFieldHelpText(field)}</small>
                {field === 'kind' ? (
                  <select value={drafts[id]?.[field] ?? String(pkg[field] ?? 'credits')} onChange={(event) => setDraft(id, field, event.target.value)}>
                    <option value="credits">Бумкоины</option>
                      <option value="subscription">Подписка</option>
                    </select>
                  ) : (
                    <input value={drafts[id]?.[field] ?? String(pkg[field] ?? '')} onChange={(event) => setDraft(id, field, event.target.value)} />
                  )}
                  <button onClick={() => save(id, field, drafts[id]?.[field] ?? pkg[field] ?? '')}>Сохранить</button>
                </label>
              ))}
              {['price_rub', 'credits', 'bonus_credits', 'subscription_days', 'image_limit', 'video_limit', 'discount_percent'].map((field) => (
                <label className="field" key={field}>
                  <span>{fieldLabel(field)}</span>
                  <small>{packageFieldHelpText(field)}</small>
                  <input value={drafts[id]?.[field] ?? String(pkg[field] ?? 0)} onChange={(event) => setDraft(id, field, event.target.value)} />
                  <button onClick={() => save(id, field, Number(drafts[id]?.[field] ?? pkg[field] ?? 0))}>Сохранить</button>
                </label>
              ))}
              <div className="inline-actions">
                {['popular', 'hidden', 'includes_pro', 'priority'].map((field) => (
                  <button key={field} onClick={() => save(id, field, !pkg[field])}>
                    {fieldLabel(field)}: {boolText(pkg[field])}
                  </button>
                ))}
              </div>
            </article>
          )
        })}
      </div>
    </div>
  )
}

function PromosPage({ data, mutate }: { data: ApiState; mutate: Mutate }) {
  const [form, setForm] = useState({ code: '', promo_type: 'discount', discount_percent: '10', reward_credits: '0', max_uses: '10', expires_days: '' })
  const set = (key: string, value: string) => setForm({ ...form, [key]: value })
  return (
    <div className="stack">
      <section className="panel form-grid">
        <input placeholder="Промокод" value={form.code} onChange={(e) => set('code', e.target.value)} />
        <select value={form.promo_type} onChange={(e) => set('promo_type', e.target.value)}>
          <option value="discount">скидка</option>
          <option value="bananas">Бумкоины</option>
          <option value="generation">генерации</option>
        </select>
        <input placeholder="скидка %" value={form.discount_percent} onChange={(e) => set('discount_percent', e.target.value)} />
        <input placeholder="награда" value={form.reward_credits} onChange={(e) => set('reward_credits', e.target.value)} />
        <input placeholder="лимит" value={form.max_uses} onChange={(e) => set('max_uses', e.target.value)} />
        <input placeholder="дней" value={form.expires_days} onChange={(e) => set('expires_days', e.target.value)} />
        <button onClick={() => mutate(() => postAction('/api/tma/admin/promos', form), 'Промокод создан')}>Создать</button>
      </section>
      <div className="cards">
        {data.promos.map((promo) => (
          <article className="row-card" key={String(promo.code)}>
            <div>
              <strong>{String(promo.code)}</strong>
              <span>{displayValue(promo.promo_type)} · {fmtNum(promo.used_count)}/{fmtNum(promo.max_uses)} · активен: {boolText(promo.is_active)}</span>
            </div>
            {promo.is_active ? <button onClick={() => mutate(() => postAction(`/api/tma/admin/promos/${promo.code}`, { action: 'deactivate' }), 'Промо отключен')}>Отключить</button> : <span />}
          </article>
        ))}
      </div>
    </div>
  )
}

function PartnersPage({ data, mutate }: { data: ApiState; mutate: Mutate }) {
  const config = data.referrals.config || {}
  const [query, setQuery] = useState('')
  const [partnerRows, setPartnerRows] = useState(data.partners)
  const [refConfig, setRefConfig] = useState({
    referrer_bonus_credits: String(config.referrer_bonus_credits ?? 30),
    friend_bonus_credits: String(config.friend_bonus_credits ?? 30),
    bonus_trigger: String(config.bonus_trigger ?? 'first_payment'),
    daily_referral_limit: String(config.daily_referral_limit ?? 20),
  })
  useEffect(() => setPartnerRows(data.partners), [data.partners])
  const setRef = (field: string, value: string) => setRefConfig({ ...refConfig, [field]: value })
  const searchPartners = async () => {
    const result = await api<{ partners: Record<string, unknown>[] }>(`/api/tma/admin/partners?search=${encodeURIComponent(query)}&limit=120`)
    setPartnerRows(result.partners)
  }
  const saveRefConfig = () =>
    mutate(
      () =>
        postAction('/api/tma/admin/referrals', {
          config: {
            referrer_bonus_credits: Number(refConfig.referrer_bonus_credits || 0),
            friend_bonus_credits: Number(refConfig.friend_bonus_credits || 0),
            bonus_trigger: refConfig.bonus_trigger,
            daily_referral_limit: Number(refConfig.daily_referral_limit || 0),
          },
        }),
      'Настройки рефералки сохранены',
    )
  const updatePayout = (id: unknown, status: string) =>
    mutate(() => postAction(`/api/tma/admin/payouts/${id}`, { status }), 'Выплата обновлена')
  const updateWithdrawal = (id: unknown, status: string) =>
    mutate(() => postAction(`/api/tma/admin/withdrawals/${id}`, { status }), 'Заявка обновлена')

  return (
    <div className="stack">
      <div className="metrics">
        <Metric label="Партнеры" value={fmtNum(partnerRows.length)} />
        <Metric label="Заявки выплат" value={fmtNum(data.referrals.payouts.length)} />
        <Metric label="Выводы" value={fmtNum(data.withdrawals.length)} />
        <Metric label="Антифрод" value={fmtNum((data.referrals.config.antifraud_rules as unknown[] | undefined)?.length || 0)} />
      </div>
      <form className="search" onSubmit={(event) => { event.preventDefault(); searchPartners() }}>
        <Search size={16} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="ID, ник, имя или промокод" />
        <button type="submit">Найти</button>
      </form>
      <MiniList title="Партнерская сводка" rows={partnerRows} fields={['telegram_id', 'username', 'users_count', 'payments_count', 'revenue_rub', 'commission_rub', 'balance_rub']} />
      <section className="panel">
        <div className="panel-title"><h2>Настройки рефералки</h2><span>начисления</span></div>
        <div className="package-form-grid">
          <label>
            <span>{fieldLabel('referrer_bonus_credits')}</span>
            <input value={refConfig.referrer_bonus_credits} onChange={(event) => setRef('referrer_bonus_credits', event.target.value)} inputMode="numeric" />
            <small>Сколько Бумкоинов получает пригласивший.</small>
          </label>
          <label>
            <span>{fieldLabel('friend_bonus_credits')}</span>
            <input value={refConfig.friend_bonus_credits} onChange={(event) => setRef('friend_bonus_credits', event.target.value)} inputMode="numeric" />
            <small>Сколько Бумкоинов получает новый пользователь.</small>
          </label>
          <label>
            <span>{fieldLabel('bonus_trigger')}</span>
            <select value={refConfig.bonus_trigger} onChange={(event) => setRef('bonus_trigger', event.target.value)}>
              <option value="first_payment">После первой оплаты</option>
              <option value="signup">При регистрации</option>
            </select>
            <small>Рекомендуется первая оплата, чтобы не раздавать бонусы пустым регистрациям.</small>
          </label>
          <label>
            <span>{fieldLabel('daily_referral_limit')}</span>
            <input value={refConfig.daily_referral_limit} onChange={(event) => setRef('daily_referral_limit', event.target.value)} inputMode="numeric" />
            <small>Ограничение на количество засчитанных приглашений в сутки.</small>
          </label>
          <button onClick={saveRefConfig}>Сохранить настройки рефералки</button>
        </div>
      </section>
      <section className="two-col">
        <ActionList title="Выплаты" rows={data.referrals.payouts} fields={['id', 'partner', 'amount_rub', 'status', 'comment']} actions={(row) => (
          <>
            <button onClick={() => updatePayout(row.id, 'paid')}>Выплачено</button>
            <button onClick={() => updatePayout(row.id, 'frozen')}>Заморозить</button>
          </>
        )} />
        <ActionList title="Заявки на вывод" rows={data.withdrawals} fields={['id', 'telegram_id', 'amount_rub', 'status', 'created_at']} actions={(row) => (
          <>
            <button onClick={() => updateWithdrawal(row.id, 'completed')}>Готово</button>
            <button onClick={() => updateWithdrawal(row.id, 'failed')}>Ошибка</button>
          </>
        )} />
      </section>
    </div>
  )
}

function AutomationPage({ data, mutate }: { data: ApiState; mutate: Mutate }) {
  const config = data.push.config
  const rules = (config.rules as Record<string, unknown>[] | undefined) || []
  const [broadcast, setBroadcast] = useState({ message: '', limit: String(data.limits.production_limit || 500) })
  return (
    <div className="stack">
      <section className="panel broadcast-box">
        <div className="panel-title">
          <h2>Рассылка из приложения</h2>
          <span>лимит {fmtNum(broadcast.limit)}</span>
        </div>
        <textarea value={broadcast.message} onChange={(event) => setBroadcast({ ...broadcast, message: event.target.value })} placeholder="HTML-текст сообщения" />
        <div className="inline-actions">
          <input value={broadcast.limit} onChange={(event) => setBroadcast({ ...broadcast, limit: event.target.value })} inputMode="numeric" />
          <button onClick={() => mutate(() => postAction('/api/tma/admin/broadcast', { text: broadcast.message, limit: Number(broadcast.limit || 0) }), 'Рассылка запущена')}>
            <Megaphone size={16} /> Отправить
          </button>
        </div>
      </section>
      <section className="panel">
        <div className="panel-title">
          <h2>Пуш-сценарии</h2>
          <button onClick={() => mutate(() => postAction('/api/tma/admin/push', { enabled: !config.enabled }), 'Пуш обновлен')}>
            Общий статус: {boolText(config.enabled)}
          </button>
        </div>
        <div className="cards">
          {rules.map((rule) => (
            <article className="row-card" key={String(rule.key)}>
              <div>
                <strong>{String(rule.title)}</strong>
                <span>{String(rule.key)} · задержка {fmtNum(rule.delay_seconds)} сек · {boolText(rule.enabled)}</span>
              </div>
              <div className="inline-actions">
                <button onClick={() => mutate(() => postAction('/api/tma/admin/push', { rules: [{ key: rule.key, enabled: !rule.enabled }] }), 'Правило обновлено')}>
                  {rule.enabled ? 'Выключить' : 'Включить'}
                </button>
                <button onClick={() => {
                  const seconds = window.prompt('Задержка в секундах', String(rule.delay_seconds || 0))
                  if (seconds !== null) {
                    mutate(() => postAction('/api/tma/admin/push', { rules: [{ key: rule.key, delay_seconds: Number(seconds) }] }), 'Задержка обновлена')
                  }
                }}>
                  Задержка
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>
      <MiniList title="События к отправке" rows={data.push.due_events} fields={['telegram_id', 'scenario_key', 'title', 'due_at']} />
    </div>
  )
}

function SystemPage({ data, mutate }: { data: ApiState; mutate: Mutate }) {
  const systemRows = Object.entries(data.system).map(([key, value]) => ({ key, value }))
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-title">
          <h2>Система</h2>
          <button onClick={() => mutate(() => postAction('/api/tma/admin/settings', { maintenance: !data.dashboard.maintenance }), 'Техрежим обновлен')}>
            Техрежим: {boolText(data.dashboard.maintenance)}
          </button>
        </div>
      </section>
      <MiniList title="Лимиты продакшена" rows={Object.entries(data.limits).map(([key, value]) => ({ key, value }))} fields={['key', 'value']} />
      <MiniList title="Конфигурация" rows={systemRows} fields={['key', 'value']} />
    </div>
  )
}

function ActionList({
  title,
  rows,
  fields,
  actions,
}: {
  title: string
  rows: Record<string, unknown>[]
  fields: string[]
  actions: (row: Record<string, unknown>) => ReactNode
}) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>{title}</h2><span>{rows.length}</span></div>
      <div className="cards">
        {rows.length ? rows.map((row, index) => (
          <article className="row-card" key={String(row.id || index)}>
            <div>
              <strong>{String(row.id || row.telegram_id || index)}</strong>
              <span>{fields.map((field) => `${fieldLabel(field)}: ${displayValue(row[field])}`).join(' · ')}</span>
            </div>
            <div className="inline-actions">{actions(row)}</div>
          </article>
        )) : <p className="muted-line">Нет данных</p>}
      </div>
    </section>
  )
}

function MiniList({ title, rows, fields }: { title: string; rows: Record<string, unknown>[]; fields: string[] }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>{title}</h2><span>{rows.length}</span></div>
      <div className="mini-list">
        {rows.length ? rows.map((row, index) => (
          <div key={index}>
            {fields.map((field) => <span key={field}><b>{fieldLabel(field)}</b>: {displayValue(row[field])}</span>)}
          </div>
        )) : <p className="muted-line">Нет данных</p>}
      </div>
    </section>
  )
}
