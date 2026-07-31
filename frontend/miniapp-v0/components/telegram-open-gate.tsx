'use client'

import { useEffect, useState } from 'react'
import { Send } from 'lucide-react'
import { buildTelegramMiniAppUrl, getStartParamFallback } from '@/lib/api'
import { useApp } from '@/lib/app-context'
import {
  buildTelegramBrowserLoginUrl,
  getTelegramBrowserAuthConfig,
  getTelegramBrowserAuthError,
} from '@/lib/telegram-browser-auth'
import { Button } from '@/components/ui/button'

function ConnectionLoader() {
  return (
    <main className="relative flex min-h-svh items-center justify-center px-5 py-10">
      <div className="w-full max-w-sm rounded-[2rem] border border-gold/20 bg-card/75 px-7 py-10 text-center shadow-2xl shadow-background/50 backdrop-blur-xl">
        <div className="relative mx-auto mb-7 flex h-24 w-24 items-center justify-center">
          <div className="absolute inset-0 rounded-full border border-gold/20" />
          <div className="absolute inset-2 animate-spin rounded-full border-2 border-transparent border-t-gold border-r-gold/40 shadow-[0_0_28px_rgba(245,180,57,0.18)]" />
          <div className="flex h-14 w-14 items-center justify-center rounded-full border border-gold/25 bg-gold/10 text-gold shadow-[inset_0_0_22px_rgba(245,180,57,0.08)]">
            <Send className="h-6 w-6 -rotate-6" />
          </div>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Подключаем <span className="text-gold">Mini App</span>
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">Загружаем данные…</p>
      </div>
    </main>
  )
}

export function TelegramOpenGate() {
  const { state } = useApp()
  const [browserLoginEnabled, setBrowserLoginEnabled] = useState(false)
  const [browserLoginUrl, setBrowserLoginUrl] = useState('')
  const [telegramUrl, setTelegramUrl] = useState('')
  const [authError, setAuthError] = useState('')

  useEffect(() => {
    setTelegramUrl(buildTelegramMiniAppUrl(getStartParamFallback()))
    setBrowserLoginUrl(buildTelegramBrowserLoginUrl())
    setAuthError(getTelegramBrowserAuthError())
    getTelegramBrowserAuthConfig()
      .then((authConfig) => setBrowserLoginEnabled(Boolean(authConfig.enabled)))
      .catch(() => setBrowserLoginEnabled(false))
  }, [])

  if (state.isLoading) {
    return <ConnectionLoader />
  }

  return (
    <main className="relative flex min-h-svh items-center justify-center px-5 py-10">
      <div className="w-full max-w-sm rounded-[2rem] border border-gold/20 bg-card/75 px-7 py-9 text-center shadow-2xl shadow-background/50 backdrop-blur-xl">
        <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-full border border-gold/25 bg-gold/10 text-gold shadow-[0_0_32px_rgba(245,180,57,0.12)]">
          <Send className="h-7 w-7 -rotate-6" />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Войти в Mini App</h1>
        <p className="mt-2 text-sm text-muted-foreground">Продолжите через Telegram</p>
        {authError ? <p className="mt-4 text-sm text-destructive">{authError}</p> : null}

        <div className="mt-7 grid gap-3">
          {browserLoginEnabled && browserLoginUrl ? (
            <Button asChild className="h-12 rounded-xl text-base">
              <a href={browserLoginUrl}>
                <Send className="h-4 w-4" />
                Войти через Telegram
              </a>
            </Button>
          ) : null}
          {telegramUrl ? (
            <Button
              asChild
              variant={browserLoginEnabled ? 'secondary' : 'default'}
              className="h-12 rounded-xl"
            >
              <a href={telegramUrl} target="_blank" rel="noreferrer">
                Открыть в Telegram
              </a>
            </Button>
          ) : null}
        </div>
      </div>
    </main>
  )
}
