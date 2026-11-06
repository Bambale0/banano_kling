import { getInitData } from '../api'

beforeEach(() => {
  window.sessionStorage.clear()
  window.history.replaceState({}, '', '/')
  delete window.__BANANO_INITIAL_LAUNCH__
  delete window.__BANANO_TG_INIT_DATA__
  window.Telegram = { WebApp: { initData: '' } }
})
afterEach(() => { window.sessionStorage.clear(); delete window.__BANANO_TG_INIT_DATA__; delete window.Telegram })

test('signed magic-link launch stays in memory and clears all cached copies', () => {
  const init = 'auth_date=123&start_param=link_' + 'a'.repeat(43) + '&hash=signature'
  window.Telegram!.WebApp!.initData = init
  window.sessionStorage.setItem('__banano_initial_hash', '#tgWebAppData=' + encodeURIComponent(init))
  window.sessionStorage.setItem('__banano_initial_href', 'https://example.test/#tgWebAppData=' + encodeURIComponent(init))
  window.sessionStorage.setItem('__telegram__initParams', JSON.stringify({ tgWebAppData: init }))
  window.sessionStorage.setItem('__banano_tg_init_data', 'previous-login')
  expect(getInitData()).toBe(init)
  expect(window.__BANANO_TG_INIT_DATA__).toBe(init)
  expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBeNull()
  expect(window.sessionStorage.getItem('__banano_initial_hash')).toBeNull()
  expect(window.sessionStorage.getItem('__banano_initial_href')).toBeNull()
  expect(window.sessionStorage.getItem('__telegram__initParams')).toBeNull()
})

test('ordinary Telegram launch preserves existing caching behavior', () => {
  window.Telegram!.WebApp!.initData = 'auth_date=123&hash=signature'
  expect(getInitData()).toBe('auth_date=123&hash=signature')
  expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBe('auth_date=123&hash=signature')
})
