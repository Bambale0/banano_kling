'use client'

import { useEffect, useState } from 'react'
import { FileText, Loader2 } from 'lucide-react'

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'

const MINIAPP_BASE_PATH =
  process.env.NEXT_PUBLIC_MINIAPP_BASE_PATH ||
  (process.env.NODE_ENV === 'production' ? '/mini-app' : '')
const OFFER_TEXT_URL = `${MINIAPP_BASE_PATH}/legal/public-offer.txt`.replace(/\/{2,}/g, '/')

export function PublicOfferAccess() {
  const [open, setOpen] = useState(false)
  const [offerText, setOfferText] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || offerText) return
    let cancelled = false

    const loadOffer = async () => {
      setLoading(true)
      setError('')
      try {
        const response = await fetch(OFFER_TEXT_URL, { cache: 'force-cache' })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const text = await response.text()
        if (!cancelled) setOfferText(text)
      } catch {
        if (!cancelled) {
          setError('Не удалось загрузить оферту. Закройте окно и попробуйте ещё раз.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void loadOffer()
    return () => {
      cancelled = true
    }
  }, [offerText, open])

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-2xl border border-border/50 bg-secondary/20 p-4 text-left transition-colors hover:bg-secondary/40"
        aria-label="Открыть публичную оферту"
      >
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-gold/25 bg-gold/10 text-gold">
            <FileText className="h-4 w-4" />
          </div>
          <div>
            <p className="font-medium text-foreground">Публичная оферта</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Условия оплаты и использования сервиса.
            </p>
          </div>
        </div>
      </button>

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
