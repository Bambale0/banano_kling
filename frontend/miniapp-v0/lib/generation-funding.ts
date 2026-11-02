import type { PaymentPackage } from './types'

export interface FundingIntent {
  cost: number
  packageId?: string
}

export interface FundingPackage {
  package: PaymentPackage
  totalCredits: number
}

function validCredits(value: number): boolean {
  return Number.isFinite(value) && value >= 0
}

/**
 * Recommend the cheapest currently configured single package that covers
 * the *shortage*, not the entire generation price. Never infer a custom
 * amount or a promo bonus that checkout has not confirmed.
 */
export function getGenerationFunding(
  cost: number,
  balance: number,
  packages: PaymentPackage[],
) {
  if (!validCredits(cost) || !validCredits(balance)) return null

  const shortage = Math.max(0, Math.round((cost - balance) * 100) / 100)
  const available: FundingPackage[] = packages
    .filter((item) => Boolean(item.id) && Number.isFinite(item.price_rub) && item.price_rub > 0
      && Number.isFinite(item.credits) && item.credits > 0
      && (item.bonus_credits == null || (Number.isFinite(item.bonus_credits) && item.bonus_credits >= 0)))
    .map((item) => ({ package: item, totalCredits: item.credits + (item.bonus_credits ?? 0) }))
    .sort((a, b) => a.package.price_rub - b.package.price_rub
      || a.totalCredits - b.totalCredits || a.package.id.localeCompare(b.package.id))

  const recommended = available.find((item) => item.totalCredits >= shortage) ?? null
  return { shortage, available, recommended }
}
