import { getInitData } from './api'
import { currentAccountPlatform } from './account-platform'

export function isBrowserPaymentSession(): boolean {
  return new URLSearchParams(getInitData()).get('query_id')?.startsWith('browser_') === true
}

export function isTelegramPaymentSurface(): boolean {
  return currentAccountPlatform() === 'telegram' && !isBrowserPaymentSession()
}

type PaymentIntent = { packageId?: string; requiredCredits?: number; provider?: string; promoCode?: string }

export function paymentDestination(request: PaymentIntent = {}): string {
  const query = new URLSearchParams({ intent: 'topup' })
  if (request.packageId) query.set('package_id', request.packageId)
  if (request.provider) query.set('provider', request.provider)
  if (request.promoCode) query.set('promo_code', request.promoCode)
  if (request.requiredCredits && Number.isFinite(request.requiredCredits)) query.set('required_credits', String(request.requiredCredits))
  return `/mini-app/?${query}`
}

/** Only the local studio may receive login credentials. Never follow URLs,
 * protocol-relative paths, backslashes, hashes or nested login destinations. */
export function safePaymentReturnTo(raw: string | null): string {
  if (!raw || !raw.startsWith('/mini-app/') || /[\\#\u0000-\u0020]/.test(raw)) return '/mini-app/'
  const url = new URL(raw, 'https://local.invalid')
  if (url.origin !== 'https://local.invalid' || url.pathname !== '/mini-app/') return '/mini-app/'
  const query = new URLSearchParams()
  for (const key of ['intent', 'package_id', 'provider', 'required_credits', 'promo_code', 'startapp']) {
    const value = url.searchParams.get(key)
    if (value && value.length <= 200) query.set(key, value)
  }
  return '/mini-app/' + (query.size ? `?${query}` : '')
}

export function webPaymentUrl(request: PaymentIntent = {}): string {
  const url = new URL('/login', window.location.origin)
  url.searchParams.set('return_to', paymentDestination(request))
  return url.toString()
}

export function openWebPayment(request: PaymentIntent = {}): void {
  const url = webPaymentUrl(request)
  const bridge = window.Telegram?.WebApp as (NonNullable<NonNullable<Window['Telegram']>['WebApp']> & { openLink?: (url: string) => void }) | undefined
  if (bridge?.openLink) {
    try { bridge.openLink(url); return } catch { /* Use browser navigation. */ }
  }
  // Same-window fallback works when popup blocking prevents external tabs.
  window.location.assign(url)
}
