'use client'

import { useState } from 'react'
import type { PaymentPackage } from '@/lib/types'
import { getGenerationFunding, type FundingIntent, type FundingPackage } from '@/lib/generation-funding'
import { Button } from '@/components/ui/button'

interface GenerationFundingOfferProps {
  cost: number
  credits: number
  paymentPackages?: PaymentPackage[]
  onTopup?: (intent: FundingIntent) => void
  isAdmin?: boolean
}

function packageLabel(item: FundingPackage) {
  return `${item.totalCredits}🍌 за ${item.package.price_rub} ₽`
}

export function GenerationFundingOffer({
  cost, credits, paymentPackages, onTopup, isAdmin = false,
}: GenerationFundingOfferProps) {
  const [showOtherPackages, setShowOtherPackages] = useState(false)
  if (isAdmin || !Number.isFinite(cost) || !Number.isFinite(credits) || cost <= credits) return null

  const funding = getGenerationFunding(cost, credits, paymentPackages ?? [])
  if (!funding || funding.shortage <= 0) return null

  const { shortage, recommended, available } = funding
  const others = available.filter((item) => item.package.id !== recommended?.package.id)
  return (
    <section aria-label="Пополнение для генерации" className="space-y-3 rounded-2xl border border-gold/40 bg-gold/5 p-3.5">
      <div className="space-y-1">
        <p className="text-sm font-semibold text-foreground">Недостаточно бананов. Пополните баланс.</p>
        <p className="text-xs leading-relaxed text-muted-foreground">
          Видео стоит <strong className="text-foreground">{cost}🍌</strong>,
          у вас <strong className="text-foreground">{credits}🍌</strong>.
          Не хватает <strong className="text-gold">{shortage}🍌</strong>.
        </p>
      </div>
      {onTopup && recommended ? (
        <>
          <Button type="button" className="w-full bg-gold text-primary-foreground hover:bg-gold/90"
            onClick={() => onTopup({ cost, packageId: recommended.package.id })}>
            Купить {packageLabel(recommended)}
          </Button>
          {recommended.package.bonus_credits ? (
            <p className="text-xs text-muted-foreground">В пакете +{recommended.package.bonus_credits}🍌 бонусом.</p>
          ) : null}
          {others.length > 0 ? (
            <button type="button" className="w-full text-center text-xs font-medium text-gold underline underline-offset-4"
              aria-expanded={showOtherPackages} onClick={() => setShowOtherPackages((value) => !value)}>
              {showOtherPackages ? 'Скрыть другие пакеты' : 'Выбрать другой пакет'}
            </button>
          ) : null}
          {showOtherPackages ? (
            <div className="grid grid-cols-2 gap-2" aria-label="Другие пакеты">
              {others.map((item) => (
                <Button key={item.package.id} type="button" variant="outline"
                  className="h-auto min-h-11 whitespace-normal text-xs"
                  onClick={() => onTopup({ cost, packageId: item.package.id })}>
                  {packageLabel(item)}
                </Button>
              ))}
            </div>
          ) : null}
        </>
      ) : onTopup && available.length > 0 ? (
        <>
          <p className="text-xs text-muted-foreground">Для такой стоимости может потребоваться несколько пакетов.</p>
          <Button type="button" variant="outline" className="w-full" onClick={() => onTopup({ cost })}>
            Посмотреть все пакеты
          </Button>
        </>
      ) : paymentPackages && paymentPackages.length === 0 ? (
        <p className="text-xs text-muted-foreground">Пакеты временно недоступны. Обновите Mini App и попробуйте снова.</p>
      ) : null}
    </section>
  )
}
