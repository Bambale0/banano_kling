'use client'

import { Banana, Wallet } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useOptionalApp } from '@/lib/app-context'
import { selectTopupPackages, type TopupPackageOption } from '@/lib/contextual-topup'

interface GenerationFundingOfferProps {
  cost: number | null | undefined
  credits: number
  adminFree?: boolean
}

const format = (value: number) => new Intl.NumberFormat('ru-RU', {
  maximumFractionDigits: 2,
}).format(value)

/** Payment is opt-in. This component never submits a generation or creates an invoice. */
export function GenerationFundingOffer({
  cost,
  credits,
  adminFree = false,
}: GenerationFundingOfferProps) {
  const app = useOptionalApp()
  if (!app || app.state.mode !== 'live' || app.state.user.isAdmin || adminFree ||
      typeof cost !== 'number' || !Number.isFinite(cost) || cost <= 0) return null

  const offer = selectTopupPackages(cost, credits, app.state.paymentPackages)
  if (!offer.shortage) return null

  const select = (option?: TopupPackageOption) => {
    app.openBalance({ packageId: option?.package.id, requiredCredits: cost })
  }

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
            Купить {format(offer.recommended.credited)}🍌 за {format(offer.recommended.package.price_rub)} ₽
          </Button>
          {offer.alternative ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => select(offer.alternative!)}
              className="h-auto min-h-11 w-full whitespace-normal border-gold/25 bg-background/40 py-2 text-center"
            >
              Больше бананов: {format(offer.alternative.credited)}🍌 — {format(offer.alternative.package.price_rub)} ₽
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
