import { clearPlatformSessionToken, getInitData, setPlatformSessionToken } from '../api'

beforeEach(() => {
  window.sessionStorage.clear()
  delete window.__BANANO_TG_INIT_DATA__
  delete window.__BANANO_PLATFORM_INIT_DATA__
  delete window.__BANANO_INITIAL_LAUNCH__
  window.Telegram = undefined
  window.history.replaceState({}, '', '/')
})

test('VK application credential is memory-only and an invalid cached Telegram credential is not resurrected', () => {
  window.sessionStorage.setItem('__banano_tg_init_data', 'old-telegram-session')
  setPlatformSessionToken('a'.repeat(43))

  expect(getInitData()).toBe('vk_session:' + 'a'.repeat(43))
  expect(window.sessionStorage.getItem('__banano_platform_init_data')).toBeNull()
  expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBe('old-telegram-session')

  clearPlatformSessionToken()
  expect(getInitData()).toBe('')
  expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBeNull()
})

test('clearing VK platform session restores a fresh signed Telegram session', () => {
  const fresh = `auth_date=${Math.floor(Date.now() / 1000)}&hash=telegram&user=%7B%22id%22%3A1%7D`
  window.sessionStorage.setItem('__banano_tg_init_data', fresh)
  setPlatformSessionToken('a'.repeat(43))
  expect(getInitData()).toBe('vk_session:' + 'a'.repeat(43))
  clearPlatformSessionToken()
  expect(getInitData()).toBe(fresh)
})

test('invalid platform tokens are rejected without changing authentication', () => {
  expect(() => setPlatformSessionToken('not-a-token')).toThrow('Некорректная сессия ВК.')
  expect(getInitData()).toBe('')
})
