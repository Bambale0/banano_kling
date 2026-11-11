import { accountLaunch, currentAccountPlatform, platformMiniAppUrl } from '../account-platform'

const sourceSearch = '?vk_app_id=54880352&vk_user_id=2001&vk_ts=1794400000&vk_ref=bot_keyboard&sign=' + 'a'.repeat(43)

afterEach(() => {
  delete window.__BANANO_INITIAL_LAUNCH__
  window.history.replaceState({}, '', '/')
  delete process.env.NEXT_PUBLIC_MINIAPP_PLATFORM
})

test('VK launch uses the original in-memory signed query if WebView strips it before React hydration', () => {
  process.env.NEXT_PUBLIC_MINIAPP_PLATFORM = 'vk'
  window.__BANANO_INITIAL_LAUNCH__ = { search: sourceSearch, hash: '' }
  window.history.replaceState({}, '', '/?ref=bot_keyboard')
  expect(accountLaunch()).toEqual({ platform: 'vk', launch_data: sourceSearch.slice(1) })
  expect(currentAccountPlatform()).toBe('vk')
  expect(platformMiniAppUrl('feed_12')).toBe('https://vk.com/app54880352#feed_12')
  expect(window.sessionStorage.getItem('__banano_initial_search')).toBeNull()
})

test('VK original signed snapshot wins when host preserves only an incomplete app ID', () => {
  process.env.NEXT_PUBLIC_MINIAPP_PLATFORM = 'vk'
  window.__BANANO_INITIAL_LAUNCH__ = { search: sourceSearch, hash: '' }
  window.history.replaceState({}, '', '/?vk_app_id=54880352&ref=bot_keyboard')
  expect(accountLaunch().launch_data).toBe(sourceSearch.slice(1))
})

test('VK launch cannot use incomplete or unsigned initial data as a credential', () => {
  process.env.NEXT_PUBLIC_MINIAPP_PLATFORM = 'vk'
  window.__BANANO_INITIAL_LAUNCH__ = { search: '?vk_app_id=54880352&vk_user_id=2001', hash: '' }
  window.history.replaceState({}, '', '/?ref=bot_keyboard')
  expect(() => accountLaunch()).toThrow('Откройте приложение из ВКонтакте')
})

test('a current complete VK launch takes precedence over an old in-memory snapshot', () => {
  window.__BANANO_INITIAL_LAUNCH__ = { search: sourceSearch, hash: '' }
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=3001&vk_ts=1794401000&sign=' + 'b'.repeat(43))
  const { launch_data } = accountLaunch()
  expect(launch_data).toContain('vk_app_id=123')
  expect(launch_data).not.toContain('vk_app_id=54880352')
})
