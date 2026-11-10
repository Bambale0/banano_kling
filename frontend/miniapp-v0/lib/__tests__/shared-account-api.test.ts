import { acceptAccountLink, checkAccountPreviewLogin, createAccountLink, fetchVkNativeState, fetchVkPublicTrend, generateVkImage, previewAccountLink, saveAccountPreviewSettings, startAccountAppSession, stopAccountAppSession } from '../shared-account-api'
import { setPlatformSessionToken } from '../api'

jest.mock('../api', () => ({
  getApiBasePath: () => '/mini-app/api',
  getInitData: () => 'signed-launch',
  setPlatformSessionToken: jest.fn(),
  clearPlatformSessionToken: jest.fn(),
}))

function reply(status: number, payload = {}) {
  return { status, ok: status === 200, json: async () => ({ ok: status === 200, ...payload }) } as Response
}

beforeEach(() => {
  jest.clearAllMocks()
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

test('oversized Cyrillic native prompt is rejected clearly before auth or media requests', async () => {
  await expect(generateVkImage({
    model: 'nano_banana_pro', prompt: 'Я'.repeat(17000), aspect: '1:1',
    resolution: '2K', reference_photos: [], quote_only: true,
  })).rejects.toThrow('Сократите промпт или число референсов')
  expect(global.fetch).not.toHaveBeenCalled()
})

test('native Cyrillic prompt within the byte budget reaches the signed generation API', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'session-token', account: { id: 'source' } }))
    .mockResolvedValueOnce(reply(200, { task_id: 0, cost: 2.5, quote_only: true }))
    .mockResolvedValueOnce(reply(200))
  const payload = { model: 'nano_banana_pro', prompt: 'Я'.repeat(15000), aspect: '1:1',
    resolution: '2K', reference_photos: [], quote_only: true }
  await expect(generateVkImage(payload)).resolves.toEqual(expect.objectContaining({ cost: 2.5 }))
  expect(fetch.mock.calls[1][0]).toBe('/mini-app/api/account-preview/vk-image')
  expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toEqual(payload)
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


test('linked VK application session stays in memory for the shared API', async () => {
  const query = 'vk_app_id=123&vk_user_id=456&vk_ts=1000&sign=signed-value'
  window.history.replaceState({}, '', '/?' + query)
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, {
    session_token: 'a'.repeat(43),
    account: { id: 'account-1' },
  })).mockResolvedValueOnce(reply(200, {
    account: { id: 'account-1' },
    preview: {
      revision: 1,
      vk_app_id: 123,
      telegram_bot_username: 'Neuromixx_bot',
      telegram_linked: true,
    },
  }))

  const access = await startAccountAppSession()

  expect(access.telegram_linked).toBe(true)
  expect(setPlatformSessionToken).toHaveBeenCalledWith('a'.repeat(43))
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(fetch.mock.calls.every(([url]) => !String(url).includes('a'.repeat(43)))).toBe(true)
  fetch.mockResolvedValueOnce(reply(200))
  await stopAccountAppSession()
})

test('unlinked VK retains one revocable in-memory session for history refresh without re-signing', async () => {
  const query = 'vk_app_id=123&vk_user_id=456&vk_ts=1000&sign=signed-value'
  window.history.replaceState({}, '', '/?' + query)
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, {
    session_token: 'b'.repeat(43),
    account: { id: 'account-1' },
  })).mockResolvedValueOnce(reply(200, {
    account: { id: 'account-1' },
    preview: {
      revision: 1,
      vk_app_id: 123,
      telegram_bot_username: 'Neuromixx_bot',
      telegram_linked: false,
    },
  })).mockResolvedValueOnce(reply(200, {
    registered: true, balance: 12.5, is_blocked: false, tasks: [],
  })).mockResolvedValueOnce(reply(200))

  const access = await startAccountAppSession()
  expect(access.telegram_linked).toBe(false)
  expect(setPlatformSessionToken).toHaveBeenCalledWith('b'.repeat(43))
  const history = await fetchVkNativeState()
  expect(history.balance).toBe(12.5)
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([
    '/mini-app/api/account-preview/session',
    '/mini-app/api/account-preview/me',
    '/mini-app/api/account-preview/vk-native-state',
  ])
  expect(fetch.mock.calls[2][1]?.headers).toEqual(expect.objectContaining({
    Authorization: 'Bearer ' + 'b'.repeat(43),
  }))
  await stopAccountAppSession()
  expect(fetch.mock.calls[3][0]).toBe('/mini-app/api/account-preview/logout')
})

