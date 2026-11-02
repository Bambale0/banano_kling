'use client'

import { Banana, Wallet } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { useOptionalApp } from '@/lib/app-context'
import {
  paymentPriceLabel,
  preferredProviderForPackage,
  selectTopupPackages,
  type TopupPackageOption,
} from '@/lib/contextual-topup'

interface GenerationFundingOfferProps {
  cost: number | null | undefined
  credits: number
  adminFree?: boolean
  autoOpenKey?: string | number | null
}

const format = (value: number) => new Intl.NumberFormat('ru-RU', {
  maximumFractionDigits: 2,
}).format(value)

/** Payment is opt-in. This component never submits a generation or creates an invoice. */
export function GenerationFundingOffer({
  cost,
  credits,
  adminFree = false,
  autoOpenKey = null,
}: GenerationFundingOfferProps) {
  const app = useOptionalApp()
  const autoOpenedRef = useRef<string | null>(null)
  const eligible = Boolean(
    app && app.state.mode === 'live' && !app.state.user.isAdmin && !adminFree &&
    typeof cost === 'number' && Number.isFinite(cost) && cost > 0,
  )
  const offer = eligible
    ? selectTopupPackages(cost!, credits, app!.state.paymentPackages)
    : { shortage: 0, recommended: null, alternative: null }

  useEffect(() => {
    if (!app || autoOpenKey == null || !offer.shortage || typeof cost !== 'number') return
    const packageId = offer.recommended?.package.id
    const key = `${autoOpenKey}:${cost}:${packageId ?? 'all-packages'}`
    if (autoOpenedRef.current === key) return
    autoOpenedRef.current = key
    app.openBalance({
      packageId,
      requiredCredits: cost,
      reason: 'video-repeat',
    })
  }, [app, autoOpenKey, cost, offer.recommended, offer.shortage])

  if (!eligible || !app || typeof cost !== 'number') return null
  if (!offer.shortage) return null

  const select = (option?: TopupPackageOption) => {
    app.openBalance({ packageId: option?.package.id, requiredCredits: cost })
  }

  const price = (option: TopupPackageOption) => paymentPriceLabel(
    option.package,
    preferredProviderForPackage(option.package),
  )

  return (
    <section
      role="region"
      aria-label="Пополнение для генерации"
      className="space-y-3 rounded-2xl border border-gold/35 bg-gold/10 p-3 sm:p-4"
    >
      <div className="flex items-start gap-2">
        <Wallet className="mt-0.5 h-5 w-5 shrink-0 text-gold" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-foreground">Пополните баланс для этого видео</p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <span>Стоимость: <strong className="text-foreground">{format(cost)}🍌</strong></span>
            <span>На балансе: <strong className="text-foreground">{format(credits)}🍌</strong></span>
          </div>
          <p className="mt-1 text-sm font-semibold text-gold">Не хватает {format(offer.shortage)}🍌</p>
        </div>
      </div>

      {offer.recommended ? (
        <div className="space-y-2">
          <Button
            type="button"
            onClick={() => select(offer.recommended!)}
            className="h-auto min-h-11 w-full whitespace-normal bg-gold py-3 text-center text-primary-foreground hover:bg-gold/90"
          >
            <Banana className="mr-2 h-4 w-4 shrink-0" aria-hidden="true" />
            Купить {format(offer.recommended.credited)}🍌 за {price(offer.recommended)}
          </Button>
          {offer.alternative ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => select(offer.alternative!)}
              className="h-auto min-h-11 w-full whitespace-normal border-gold/25 bg-background/40 py-2 text-center"
            >
              Больше бананов: {format(offer.alternative.credited)}🍌 — {price(offer.alternative)}
            </Button>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Одного доступного пакета недостаточно. Выберите подходящие суммы в разделе пополнения.
        </p>
      )}

      <Button
        type="button"
        variant="ghost"
        className="h-10 w-full text-foreground"
        onClick={() => select()}
      >
        Другие суммы и способы оплаты
      </Button>
      <p className="text-xs leading-5 text-muted-foreground">
        Покупка начисляет бананы на баланс. Видео запускается только после вашего подтверждения.
      </p>
    </section>
  )
}
