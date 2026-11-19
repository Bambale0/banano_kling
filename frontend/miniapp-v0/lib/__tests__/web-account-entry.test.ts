import { browserEntryMode, hasExplicitTelegramLaunch } from '../web-account-entry'

beforeEach(() => {
  window.Telegram = undefined
  delete window.__BANANO_INITIAL_LAUNCH__
  window.history.replaceState({}, '', '/mini-app/')
  window.sessionStorage.clear()
})

test('a verified Yandex-only account enters a web session without a Telegram link', () => {
  expect(browserEntryMode(true, false)).toBe('web')
  expect(browserEntryMode(true, true)).toBe('linked')
  expect(browserEntryMode(false, false)).toBe('telegram')
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
