import { clearBrowserAccountCredentials, isBrowserAccountSession } from '../browser-account-session'
import { getInitData, setPlatformSessionToken } from '../api'

const browserSession = 'query_id=browser_test_session&auth_date=1795100000&hash=mock'
const nativeSession = 'query_id=AAE123&auth_date=1795100000&hash=mock'

beforeEach(() => {
  window.sessionStorage.clear()
  delete window.__BANANO_TG_INIT_DATA__
  delete window.__BANANO_PLATFORM_INIT_DATA__
  delete window.__BANANO_INITIAL_LAUNCH__
  window.Telegram = undefined
  window.history.replaceState({}, '', '/mini-app/')
})

test('web browser login can be signed out without exposing the option for native Telegram', () => {
  window.__BANANO_TG_INIT_DATA__ = browserSession
  expect(isBrowserAccountSession()).toBe(true)

  window.__BANANO_TG_INIT_DATA__ = nativeSession
  expect(isBrowserAccountSession()).toBe(false)

  setPlatformSessionToken('a'.repeat(43))
  expect(isBrowserAccountSession()).toBe(false)
})

test('signout drops all cached browser credentials and strips launch auth from URL', () => {
  window.history.replaceState({}, '', '/mini-app/?tgWebAppData=' + encodeURIComponent(browserSession) + '#tgWebAppData=' + encodeURIComponent(browserSession))
  window.__BANANO_TG_INIT_DATA__ = browserSession
  window.__BANANO_INITIAL_LAUNCH__ = {
    hash: '#tgWebAppData=' + encodeURIComponent(browserSession),
    search: '?tgWebAppData=' + encodeURIComponent(browserSession),
  }
  for (const key of ['__banano_tg_init_data', '__banano_initial_href', '__banano_initial_hash',
    '__banano_initial_search', '__telegram__initParams']) {
    window.sessionStorage.setItem(key, browserSession)
  }
  window.sessionStorage.setItem('ui_theme', 'dark')

  expect(isBrowserAccountSession()).toBe(true)
  clearBrowserAccountCredentials()

  expect(window.location.pathname).toBe('/mini-app/')
  expect(window.location.hash).toBe('')
  expect(window.location.search).toBe('')
  expect(window.__BANANO_TG_INIT_DATA__).toBeUndefined()
  expect(window.__BANANO_INITIAL_LAUNCH__).toBeUndefined()
  expect(getInitData()).toBe('')
  expect(window.sessionStorage.getItem('ui_theme')).toBe('dark')
  for (const key of ['__banano_tg_init_data', '__banano_initial_href', '__banano_initial_hash',
    '__banano_initial_search', '__telegram__initParams']) {
    expect(window.sessionStorage.getItem(key)).toBeNull()
  }
})

test('no native Telegram account credential is destroyed by signing out of web', () => {
  window.__BANANO_TG_INIT_DATA__ = nativeSession
  expect(isBrowserAccountSession()).toBe(false)
  expect(getInitData()).toBe(nativeSession)
})
