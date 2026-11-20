import { clearBrowserAccountCredentials, isBrowserAccountSession, revokeBrowserAccountSession, signOutBrowserAccount } from '../browser-account-session'
import { getInitData, setPlatformSessionToken } from '../api'

const browserSession = 'query_id=browser_test_session&auth_date=1795100000&hash=mock'
const nativeSession = 'query_id=AAE123&auth_date=1795100000&hash=mock'

beforeEach(() => {
  window.sessionStorage.clear()
  delete window.__BANANO_TG_INIT_DATA__
  delete window.__BANANO_PLATFORM_INIT_DATA__
  delete window.__BANANO_INITIAL_LAUNCH__
  delete window.__BANANO_BROWSER_SIGNOUT__
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

test('linked website studio session exposes logout; malformed and native launch do not', () => {
  // This exactly matches the server web_auth._mint_session_bound_studio_init_data.
  const webstudio = 'query_id=webstudio_' + 'x'.repeat(32) + '&auth_date=1795100000&hash=fixture'
  window.__BANANO_TG_INIT_DATA__ = webstudio
  expect(isBrowserAccountSession()).toBe(true)

  window.__BANANO_TG_INIT_DATA__ = 'query_id=webstudio_' + 'z'.repeat(5) + '&auth_date=1795100000'
  expect(isBrowserAccountSession()).toBe(false)

  window.__BANANO_TG_INIT_DATA__ = nativeSession
  expect(isBrowserAccountSession()).toBe(false)

  setPlatformSessionToken('a'.repeat(43))
  window.__BANANO_TG_INIT_DATA__ = webstudio
  expect(isBrowserAccountSession()).toBe(false)
})

test('linked website studio logout revokes server token then removes cached identity', async () => {
  const browserSession = 'query_id=webstudio_' + 'w'.repeat(32) + '&auth_date=1795100000&hash=fixture'
  window.__BANANO_TG_INIT_DATA__ = browserSession
  window.sessionStorage.setItem('__banano_tg_init_data', browserSession)
  const savedFetch = global.fetch
  const mockFetch = jest.fn().mockResolvedValue({
    ok: true, json: async () => ({ ok: true }),
  })
  global.fetch = mockFetch as typeof fetch
  // window.location.replace is not configurable in jsdom, so observe the
  // server revoke + cleared identity before the navigation occurs.
  try {
    await signOutBrowserAccount().catch(() => {})
    expect(mockFetch).toHaveBeenCalledWith('/mini-app/api/web-auth/logout', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { Accept: 'application/json' },
    })
    expect(getInitData()).toBe('')
    expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBeNull()
  } finally {
    global.fetch = savedFetch
  }
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

test('browser sign-out blocks Telegram bridge rehydration during navigation', () => {
  window.Telegram = { WebApp: { initData: browserSession } }
  expect(getInitData()).toBe(browserSession)
  expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBe(browserSession)

  clearBrowserAccountCredentials()
  expect(getInitData()).toBe('')
  expect(window.__BANANO_TG_INIT_DATA__).toBeUndefined()
  expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBeNull()
})

test('no native Telegram account credential is destroyed by signing out of web', () => {
  window.__BANANO_TG_INIT_DATA__ = nativeSession
  expect(isBrowserAccountSession()).toBe(false)
  expect(getInitData()).toBe(nativeSession)
})

test('web session logout calls the server with cookies before local cleanup', async () => {
  const originalFetch = global.fetch
  const mockFetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) })
  global.fetch = mockFetch as typeof fetch
  try {
    await expect(revokeBrowserAccountSession()).resolves.toBeUndefined()
    expect(mockFetch).toHaveBeenCalledWith('/mini-app/api/web-auth/logout', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { Accept: 'application/json' },
    })
  } finally {
    global.fetch = originalFetch
  }
})

test('failed server revocation leaves browser credentials intact for a retry', async () => {
  const originalFetch = global.fetch
  global.fetch = jest.fn().mockResolvedValue({
    ok: false, status: 503, json: async () => ({ ok: false }),
  }) as typeof fetch
  window.__BANANO_TG_INIT_DATA__ = browserSession
  try {
    await expect(signOutBrowserAccount()).rejects.toThrow('Не удалось выйти из аккаунта')
    expect(getInitData()).toBe(browserSession)
    expect(isBrowserAccountSession()).toBe(true)
  } finally {
    global.fetch = originalFetch
  }
})
