'use client'

import { useEffect, useState } from 'react'
import { ExternalLink, RefreshCw, Send } from 'lucide-react'
import { buildTelegramMiniAppUrl, getStartParamFallback } from '@/lib/api'
import { useApp } from '@/lib/app-context'
import { Button } from '@/components/ui/button'

export function TelegramOpenGate() {
  const { state, refreshTasks } = useApp()
  const [telegramUrl, setTelegramUrl] = useState('')

  useEffect(() => {
    setTelegramUrl(buildTelegramMiniAppUrl(getStartParamFallback()))
  }, [])

  return (
    <main className="relative flex min-h-svh items-center justify-center px-5 py-10">
      <div className="w-full max-w-sm space-y-5 rounded-2xl border border-border/60 bg-card/70 p-5 shadow-2xl shadow-background/40 backdrop-blur">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-gold/30 bg-gold/10 text-gold">
          <Send className="h-5 w-5" />
        </div>
        <div className="space-y-2">
          <h1 className="text-xl font-semibold text-foreground">Откройте Mini App в Telegram</h1>
          <p className="text-sm leading-6 text-muted-foreground">
            Здесь нет демо-генераций. Задачи, баланс, история и ссылки работают только внутри Telegram Mini App.
          </p>
          {state.error ? (
            <p className="text-sm leading-6 text-destructive">{state.error}</p>
          ) : null}
        </div>

        <div className="grid gap-2">
          {telegramUrl ? (
            <Button asChild className="h-11 rounded-lg">
              <a href={telegramUrl} target="_blank" rel="noreferrer">
                <ExternalLink className="h-4 w-4" />
                Открыть в Telegram
              </a>
            </Button>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            className="h-11 rounded-lg"
            disabled={state.isLoading}
            onClick={refreshTasks}
          >
            <RefreshCw className={state.isLoading ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
            Проверить Telegram
          </Button>
        </div>
      </div>
    </main>
  )
}
