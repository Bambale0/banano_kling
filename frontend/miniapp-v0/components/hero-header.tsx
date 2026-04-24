'use client'

import { useApp } from '@/lib/app-context'
import { Banana, RefreshCw, Wifi } from 'lucide-react'
import { cn } from '@/lib/utils'

export function HeroHeader() {
  const { state, refreshTasks, openBalance } = useApp()
  const { user, mode, lastSync, isLoading } = state

  const formatTime = (date: Date | null) => {
    if (!date) return '—'
    return date.toLocaleTimeString('ru-RU', {
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <header className="sticky top-0 z-40 px-4 pt-3 pb-2 bg-background/80 backdrop-blur-xl">
      <div className="flex items-center justify-between gap-3 rounded-2xl border border-border/50 bg-card/55 px-3 py-2.5 shadow-lg shadow-background/30">
        <div className="inline-flex items-center gap-2 rounded-full border border-success/25 bg-success/10 px-3 py-1.5">
          <Wifi className="h-3.5 w-3.5 text-success" />
          <span className="text-xs font-semibold text-success">
            {mode === 'live' ? 'Онлайн' : 'Демо'}
          </span>
          <span className="h-1.5 w-1.5 rounded-full bg-success" />
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={refreshTasks}
            disabled={isLoading}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-xs text-muted-foreground',
              'transition-colors hover:bg-secondary/70 hover:text-foreground',
              'disabled:opacity-50'
            )}
          >
            <RefreshCw className={cn('h-3.5 w-3.5', isLoading && 'animate-spin')} />
            <span>{formatTime(lastSync)}</span>
          </button>

          <button
            onClick={openBalance}
            className="inline-flex items-center gap-2 rounded-full border border-gold/25 bg-gold/10 px-3 py-1.5 transition-colors hover:bg-gold/15"
          >
            <Banana className="h-4 w-4 text-gold" />
            <span className="text-sm font-bold text-gold">{user.credits}</span>
          </button>
        </div>
      </div>
    </header>
  )
}
