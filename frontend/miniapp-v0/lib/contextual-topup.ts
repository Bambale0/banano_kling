import type { PaymentPackage, PaymentProvider } from './types'

export interface TopupPackageOption {
  package: PaymentPackage
  credited: number
}

export interface ContextualTopup {
  shortage: number
  recommended: TopupPackageOption | null
  alternative: TopupPackageOption | null
}

export function totalPackageCredits(pkg: PaymentPackage) {
  return Number(pkg.credits) + Math.max(0, Number(pkg.bonus_credits ?? 0))
}

export function preferredProviderForPackage(pkg: PaymentPackage): PaymentProvider {
  if (pkg.robokassa_enabled) return 'robokassa'
  if (pkg.freekassa_enabled) return 'freekassa_card'
  if (pkg.lava_offer_id) return 'lava_card'
  return 'telegram_stars'
}

export function paymentPriceLabel(pkg: PaymentPackage, provider: PaymentProvider) {
  return provider === 'telegram_stars'
    ? `${pkg.price_stars ?? pkg.price_rub} ⭐`
    : `${pkg.price_rub} ₽`
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
    left.credited - right.credited ||
    left.package.price_rub - right.package.price_rub ||
    left.package.id.localeCompare(right.package.id),
  )

  const recommended = covering[0] ?? null
  // The secondary CTA says "More bananas"; never label a smaller bundle
  // that way even when prices were configured non-monotonically.
  const alternative = recommended
    ? covering.find(item => item.package.id !== recommended.package.id &&
      item.credited > recommended.credited) ?? null
    : null

  return { shortage, recommended, alternative }
}
