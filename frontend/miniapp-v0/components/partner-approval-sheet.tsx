'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { BriefcaseBusiness, CheckCircle2, Copy, Loader2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useApp } from '@/lib/app-context'
import { fetchPartnerOverview } from '@/lib/api'

type PartnerOverview = Awaited<ReturnType<typeof fetchPartnerOverview>>

// Keep the exported component name for clients importing the old approval sheet.
export function PartnerApprovalSheet() {
  const { activeWorkspace, closeWorkspace } = useApp()
  const [partner, setPartner] = useState<PartnerOverview | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestId = useRef(0)
  const isOpen = activeWorkspace === 'partners'

  const loadPartnerData = useCallback(async (reset = false) => {
    const currentRequest = ++requestId.current
    if (reset) setPartner(null)
    setIsLoading(true)
    setError(null)
    try {
      const data = await fetchPartnerOverview()
      if (currentRequest === requestId.current) setPartner(data)
    } catch (cause) {
      if (currentRequest !== requestId.current) return
      const message = cause instanceof Error ? cause.message : 'Не удалось загрузить партнёрский кабинет'
      setError(message)
      toast.error('Партнёрская программа недоступна', { description: message })
    } finally {
      if (currentRequest === requestId.current) setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!isOpen) return
    void loadPartnerData(true)
    return () => { requestId.current += 1 }
  }, [isOpen, loadPartnerData])

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && closeWorkspace()}>
      <SheetContent side="bottom" className="h-[86vh] rounded-t-[28px] border-border/50 bg-background/95 px-0">
        <SheetHeader className="px-5 pt-3 text-left">
          <div className="mb-2">
            <div className="mb-3 h-1 w-10 rounded-full bg-border/80" />
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl border border-gold/20 bg-gold/10">
                <BriefcaseBusiness className="h-4 w-4 text-gold" />
              </div>
              <div className="min-w-0">
                <SheetTitle className="font-serif text-2xl leading-tight text-foreground">
                  Партнёрская программа
                </SheetTitle>
                <SheetDescription className="mt-1 max-w-xl text-sm leading-5 text-muted-foreground">
                  Кабинет, реферальная ссылка и статистика доступны всем пользователям.
                </SheetDescription>
              </div>
            </div>
          </div>
        </SheetHeader>

        <div className="h-[calc(86vh-92px)] overflow-auto px-5 pb-8">
          {partner ? (
            <PartnerCabinet
              partner={partner}
              referralLink={partner.referral_link || ''}
              isLoading={isLoading}
              onRefresh={loadPartnerData}
            />
          ) : error ? (
            <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
              <p role="alert" className="text-sm text-muted-foreground">{error}</p>
              <Button className="mt-4" onClick={() => void loadPartnerData()} disabled={isLoading}>
                Повторить загрузку
              </Button>
            </div>
          ) : (
            <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
              <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin text-gold" />
                Загружаю партнёрский кабинет…
              </div>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function PartnerCabinet({
  partner,
  referralLink,
  isLoading,
  onRefresh,
}: {
  partner: PartnerOverview
  referralLink: string
  isLoading: boolean
  onRefresh: () => Promise<void>
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/10 p-4">
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-emerald-400" />
          <div>
            <p className="font-medium text-foreground">Ваш партнёрский кабинет</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Реферальная ссылка активна и может закреплять новых пользователей.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-3">
          <p className="text-[11px] text-muted-foreground">Статус</p>
          <p className="mt-1 truncate font-serif text-lg text-foreground">Партнёр</p>
        </div>
        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-3">
          <p className="text-[11px] text-muted-foreground">Рефералов</p>
          <p className="mt-1 font-serif text-lg text-foreground">{partner?.referrals_count ?? '—'}</p>
        </div>
        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-3">
          <p className="text-[11px] text-muted-foreground">Баланс</p>
          <p className="mt-1 font-serif text-lg text-foreground">
            {partner ? `${partner.balance_rub} ₽` : '—'}
          </p>
        </div>
      </div>

      {typeof partner.percent === 'number' && (
        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4 text-sm">
          <p>Ваш процент с покупок рефералов 1 уровня: {partner.percent}%</p>
          {typeof partner.level2_percent === 'number' && (
            <p className="mt-1 text-muted-foreground">С покупок рефералов 2 уровня: {partner.level2_percent}%</p>
          )}
        </div>
      )}

      <div className="rounded-[1.5rem] border border-gold/20 bg-gold/10 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.16em] text-gold/80">Ваша ссылка</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Делитесь ей — новые пользователи закрепляются за вами по правилам партнёрки.
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => void onRefresh()}
            disabled={isLoading}
            className="shrink-0 border-border/50 bg-background/40 hover:bg-background/60"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            <span className="sr-only">Обновить</span>
          </Button>
        </div>

        <div className="mt-4 rounded-2xl border border-border/50 bg-background/45 p-3">
          <p className="break-all text-sm leading-6 text-foreground">
            {referralLink || 'Ссылка временно недоступна'}
          </p>
        </div>

        <Button
          disabled={!referralLink}
          onClick={() => {
            void navigator.clipboard.writeText(referralLink).then(
              () => toast.success('Реферальная ссылка скопирована'),
              () => toast.error('Не удалось скопировать ссылку'),
            )
          }}
          className="mt-4 h-12 w-full rounded-2xl bg-gold text-primary-foreground hover:bg-gold/90 disabled:opacity-50"
        >
          <Copy className="mr-2 h-4 w-4" />
          Скопировать ссылку
        </Button>
      </div>

      <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
        <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">Как это работает</p>
        <div className="mt-3 space-y-2">
          {[
            'Пользователь переходит по вашей активной ссылке.',
            'Система закрепляет его за вами после антифрод-проверок.',
            'Покупки рефералов обновляют партнёрский баланс и статистику.',
          ].map((item, index) => (
            <div key={item} className="flex gap-3 rounded-xl bg-background/35 px-3 py-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gold/10 text-xs text-gold">
                {index + 1}
              </span>
              <p className="text-sm leading-5 text-foreground">{item}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
