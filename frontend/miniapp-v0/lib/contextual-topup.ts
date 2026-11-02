import type { PaymentPackage } from './types'

export interface TopupPackageOption {
  package: PaymentPackage
  credited: number
}

export interface ContextualTopup {
  shortage: number
  recommended: TopupPackageOption | null
  alternative: TopupPackageOption | null
}

/**
 * Package prices and quantities come exclusively from the authenticated
 * Mini App bootstrap, never from mock data or a fixed ruble/banana exchange.
 * The promo code is applied by the existing checkout, not speculated here.
 */
export function selectTopupPackages(
  generationCost: number,
  currentCredits: number,
  packages: readonly PaymentPackage[],
): ContextualTopup {
  if (!Number.isFinite(generationCost) || generationCost <= 0 || !Number.isFinite(currentCredits)) {
    return { shortage: 0, recommended: null, alternative: null }
  }
  const shortage = Math.max(0, generationCost - Math.max(0, currentCredits))
  if (shortage === 0) return { shortage, recommended: null, alternative: null }

  const covering = packages.flatMap((pkg): TopupPackageOption[] => {
    const credits = Number(pkg.credits)
    const bonus = Number(pkg.bonus_credits ?? 0)
    const price = Number(pkg.price_rub)
    if (!Number.isInteger(credits) || credits <= 0 ||
        !Number.isInteger(bonus) || bonus < 0 ||
        !Number.isFinite(price) || price <= 0) return []
    const credited = credits + bonus
    return credited >= shortage ? [{ package: pkg, credited }] : []
  }).sort((left, right) =>
    left.package.price_rub - right.package.price_rub ||
    left.credited - right.credited ||
    left.package.id.localeCompare(right.package.id),
  )

  const recommended = covering[0] ?? null
  const alternative = recommended
    ? covering.find(item => item.package.id !== recommended.package.id &&
      item.credited > recommended.credited) ??
      covering.find(item => item.package.id !== recommended.package.id) ?? null
    : null

  return { shortage, recommended, alternative }
}
