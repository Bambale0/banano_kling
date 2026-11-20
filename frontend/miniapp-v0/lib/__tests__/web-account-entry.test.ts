import { browserEntryMode, hasExplicitTelegramLaunch, browserLoginUrl } from '../web-account-entry'

beforeEach(() => {
  window.Telegram = undefined
  delete window.__BANANO_INITIAL_LAUNCH__
  window.history.replaceState({}, '', '/mini-app/')
  window.sessionStorage.clear()
})

test('a verified Yandex-only account enters a web session without a Telegram link', () => {
  expect(browserEntryMode(true, false)).toBe('web')
  expect(browserEntryMode(true, true)).toBe('linked')
  expect(browserEntryMode(false, false)).toBe('login')
  expect(browserEntryMode(false, true)).toBe('login')
})

test('only explicit Telegram launches win over browser cookies', () => {
  window.sessionStorage.setItem('__banano_tg_init_data', 'stale browser payload')
  expect(hasExplicitTelegramLaunch()).toBe(false)
  window.history.replaceState({}, '', '/mini-app/#tgWebAppData=signed-from-telegram')
  expect(hasExplicitTelegramLaunch()).toBe(true)
  window.history.replaceState({}, '', '/mini-app/')
  window.__BANANO_INITIAL_LAUNCH__ = { hash: '#tgWebAppData=early-signed-launch' }
  expect(hasExplicitTelegramLaunch()).toBe(true)
})

test('native Telegram SDK payload is not overridden by a browser web session', () => {
  window.Telegram = { WebApp: { initData: 'signed-native' } }
  expect(hasExplicitTelegramLaunch()).toBe(true)
})


test('anonymous browser login preserves referral and payment intent without forwarding arbitrary parameters', () => {
  expect(browserLoginUrl('?ref=NW0123456789ABCDEF&intent=topup&package_id=mini&provider=lava_card&junk=no'))
    .toBe('/login?ref=NW0123456789ABCDEF&intent=topup&package_id=mini&provider=lava_card')
  expect(browserLoginUrl('?startapp=test_ref&return_to=%2Fmini-app%2F%3Fintent%3Dtopup'))
    .toBe('/login?startapp=test_ref&return_to=%2Fmini-app%2F%3Fintent%3Dtopup')
  expect(browserLoginUrl('?return_to=https%3A%2F%2Fevil.example%2F'))
    .toBe('/login')
})
