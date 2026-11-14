import { getInitData, hasTelegramInitData } from '../api'

const fresh = (hash: string): string => `auth_date=${Math.floor(Date.now() / 1000)}&hash=${hash}&user=%7B%22id%22%3A1%7D`
const stale = `auth_date=1600000000&hash=expired&user=%7B%22id%22%3A1%7D`

beforeEach(() => {
  sessionStorage.clear()
  window.history.replaceState({}, '', '/mini-app/')
  delete window.__BANANO_TG_INIT_DATA__
  delete window.__BANANO_INITIAL_LAUNCH__
  delete window.__BANANO_PLATFORM_INIT_DATA__
  delete window.Telegram
})
afterEach(() => {
  sessionStorage.clear()
  delete window.Telegram
})

test('fresh Telegram SDK launch overrides an expired cached launch snapshot', () => {
  const live = fresh('fresh-signed-by-telegram')
  sessionStorage.setItem('__banano_tg_init_data', stale)
  sessionStorage.setItem('__banano_initial_hash', '#tgWebAppData=' + encodeURIComponent(stale))
  window.__BANANO_TG_INIT_DATA__ = stale
  window.Telegram = { WebApp: { initData: live } }
  expect(getInitData()).toBe(live)
})

test('expired storage-only session cannot trigger a failing bootstrap', () => {
  sessionStorage.setItem('__banano_tg_init_data', stale)
  sessionStorage.setItem('__banano_initial_hash', '#tgWebAppData=' + encodeURIComponent(stale))
  window.__BANANO_TG_INIT_DATA__ = stale
  expect(getInitData()).toBe('')
  expect(hasTelegramInitData()).toBe(false)
})

test('fresh signed Telegram launch in location is accepted before SDK initialization', () => {
  const live = fresh('early-telegram')
  window.history.replaceState({}, '', '/mini-app/#tgWebAppData=' + encodeURIComponent(live))
  expect(getInitData()).toBe(live)
})
