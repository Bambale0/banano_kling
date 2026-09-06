'use client'

import type { Seedance25GenerateResponse } from '@/lib/seedance25-api'

interface Props {
  duration?: number | null
  ratio?: string | null
  isSubmitting: boolean
  error?: string | null
  result?: Seedance25GenerateResponse | null
  onRepeat: () => void
}

export function Seedance25RepeatCard({
  duration,
  ratio,
  isSubmitting,
  error,
  result,
  onRepeat,
}: Props) {
  return (
    <div data-testid="seedance25-repeat-card" className="glass space-y-5 rounded-3xl border border-gold/30 p-5 sm:p-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gold">Повтор видео</p>
        <h3 className="mt-2 font-serif text-2xl font-semibold text-foreground">Seedance 2.5</h3>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Повторим исходное видео с теми же настройками и доступными референсами. Ничего выбирать заново не нужно.
        </p>
      </div>

      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        {duration ? (
          <span className="rounded-full border border-border/50 bg-secondary/35 px-3 py-1.5">{duration} сек</span>
        ) : null}
        {ratio ? (
          <span className="rounded-full border border-border/50 bg-secondary/35 px-3 py-1.5">{ratio}</span>
        ) : null}
      </div>

      {error ? (
        <div className="rounded-2xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {result ? (
        <div className="rounded-2xl border border-cyan/25 bg-cyan/5 p-4 text-sm text-foreground">
          ✅ Повтор запущен. Готовое видео придёт в Telegram.
          {!result.admin_free ? (
            <span className="mt-1 block text-xs text-muted-foreground">Списано {result.cost}🍌.</span>
          ) : null}
        </div>
      ) : null}

      <button
        type="button"
        onClick={onRepeat}
        disabled={isSubmitting}
        className="h-12 w-full rounded-2xl bg-gold px-4 text-base font-semibold text-primary-foreground transition hover:bg-gold/90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isSubmitting ? 'Повторяю…' : 'Повторить видео'}
      </button>
    </div>
  )
}
