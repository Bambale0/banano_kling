import { checkAccountPreviewLogin, saveAccountPreviewSettings } from '../shared-account-api'

jest.mock('../api', () => ({ getApiBasePath: () => '/mini-app/api', getInitData: () => 'signed-launch' }))

function reply(status: number, payload = {}) {
  return { status, ok: status === 200, json: async () => ({ ok: status === 200, ...payload }) } as Response
}

beforeEach(() => {
  global.fetch = jest.fn()
})
afterEach(() => {
  delete process.env.NEXT_PUBLIC_MINIAPP_PLATFORM
  window.history.replaceState({}, '', '/')
})

test('dedicated VK build refuses a cached Telegram launch before making any request', async () => {
  process.env.NEXT_PUBLIC_MINIAPP_PLATFORM = 'vk'
  await expect(checkAccountPreviewLogin()).rejects.toThrow('Откройте приложение из ВКонтакте.')
  expect(global.fetch).not.toHaveBeenCalled()
})

test('VK launch forwards the signed query intact and never substitutes Telegram credentials', async () => {
  process.env.NEXT_PUBLIC_MINIAPP_PLATFORM = 'vk'
  const query = 'vk_app_id=123&vk_user_id=456&vk_ts=1000&sign=signed-value'
  window.history.replaceState({}, '', '/?' + query)
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'private-session', account: { id: 'account-1' } }))
    .mockResolvedValueOnce(reply(200, { account: { id: 'account-1' } })).mockResolvedValueOnce(reply(200))
  await checkAccountPreviewLogin()
  expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({ platform: 'vk', launch_data: query })
})

test('login probe verifies the same account and revokes its operation-local token', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'private-session', account: { id: 'account-1' } }))
    .mockResolvedValueOnce(reply(200, { account: { id: 'account-1' } }))
    .mockResolvedValueOnce(reply(200))
  await checkAccountPreviewLogin()
  expect(fetch).toHaveBeenCalledTimes(3)
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([
    '/mini-app/api/account-preview/session', '/mini-app/api/account-preview/me', '/mini-app/api/account-preview/logout',
  ])
  expect(fetch.mock.calls[1][1]?.headers).toEqual(expect.objectContaining({ Authorization: 'Bearer private-session' }))
  expect(fetch.mock.calls[2][1]?.method).toBe('POST')
  expect(fetch.mock.calls.every(([url]) => !String(url).includes('private-session'))).toBe(true)
})

test('failed profile probe still revokes the session', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'private-session', account: { id: 'account-1' } }))
    .mockResolvedValueOnce(reply(403)).mockResolvedValueOnce(reply(200))
  await expect(checkAccountPreviewLogin()).rejects.toThrow('Требуется доступ администратора.')
  expect(fetch.mock.calls[2][0]).toBe('/mini-app/api/account-preview/logout')
})

test('cleanup failure does not mask the reason the profile was rejected', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'private-session', account: { id: 'account-1' } }))
    .mockResolvedValueOnce(reply(403)).mockResolvedValueOnce(reply(503))
  await expect(checkAccountPreviewLogin()).rejects.toThrow('Требуется доступ администратора.')
})

test('settings submit uses the viewed revision and signed administrator credentials', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValue(reply(409))
  await expect(saveAccountPreviewSettings({ enabled: true, vk_app_id: null, vk_admin_ids: [], session_ttl_seconds: 3600, launch_max_age_seconds: 600 }, 7)).rejects.toThrow('Настройки изменились.')
  expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual(expect.objectContaining({ expected_revision: 7, init_data: 'signed-launch' }))
})
