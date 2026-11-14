import { getInitData, hasTelegramInitData } from '../api'

function tgData(ageSeconds: number, userId = 123): string {
  const authDate = Math.floor(Date.now() / 1000) - ageSeconds
  return new URLSearchParams({
    auth_date: String(authDate),
    user: JSON.stringify({ id: userId, first_name: 'Test' }),
    hash: 'a'.repeat(64),
  }).toString()
}

beforeEach(() => {
  window.sessionStorage.clear()
  delete window.__BANANO_TG_INIT_DATA__
  delete window.__BANANO_PLATFORM_INIT_DATA__
  delete window.__BANANO_INITIAL_LAUNCH__
  window.Telegram = undefined
  window.history.replaceState({}, '', '/')
})

afterEach(() => {
  window.sessionStorage.clear()
  delete window.__BANANO_TG_INIT_DATA__
  delete window.__BANANO_PLATFORM_INIT_DATA__
  delete window.__BANANO_INITIAL_LAUNCH__
  window.Telegram = undefined
  window.history.replaceState({}, '', '/')
})

test('fresh Telegram SDK launch supersedes an expired pre-hydration snapshot', () => {
  const stale = tgData(90000)
  const fresh = tgData(0)
  window.__BANANO_INITIAL_LAUNCH__ = { hash: '#tgWebAppData=' + encodeURIComponent(stale), search: '' }
  window.Telegram = { WebApp: { initData: fresh } }
  expect(getInitData()).toBe(fresh)
  expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBe(fresh)
})

test('fresh Telegram SDK launch supersedes a still-valid but older snapshot', () => {
  const older = tgData(3600)
  const fresh = tgData(0)
  window.__BANANO_INITIAL_LAUNCH__ = { hash: '#tgWebAppData=' + encodeURIComponent(older), search: '' }
  window.Telegram = { WebApp: { initData: fresh } }
  expect(getInitData()).toBe(fresh)
})

test('expired sessionStorage initData is not used for another bootstrap 401', () => {
  window.sessionStorage.setItem('__banano_tg_init_data', tgData(90000))
  expect(getInitData()).toBe('')
  expect(hasTelegramInitData()).toBe(false)
  expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBeNull()
})

test('stale stored launch hash cannot shadow a new Telegram SDK session', () => {
  const stale = tgData(90000)
  const fresh = tgData(0)
  window.sessionStorage.setItem('__banano_initial_hash', '#tgWebAppData=' + encodeURIComponent(stale))
  window.Telegram = { WebApp: { initData: fresh } }
  expect(getInitData()).toBe(fresh)
})

test('stale memory-only cached Telegram initData is not reused without a fresh launch', () => {
  window.__BANANO_TG_INIT_DATA__ = tgData(90000)
  expect(getInitData()).toBe('')
  expect(window.__BANANO_TG_INIT_DATA__).toBeUndefined()
})

test('malformed persisted initData without auth_date is not treated as authenticated', () => {
  window.sessionStorage.setItem('__banano_tg_init_data', 'old-telegram-session')
  expect(getInitData()).toBe('')
  expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBeNull()
})

test('fresh browser fallback session remains available after a page reload', () => {
  const fresh = tgData(60)
  window.sessionStorage.setItem('__banano_tg_init_data', fresh)
  expect(getInitData()).toBe(fresh)
})

test('fresh URL launch works before Telegram SDK is loaded', () => {
  const fresh = tgData(0)
  window.history.replaceState({}, '', '/#tgWebAppData=' + encodeURIComponent(fresh))
  expect(getInitData()).toBe(fresh)
})

test('newly issued browser login hash wins over a still-valid old Telegram SDK session', () => {
  const older = tgData(600)
  const fresh = tgData(0)
  window.Telegram = { WebApp: { initData: older } }
  window.history.replaceState({}, '', '/#tgWebAppData=' + encodeURIComponent(fresh))
  expect(getInitData()).toBe(fresh)
})
