'use client'

import { useApp } from '@/lib/app-context'
import { ModeBadge } from './mode-badge'
import { Banana, Sparkles, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'

export function HeroHeader() {
  const { state, refreshTasks, openBalance, setActiveTab } = useApp()
  const { user, mode, lastSync, isLoading, error } = state

  const formatTime = (date: Date | null) => {
    if (!date) return '—'
    return date.toLocaleTimeString('ru-RU', { 
      hour: '2-digit', 
      minute: '2-digit' 
    })
  }

  return (
    <header className="relative px-4 pt-3 pb-3">
      <div className="glass rounded-2xl border border-border/50 px-4 py-4">
        <div className="flex items-center justify-between">
          <ModeBadge mode={mode} />
          <button
            onClick={refreshTasks}
            disabled={isLoading}
            className={cn(
              "flex items-center gap-1.5 text-xs text-muted-foreground",
              "hover:text-foreground transition-colors",
              "disabled:opacity-50"
            )}
          >
            <RefreshCw className={cn("w-3.5 h-3.5", isLoading && "animate-spin")} />
            <span>{formatTime(lastSync)}</span>
          </button>
        </div>

        <div className="mt-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-gold to-gold-muted">
                <Sparkles className="w-4 h-4 text-primary-foreground" />
              </div>
              <h1 className="truncate font-serif text-[2rem] leading-none font-semibold tracking-tight text-foreground">
                Banano AI Studio
              </h1>
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              Фото и видео генерация в одном окне
            </p>
          </div>

          <button
            onClick={openBalance}
            className="flex shrink-0 items-center gap-2 rounded-full border border-gold/20 bg-gold/10 px-3 py-2 transition-colors hover:bg-gold/15"
          >
            <Banana className="w-4 h-4 text-gold" />
            <span className="text-sm font-semibold text-gold">{user.credits}</span>
          </button>
        </div>

        <div className="mt-3 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-secondary">
              <span className="text-sm font-medium text-secondary-foreground">
                {user.firstName.charAt(0).toUpperCase()}
              </span>
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">{user.firstName}</p>
              <p className="text-xs text-muted-foreground">
                {mode === 'demo' ? 'Режим просмотра' : 'Готово к запуску'}
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <QuickPill icon="📸" label="Фото" onClick={() => setActiveTab(1)} />
            <QuickPill icon="🎬" label="Видео" onClick={() => setActiveTab(2)} />
            <QuickPill icon="📋" label="История" onClick={() => setActiveTab(0)} />
          </div>
        </div>

        {error && (
          <div className="mt-3 rounded-xl border border-border/50 bg-secondary/40 px-3 py-2">
            <p className="text-xs text-muted-foreground">{error}</p>
          </div>
        )}
      </div>
    </header>
  )
}

function QuickPill({ 
  icon, 
  label, 
  variant = 'default',
  onClick,
}: { 
  icon: string
  label: string
  variant?: 'default' | 'gold'
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
      "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-xs font-medium",
      "transition-all duration-200",
      onClick ? "cursor-pointer hover:scale-[1.02]" : "cursor-default",
      variant === 'gold' 
        ? "bg-gold/15 text-gold border border-gold/20" 
        : "bg-secondary/80 text-secondary-foreground border border-border/50"
    )}>
      <span>{icon}</span>
      <span>{label}</span>
    </button>
  )
}
