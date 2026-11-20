import { getInitData } from '../api'
import { isBrowserPaymentSession, isTelegramPaymentSurface, openWebPayment, paymentDestination, safePaymentReturnTo, webPaymentUrl } from '../web-payments'

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

it('keeps the Telegram page and a manual link when external navigation fails', () => {
  ;(getInitData as jest.Mock).mockReturnValue('query_id=tg&hash=signed')
  const open = jest.spyOn(window, 'open').mockReturnValue(null)
  const original = window.Telegram!.WebApp!
  const broken = { ...original, openLink: () => { throw new Error('unavailable') } }
  window.Telegram = { WebApp: broken }
  const listener = jest.fn()
  window.addEventListener('neuromix-web-payment', listener)
  const before = window.location.href
  try {
    openWebPayment({ packageId: 'mini' })
    expect(window.location.href).toBe(before)
    expect(open).toHaveBeenCalledWith(expect.stringContaining('/login?'), '_blank', 'noopener,noreferrer')
    expect(listener).toHaveBeenCalledTimes(1)
  } finally {
    open.mockRestore()
    window.Telegram = { WebApp: original }
    window.removeEventListener('neuromix-web-payment', listener)
  }
})

it('does not bounce a verified Yandex webstudio checkout back to /login', () => {
  // web_auth_studio mints a signed webstudio_* initData for the linked user.
  // It is NOT a Telegram WebView launch even though it uses Telegram-shaped fields.
  ;(getInitData as jest.Mock).mockReturnValue('query_id=webstudio_verified-session-abcdef123456&hash=synthetic')
  expect(isBrowserPaymentSession()).toBe(true)
  expect(isTelegramPaymentSurface()).toBe(false)
  expect(paymentDestination({ packageId: 'mini', provider: 'lava_card', promoCode: 'REF50' }))
    .toBe('/mini-app/?intent=topup&package_id=mini&provider=lava_card&promo_code=REF50')
})

it.each(['tg_native', 'webstudio', 'webstudiox_abcd', 'other_webstudio_session'])(
  'does not spoof browser checkout with an unrelated query_id %s', queryId => {
    ;(getInitData as jest.Mock).mockReturnValue('query_id=' + queryId + '&hash=synthetic')
    expect(isBrowserPaymentSession()).toBe(false)
    expect(isTelegramPaymentSurface()).toBe(true)
  },
)
