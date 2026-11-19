import { getInitData } from '../api'
import { isBrowserPaymentSession, isTelegramPaymentSurface, paymentDestination, safePaymentReturnTo, webPaymentUrl } from '../web-payments'

jest.mock('../api', () => ({ getInitData: jest.fn() }))

it('returns Telegram users to the exact package after website login without credentials', () => {
  ;(getInitData as jest.Mock).mockReturnValue('query_id=tg&hash=secret')
  expect(isTelegramPaymentSurface()).toBe(true)
  const url = new URL(webPaymentUrl({ packageId: 'mini', provider: 'lava_card', requiredCredits: 20 }))
  expect(url.pathname).toBe('/login')
  expect(url.searchParams.get('return_to')).toBe('/mini-app/?intent=topup&package_id=mini&provider=lava_card&required_credits=20')
  expect(url.toString()).not.toContain('secret')
})

it('recognizes the signed browser session and preserves the local checkout intent', () => {
  ;(getInitData as jest.Mock).mockReturnValue('query_id=browser_nonce')
  expect(isBrowserPaymentSession()).toBe(true)
  expect(isTelegramPaymentSurface()).toBe(false)
  expect(safePaymentReturnTo(paymentDestination({ packageId: 'start' }))).toBe('/mini-app/?intent=topup&package_id=start')
})

it.each(['https://evil.test/mini-app/', '//evil.test/mini-app/', '/mini-app/../login', '/mini-app/%2e%2e/login', '/mini-app/\\evil', '/mini-app/#tgWebAppData=bad', '/mini-app/?x=1#evil', 'javascript:alert(1)'])(
  'rejects an unsafe return destination %s', raw => expect(safePaymentReturnTo(raw)).toBe('/mini-app/'),
)
