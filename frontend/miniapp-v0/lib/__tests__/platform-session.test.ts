import { clearPlatformSessionToken, getInitData, setPlatformSessionToken } from '../api'

beforeEach(() => {
  window.sessionStorage.clear()
  delete window.__BANANO_TG_INIT_DATA__
  delete window.__BANANO_PLATFORM_INIT_DATA__
  delete window.__BANANO_INITIAL_LAUNCH__
  window.Telegram = undefined
  window.history.replaceState({}, '', '/')
})

test('VK application credential is memory-only and wins over cached Telegram data', () => {
  window.sessionStorage.setItem('__banano_tg_init_data', 'old-telegram-session')
  setPlatformSessionToken('a'.repeat(43))

  expect(getInitData()).toBe('vk_session:' + 'a'.repeat(43))
  expect(window.sessionStorage.getItem('__banano_platform_init_data')).toBeNull()
  expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBe('old-telegram-session')

  clearPlatformSessionToken()
  expect(getInitData()).toBe('old-telegram-session')
})

test('invalid platform tokens are rejected without changing authentication', () => {
  expect(() => setPlatformSessionToken('not-a-token')).toThrow('Некорректная сессия ВК.')
  expect(getInitData()).toBe('')
})
