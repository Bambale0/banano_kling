'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { ExternalLink, LoaderCircle, MessageCircle } from 'lucide-react'

import { getStartParamFallback } from '@/lib/api'
import { parseMiniAppStartParam } from '@/lib/start-params'

interface BotWriteAccessGateProps {
  required: boolean
  botUsername?: string
  onRefresh: (signal: AbortSignal) => Promise<boolean>
}

type GatePhase = 'idle' | 'open-bot' | 'checking' | 'not-started' | 'error'
const RETURN_CHECK_TIMEOUT_MS = 12_000
const DISMISS_STORAGE_KEY = 'neuromix_bot_delivery_offer_dismissed'

function botStartUrl(botUsername?: string) {
  const username = String(botUsername || '').trim().replace(/^@/, '')
  if (!/^[a-zA-Z0-9_]{5,32}$/.test(username)) return ''
  // Retain a direct referral; never replay payment/generation actions in /start.
  // The original Mini App launch context and form stay mounted in this WebView.
  const launch = getStartParamFallback().trim().replace(/^start=/, '').replace(/^startapp=/, '')
  const target = parseMiniAppStartParam(launch)
  const referral = launch.startsWith('ref_')
    ? launch.slice(4).trim().toUpperCase()
    : target && 'referralCodeForAttribution' in target && target.kind !== 'genjutsu_recipe'
      ? target.referralCodeForAttribution || ''
      : ''
  const start = /^[A-Z0-9_-]{1,60}$/.test(referral) ? `ref_${referral}` : 'miniapp_delivery'
  return `https://t.me/${username}?start=${encodeURIComponent(start)}`
}

export function BotWriteAccessGate({ required, botUsername, onRefresh }: BotWriteAccessGateProps) {
  const [phase, setPhase] = useState<GatePhase>('idle')
  const [dismissed, setDismissed] = useState(() => {
    try { return typeof window !== 'undefined' && window.sessionStorage.getItem(DISMISS_STORAGE_KEY) === '1' } catch { return false }
  })
  const openedBot = useRef(false)
  const attempt = useRef(0)
  const pending = useRef<{ controller: AbortController; timer: ReturnType<typeof setTimeout> } | null>(null)

  const cancelCheck = useCallback(() => {
    attempt.current += 1
    if (pending.current) {
      clearTimeout(pending.current.timer)
      pending.current.controller.abort()
      pending.current = null
    }
  }, [])

  const checkAccess = useCallback(async () => {
    if (!required || pending.current) return
    const id = ++attempt.current
    const controller = new AbortController()
    setPhase('checking')
    const timer = setTimeout(() => {
      if (id !== attempt.current) return
      cancelCheck()
      console.warn('Mini App bot-start check timed out')
      setPhase('error')
    }, RETURN_CHECK_TIMEOUT_MS)
    pending.current = { controller, timer }
    try {
      const available = await onRefresh(controller.signal)
      if (id !== attempt.current || controller.signal.aborted) return
      setPhase(available ? 'idle' : 'not-started')
    } catch {
      if (id !== attempt.current || controller.signal.aborted) return
      setPhase('error')
    } finally {
      if (id === attempt.current) {
        clearTimeout(timer)
        pending.current = null
      }
    }
  }, [cancelCheck, onRefresh, required])

  const openBot = useCallback(() => {
    cancelCheck()
    const url = botStartUrl(botUsername)
    if (!url) {
      setPhase('error')
      return
    }
    openedBot.current = true
    setPhase('open-bot')
    try {
      const webApp = window.Telegram?.WebApp
      if (webApp?.openTelegramLink) webApp.openTelegramLink(url)
      else window.open(url, '_blank', 'noopener,noreferrer')
    } catch {
      setPhase('error')
    }
  }, [botUsername, cancelCheck])

  useEffect(() => {
    if (!required) {
      openedBot.current = false
      setPhase('idle')
      return
    }
    const refreshAfterBot = () => {
      if (openedBot.current && document.visibilityState !== 'hidden') void checkAccess()
    }
    const webApp = window.Telegram?.WebApp as
      | { onEvent?: (event: string, handler: () => void) => void; offEvent?: (event: string, handler: () => void) => void }
      | undefined
    window.addEventListener('focus', refreshAfterBot)
    document.addEventListener('visibilitychange', refreshAfterBot)
    webApp?.onEvent?.('activated', refreshAfterBot)
    return () => {
      window.removeEventListener('focus', refreshAfterBot)
      document.removeEventListener('visibilitychange', refreshAfterBot)
      webApp?.offEvent?.('activated', refreshAfterBot)
      cancelCheck()
    }
  }, [cancelCheck, checkAccess, required])

  if (!required) return null

  const skipOffer = () => {
    cancelCheck()
    openedBot.current = false
    setPhase('idle')
    setDismissed(true)
    try { window.sessionStorage.setItem(DISMISS_STORAGE_KEY, '1') } catch {}
  }

  if (dismissed) return (
    <aside aria-label="Доставка результатов" className="relative mx-4 mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-white/60">
      <span>Результаты доступны в Студии</span>
      <button type="button" onClick={() => setDismissed(false)} className="min-h-11 rounded-lg px-3 text-sm font-medium text-gold">Получать в боте</button>
    </aside>
  )

  const helperText = phase === 'error'
    ? 'Не удалось проверить доступ. Открой чат с ботом или попробуй проверить снова.'
    : phase === 'not-started'
      ? 'Доступ пока не подтверждён. В чате нажми Start / «Начать», затем вернись и проверь снова.'
      : 'Открой чат, нажми Start / «Начать», затем вернись сюда.'

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center overflow-y-auto bg-black/70 px-5 py-6 backdrop-blur-md" role="dialog" aria-modal="true" aria-labelledby="bot-write-access-title">
      <section className="my-auto w-full max-w-sm rounded-[28px] border border-white/10 bg-[#1d1d1f]/95 p-7 text-center shadow-2xl shadow-black/60">
        <div className="mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-full bg-white/95 text-[#333] shadow-lg shadow-black/20">
          <MessageCircle className="h-10 w-10 fill-current" />
        </div>
        <h2 id="bot-write-access-title" className="text-2xl font-semibold leading-tight text-white">Разреши боту писать тебе</h2>
        <p className="mt-5 text-[17px] leading-7 text-white/55">
          Так готовые фото и видео будут приходить прямо в чат с ботом — в максимальном качестве.
          Можно пропустить: все результаты будут доступны в Студии.
        </p>
        <p role="status" className="mt-4 rounded-2xl bg-white/[0.05] px-4 py-3 text-sm leading-5 text-white/65">{helperText}</p>
        <button type="button" onClick={openBot} className="mt-7 flex min-h-14 w-full items-center justify-center gap-2 rounded-2xl bg-gold px-5 py-3 text-lg font-semibold text-black transition active:scale-[0.99]">
          <ExternalLink className="h-5 w-5 shrink-0" />
          Открыть бота
        </button>
        <button type="button" onClick={() => void checkAccess()} disabled={phase === 'checking'} className="mt-3 flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-sm font-medium text-white/75 disabled:opacity-70">
          {phase === 'checking' ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
          {phase === 'checking' ? 'Проверяем…' : 'Проверить снова'}
        </button>
        <button type="button" onClick={skipOffer} className="mt-2 min-h-11 w-full rounded-xl px-4 py-2 text-sm text-white/60 hover:text-white">Пропустить</button>
      </section>
    </div>
  )
}
