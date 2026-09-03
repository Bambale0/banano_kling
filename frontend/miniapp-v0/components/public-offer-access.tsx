'use client'

import { useEffect, useMemo, useState } from 'react'
import { FileText, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useApp } from '@/lib/app-context'
import { cn } from '@/lib/utils'

const MINIAPP_BASE_PATH =
  process.env.NEXT_PUBLIC_MINIAPP_BASE_PATH ||
  (process.env.NODE_ENV === 'production' ? '/mini-app' : '')
const OFFER_TEXT_URL = `${MINIAPP_BASE_PATH}/legal/public-offer.txt`.replace(/\/{2,}/g, '/')

type OfferContext = 'payment' | 'partner' | 'profile'

export function PublicOfferAccess() {
  const { isBalanceOpen, activeWorkspace, activeTab } = useApp()
  const [open, setOpen] = useState(false)
  const [offerText, setOfferText] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const context = useMemo<OfferContext | null>(() => {
    if (isBalanceOpen) return 'payment'
    if (activeWorkspace === 'partners') return 'partner'
    if (activeTab === 7) return 'profile'
    return null
  }, [activeTab, activeWorkspace, isBalanceOpen])

  useEffect(() => {
    if (!open || offerText || loading) return
    let cancelled = false
    setLoading(true)
    setError('')

    void fetch(OFFER_TEXT_URL, { cache: 'force-cache' })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.text()
      })
      .then((text) => {
        if (!cancelled) setOfferText(text)
      })
      .catch(() => {
        if (!cancelled) {
          setError('Не удалось загрузить оферту. Закройте окно и попробуйте ещё раз.')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [loading, offerText, open])

  useEffect(() => {
    if (!context) setOpen(false)
  }, [context])

  if (!context) return null

  const isOverlay = context === 'payment' || context === 'partner'
  const label = context === 'payment' ? 'Оферта · оплата = согласие' : 'Публичная оферта'
  const description =
    context === 'payment'
      ? 'Нажимая оплату, вы принимаете условия публичной оферты.'
      : context === 'partner'
        ? 'Условия партнёрской программы и расчётов.'
        : 'Полный юридический документ.'

  return (
    <>
      <div
        className={cn(
          'fixed right-4 z-[75] max-w-[calc(100vw-2rem)] rounded-2xl border border-border/60 bg-background/95 p-2 shadow-xl backdrop-blur',
          isOverlay
            ? 'bottom-[calc(env(safe-area-inset-bottom)+0.75rem)]'
            : 'bottom-[calc(env(safe-area-inset-bottom)+5.75rem)]',
        )}
      >
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setOpen(true)}
          className="h-9 rounded-xl border-gold/30 bg-gold/10 px-3 text-gold hover:bg-gold/15"
          aria-label={`${label}. ${description}`}
        >
          <FileText className="mr-2 h-4 w-4" />
          {label}
        </Button>
      </div>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          side="bottom"
          className="z-[90] h-[92vh] rounded-t-[28px] border-border/50 bg-background/98 px-0"
        >
          <SheetHeader className="border-b border-border/50 px-5 pb-4 pt-3 text-left">
            <SheetTitle className="font-serif text-2xl text-foreground">
              Публичная оферта
            </SheetTitle>
            <SheetDescription>
              Полный текст документа. Версия действует с 03 сентября 2026 года.
            </SheetDescription>
          </SheetHeader>

          <div className="h-[calc(92vh-105px)] overflow-auto px-5 py-5">
            {loading ? (
              <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Загружаю полный текст…
              </div>
            ) : error ? (
              <div className="rounded-2xl border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
                {error}
              </div>
            ) : (
              <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-6 text-foreground">
                {offerText}
              </pre>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}