test('quick invitation submits signed source consent only with the connect click', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'session-token', account: { id: 'source' } }))
    .mockResolvedValueOnce(reply(200, { link: { id: 'pending', token: 'a'.repeat(43) } }))
    .mockResolvedValueOnce(reply(200))
  await createAccountLink('vk', undefined, true)
  expect(fetch.mock.calls[1][0]).toBe('/mini-app/api/account-preview/links')
  expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toEqual({
    target_platform: 'vk', confirm_source: true,
  })
  expect(fetch.mock.calls[1][1]?.headers).toEqual(expect.objectContaining({ Authorization: 'Bearer session-token' }))
  expect(fetch.mock.calls[2][0]).toBe('/mini-app/api/account-preview/logout')
})

test('opening a signed invitation previews identity without accepting it', async () => {
  const fetch = jest.mocked(global.fetch)
  const token = 'x'.repeat(43)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'session-token', account: { id: 'target' } }))
    .mockResolvedValueOnce(reply(200, { link: { id: 'pending', source_identity: { platform: 'vk', external_id: '456' } } }))
    .mockResolvedValueOnce(reply(200))
  const invitation = await previewAccountLink(token)
  expect(invitation.source_identity?.external_id).toBe('456')
  expect(fetch.mock.calls[1][0]).toBe('/mini-app/api/account-preview/links/preview')
  expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toEqual({ token })
  expect(fetch.mock.calls.map(([url]) => String(url)).join(' ')).not.toContain(token)
})

test('recipient confirmation is one authenticated accept request and session is revoked', async () => {
  const fetch = jest.mocked(global.fetch)
  const token = 'x'.repeat(43)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'session-token', account: { id: 'target' } }))
    .mockResolvedValueOnce(reply(200, { link: { id: 'done', state: 'committed' } }))
    .mockResolvedValueOnce(reply(200))
  const link = await acceptAccountLink(token, undefined, true)
  expect(link.state).toBe('committed')
  expect(fetch.mock.calls[1][0]).toBe('/mini-app/api/account-preview/links/accept')
  expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toEqual({ token, confirm: true })
  expect(fetch.mock.calls[2][0]).toBe('/mini-app/api/account-preview/logout')
})

test('wrong-platform invitation is not mistaken for missing admin permission', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'session-token', account: { id: 'target' } }))
    .mockResolvedValueOnce(reply(403)).mockResolvedValueOnce(reply(200))
  await expect(previewAccountLink('x'.repeat(43))).rejects.toThrow(
    'Это приглашение предназначено другому аккаунту или платформе.',
  )
})


test('direct public VK trend lookup stays within signed platform API, without Telegram launch', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'a'.repeat(43), account: { id: 'vk-actor' } }))
    .mockResolvedValueOnce(reply(200, {
      item: { id: 5, title: 'Safe trend', preview_url: null, share_link: 'https://vk.com/app123#prompt_5' },
      can_generate_in_app: true,
    }))
    .mockResolvedValueOnce(reply(200))
  await expect(fetchVkPublicTrend(5)).resolves.toEqual(expect.objectContaining({ can_generate_in_app: true }))
  expect(fetch.mock.calls[1][0]).toBe('/mini-app/api/account-preview/trends?view=item&trend_id=5')
  expect(fetch.mock.calls.map(([url]) => String(url))).not.toEqual(expect.arrayContaining([expect.stringContaining('t.me')]))
  expect(fetch.mock.calls[2][0]).toBe('/mini-app/api/account-preview/logout')
  await expect(fetchVkPublicTrend(-4)).rejects.toThrow('Некорректный тренд')
})
