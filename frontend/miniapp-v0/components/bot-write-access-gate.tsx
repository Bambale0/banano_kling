'use client'

import { useCallback, useEffect, useState } from 'react'
import { ExternalLink, LoaderCircle, MessageCircle } from 'lucide-react'

import { confirmTelegramWriteAccess } from '@/lib/api'

interface BotWriteAccessGateProps {
  required: boolean
  botUsername?: string
  onRefresh: () => Promise<void> | void
}

type GatePhase = 'idle' | 'requesting' | 'declined' | 'open-bot' | 'error'

function botStartUrl(botUsername?: string) {
  const username = String(botUsername || '').trim().replace(/^@/, '')
  return username ? `https://t.me/${username}?start=miniapp_delivery` : ''
}

export function BotWriteAccessGate({
  required,
  botUsername,
  onRefresh,
}: BotWriteAccessGateProps) {
  const [phase, setPhase] = useState<GatePhase>('idle')

  const openBot = useCallback(() => {
    if (typeof window === 'undefined') return
    const url = botStartUrl(botUsername)
    if (!url) {
      setPhase('error')
      return
    }
    setPhase('open-bot')
    const webApp = window.Telegram?.WebApp
    if (webApp?.openTelegramLink) {
      webApp.openTelegramLink(url)
      return
    }
    window.open(url, '_blank', 'noopener,noreferrer')
  }, [botUsername])

  const confirmNativeGrant = useCallback(async () => {
    try {
      const result = await confirmTelegramWriteAccess()
      if (!result.chat_available || result.needs_bot_start) {
        openBot()
        return
      }
      await onRefresh()
      setPhase('idle')
    } catch {
      setPhase('error')
    }
  }, [onRefresh, openBot])

  const requestAccess = useCallback(() => {
    if (typeof window === 'undefined' || phase === 'requesting') return
    const webApp = window.Telegram?.WebApp
    const requestWriteAccess = webApp?.requestWriteAccess
    if (!requestWriteAccess) {
      openBot()
      return
    }

    setPhase('requesting')
    try {
      requestWriteAccess((allowed) => {
        if (!allowed) {
          setPhase('declined')
          return
        }
        void confirmNativeGrant()
      })
    } catch {
      openBot()
    }
  }, [confirmNativeGrant, openBot, phase])

  useEffect(() => {
    if (!required || phase !== 'open-bot' || typeof window === 'undefined') return

    let refreshing = false
    const refreshAfterBot = () => {
      if (refreshing || document.visibilityState === 'hidden') return
      refreshing = true
      Promise.resolve(onRefresh()).finally(() => {
        refreshing = false
      })
    }
    const webApp = window.Telegram?.WebApp as
      | ({ onEvent?: (event: string, handler: () => void) => void; offEvent?: (event: string, handler: () => void) => void })
      | undefined

    window.addEventListener('focus', refreshAfterBot)
    document.addEventListener('visibilitychange', refreshAfterBot)
    webApp?.onEvent?.('activated', refreshAfterBot)
    return () => {
      window.removeEventListener('focus', refreshAfterBot)
      document.removeEventListener('visibilitychange', refreshAfterBot)
      webApp?.offEvent?.('activated', refreshAfterBot)
    }
  }, [onRefresh, phase, required])

  if (!required) return null

  const helperText =
    phase === 'open-bot'
      ? 'В чате нажми Start, затем вернись сюда — доступ проверится автоматически.'
      : phase === 'declined'
        ? 'Telegram не дал доступ. Попробуй ещё раз или открой чат с ботом.'
        : phase === 'error'
          ? 'Не удалось подтвердить доступ. Попробуй ещё раз или открой чат с ботом.'
          : null

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 px-5 backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-labelledby="bot-write-access-title"
    >
      <section className="w-full max-w-sm rounded-[28px] border border-white/10 bg-[#1d1d1f]/95 p-7 text-center shadow-2xl shadow-black/60">
        <div className="mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-full bg-white/95 text-[#333] shadow-lg shadow-black/20">
          <MessageCircle className="h-10 w-10 fill-current" />
        </div>

        <h2 id="bot-write-access-title" className="text-2xl font-semibold leading-tight text-white">
          Разреши боту писать тебе
        </h2>
        <p className="mt-5 text-[17px] leading-7 text-white/55">
          Так готовые фото и видео будут приходить прямо в чат с ботом — в максимальном качестве.
          Результат также останется в Студии.
        </p>

        {helperText ? (
          <p className="mt-4 rounded-2xl bg-white/[0.05] px-4 py-3 text-sm leading-5 text-white/65">
            {helperText}
          </p>
        ) : null}

        <button
          type="button"
          onClick={requestAccess}
          disabled={phase === 'requesting'}
          className="mt-7 flex h-14 w-full items-center justify-center gap-2 rounded-2xl bg-gold px-5 text-lg font-semibold text-black transition active:scale-[0.99] disabled:opacity-70"
        >
          {phase === 'requesting' ? <LoaderCircle className="h-5 w-5 animate-spin" /> : null}
          {phase === 'requesting' ? 'Проверяем…' : 'Разрешить'}
        </button>

        {(phase === 'declined' || phase === 'error' || phase === 'open-bot') && botStartUrl(botUsername) ? (
          <button
            type="button"
            onClick={openBot}
            className="mt-3 flex h-11 w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-medium text-white/75"
          >
            <ExternalLink className="h-4 w-4" />
            Открыть бота
          </button>
        ) : null}
      </section>
    </div>
  )
}
