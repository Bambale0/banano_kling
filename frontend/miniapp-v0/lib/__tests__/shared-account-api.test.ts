import { acceptAccountLink, createVkInvoice, checkAccountPreviewLogin, createAccountLink, fetchVkNativeState, fetchVkPublicTrend, fetchVkPublicFeedItem, likeVkFeed, fetchVkGenerationClaim, generateVkImage, previewAccountLink, saveAccountPreviewSettings, startAccountAppSession, stopAccountAppSession } from '../shared-account-api'
import { setPlatformSessionToken } from '../api'
import { platformMiniAppUrl } from '../account-platform'

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

test('native generation claim read uses signed VK identity with no actor override', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'r'.repeat(43), account: { id: 'owned-account' } }))
    .mockResolvedValueOnce(reply(200, {
      found: true, task_id: 73, task_type: 'photo', status: 'processing', cost: 3,
      prompt: 'DO NOT DISCLOSE PRIVATE RECIPE',
    })).mockResolvedValueOnce(reply(200))
  await expect(fetchVkGenerationClaim('vk_native_claim_replay_000001')).resolves.toEqual({
    ok: true, found: true, task_id: 73, task_type: 'photo', status: 'processing', cost: 3,
  })
  expect(fetch.mock.calls[1][0]).toBe('/mini-app/api/account-preview/vk-generation-claim')
  expect(JSON.parse(String(fetch.mock.calls[1][1]?.body)))
    .toEqual({ client_request_id: 'vk_native_claim_replay_000001' })
  expect(fetch.mock.calls[1][1]?.headers).toEqual(expect.objectContaining({
    Authorization: 'Bearer ' + 'r'.repeat(43),
  }))
  expect(fetch.mock.calls.every(([url]) => !String(url).includes('r'.repeat(43)))).toBe(true)
})

test('malformed native generation claim never authorizes unknown task or owner', async () => {
  const fetch = jest.mocked(global.fetch)
  await expect(fetchVkGenerationClaim('bad')).rejects.toThrow('Некорректный идентификатор')
  expect(fetch).not.toHaveBeenCalled()
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'r'.repeat(43), account: { id: 'owned-account' } }))
    .mockResolvedValueOnce(reply(200, {
      found: true, task_id: 0, task_type: 'photo', status: 'processing', cost: 3,
    })).mockResolvedValueOnce(reply(200))
  await expect(fetchVkGenerationClaim('vk_native_claim_replay_000001')).rejects
    .toThrow('Невозможно безопасно подтвердить статус')
  expect(fetch).toHaveBeenCalledTimes(3)
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
      vk_community_id: 239915802,
      telegram_bot_username: 'Neuromixx_bot',
      telegram_linked: false,
    },
  })).mockResolvedValueOnce(reply(200, {
    registered: true, balance: 12.5, is_blocked: false, tasks: [],
  })).mockResolvedValueOnce(reply(200))

  const access = await startAccountAppSession()
  expect(access.telegram_linked).toBe(false)
  expect(platformMiniAppUrl('prompt_2534')).toBe('https://vk.com/app123_-239915802#prompt_2534')
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
  expect(platformMiniAppUrl('prompt_2534')).toBe('https://vk.com/app123#prompt_2534')
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


test('native invoice transport never sends browser actor IDs or Telegram wallet fields', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'a'.repeat(43), account: { id: 'vk-actor' } }))
    .mockResolvedValueOnce(reply(200, {
      status: 'ready', amount_rub: 250, credits: 25, payment_url: 'https://lava.top/p/1',
    }))
    .mockResolvedValueOnce(reply(200))
  const input = { package_id: '250', payment_method: 'CARD' as const,
    customer_email: 'user@gmail.com', client_request_id: 'abc123def456xyz789' }
  await expect(createVkInvoice(input)).resolves.toEqual(expect.objectContaining({ status: 'ready' }))
  expect(fetch.mock.calls[1][0]).toBe('/mini-app/api/account-preview/vk-invoice')
  const body = JSON.parse(String(fetch.mock.calls[1][1]?.body))
  expect(body).toEqual(input)
  expect(body).not.toHaveProperty('user_id')
  expect(fetch.mock.calls[1][1]?.headers).toEqual(
    expect.objectContaining({ Authorization: 'Bearer ' + 'a'.repeat(43) }),
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


test('VK feed publication lookup is distinct from an editorial trend recipe', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'a'.repeat(43), account: { id: 'vk-actor' } }))
    .mockResolvedValueOnce(reply(200, {
      item: { id: 370766, generation_type: 'video', model: 'seedance_2_5',
        preview_url: 'https://assets.example/preview.mp4', result_url: 'https://assets.example/result.mp4',
        share_link: 'https://vk.com/app123#feed_370766', can_repeat_in_app: false },
    }))
    .mockResolvedValueOnce(reply(200))
  const data = await fetchVkPublicFeedItem(370766)
  expect(data.item.generation_type).toBe('video')
  expect(data.item.share_link).toContain('#feed_370766')
  expect(fetch.mock.calls[1][0]).toBe('/mini-app/api/account-preview/trends?view=feed_item&gen_id=370766')
  expect(fetch.mock.calls[1][1]?.headers).toEqual(
    expect.objectContaining({ Authorization: 'Bearer ' + 'a'.repeat(43) }),
  )
  expect(fetch.mock.calls[2][0]).toBe('/mini-app/api/account-preview/logout')
  expect(fetch.mock.calls.map(([url]) => String(url))).not.toEqual(
    expect.arrayContaining([expect.stringContaining('view=item&trend_id=')]),
  )
  await expect(fetchVkPublicFeedItem(0)).rejects.toThrow('Некорректная публикация')
})

test('VK feed and trend start parameters remain disjoint even when IDs match', async () => {
  const { parseMiniAppStartParam, startParamFromLocation } = await import('../start-params')
  expect(parseMiniAppStartParam('feed_370766_ref_27QT0YCB')).toEqual({
    kind: 'feed', genId: 370766, referralCodeForAttribution: '27QT0YCB',
  })
  expect(parseMiniAppStartParam('remix_370766_ref_27QT0YCB')).toEqual({
    kind: 'remix', genId: 370766, referralCodeForAttribution: '27QT0YCB',
  })
  expect(parseMiniAppStartParam('prompt_370766_ref_27QT0YCB')).toEqual({
    kind: 'prompt', promptId: 370766, referralCodeForAttribution: '27QT0YCB',
  })
  expect(startParamFromLocation('?vk_app_id=54880352&vk_user_id=1&sign=secret',
    '#feed_370766_ref_27QT0YCB')).toBe('feed_370766_ref_27QT0YCB')
})

test('signed public feed HTTP 404 gives a publication-specific error and revokes the session', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'a'.repeat(43), account: { id: 'vk-actor' } }))
    .mockResolvedValueOnce(reply(404, { error: 'Публикация не найдена' }))
    .mockResolvedValueOnce(reply(200))
  await expect(fetchVkPublicFeedItem(370766)).rejects.toThrow('Публикация не найдена')
  expect(fetch.mock.calls[1][0]).toBe('/mini-app/api/account-preview/trends?view=feed_item&gen_id=370766')
  expect(fetch.mock.calls[2][0]).toBe('/mini-app/api/account-preview/logout')
  expect(fetch.mock.calls.map(([url]) => String(url))).not.toEqual(
    expect.arrayContaining([expect.stringContaining('view=item&trend_id=')]),
  )
})

test('overlapping signed VK logins cannot install an older response over the newer actor', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=456&vk_ts=1000&sign=verified')
  const aToken = 'a'.repeat(43)
  const bToken = 'b'.repeat(43)
  let resolveOldSession!: (response: Response) => void
  const oldSession = new Promise<Response>(resolve => { resolveOldSession = resolve })
  const calls: string[] = []
  let logins = 0
  jest.mocked(global.fetch).mockImplementation(async (input, options) => {
    const url = String(input)
    const token = String((options?.headers as Record<string, string>)?.Authorization || '')
    calls.push(url + ' ' + token)
    if (url.endsWith('/session')) {
      logins += 1
      return logins === 1
        ? oldSession
        : reply(200, { session_token: bToken, account: { id: 'new-vk-owner' } })
    }
    if (url.endsWith('/me')) {
      return reply(200, {
        account: { id: token === 'Bearer ' + aToken ? 'old-vk-owner' : 'new-vk-owner' },
        preview: { revision: 1, vk_app_id: 123, telegram_linked: false, telegram_bot_username: 'test_bot' },
      })
    }
    if (url.endsWith('/vk-native-state')) {
      return reply(200, { registered: true, balance: token === 'Bearer ' + bToken ? 21 : 999, tasks: [] })
    }
    return reply(200)
  })
  const older = startAccountAppSession()
  const newer = startAccountAppSession()
  const access = await newer
  expect(access.telegram_linked).toBe(false)
  resolveOldSession(reply(200, { session_token: aToken, account: { id: 'old-vk-owner' } }))
  await expect(older).rejects.toThrow()
  const state = await fetchVkNativeState()
  expect(state.balance).toBe(21)
  expect(calls.filter(value => value.includes('/logout'))).toEqual([
    expect.stringContaining('Bearer ' + aToken),
  ])
  expect(calls.some(value => value.includes('Bearer ' + bToken) && value.includes('/logout'))).toBe(false)
  await stopAccountAppSession()
  expect(calls.filter(value => value.includes('/logout'))).toHaveLength(2)
})

test('aborted old VK profile response cannot overwrite another active VK session', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=456&vk_ts=1000&sign=verified')
  const aToken = 'c'.repeat(43)
  const bToken = 'd'.repeat(43)
  let resolveOldProfile!: (response: Response) => void
  const oldProfile = new Promise<Response>(resolve => { resolveOldProfile = resolve })
  const loggedOut: string[] = []
  let logins = 0
  jest.mocked(global.fetch).mockImplementation(async (input, options) => {
    const url = String(input)
    const token = String((options?.headers as Record<string, string>)?.Authorization || '')
    if (url.endsWith('/session')) {
      logins += 1
      return reply(200, {
        session_token: logins === 1 ? aToken : bToken,
        account: { id: logins === 1 ? 'old-owner' : 'new-owner' },
      })
    }
    if (url.endsWith('/me')) return token === 'Bearer ' + aToken ? oldProfile : reply(200, {
      account: { id: 'new-owner' },
      preview: { revision: 1, vk_app_id: 123, telegram_linked: false, telegram_bot_username: 'test_bot' },
    })
    if (url.endsWith('/logout')) { loggedOut.push(token); return reply(200) }
    if (url.endsWith('/vk-native-state')) return reply(200, { balance: token === 'Bearer ' + bToken ? 5 : -1, registered: true, tasks: [] })
    return reply(200)
  })
  const controller = new AbortController()
  const first = startAccountAppSession(controller.signal)
  // Wait until the first request reaches its profile read.
  await Promise.resolve()
  await Promise.resolve()
  controller.abort()
  await stopAccountAppSession()
  await startAccountAppSession()
  resolveOldProfile(reply(200, {
    account: { id: 'old-owner' },
    preview: { revision: 1, vk_app_id: 123, telegram_linked: false, telegram_bot_username: 'test_bot' },
  }))
  await expect(first).rejects.toThrow()
  expect((await fetchVkNativeState()).balance).toBe(5)
  expect(loggedOut).toContain('Bearer ' + aToken)
  expect(loggedOut).not.toContain('Bearer ' + bToken)
  await stopAccountAppSession()
})

test('unmount invalidates a pending VK login even if the server ignores abort', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=456&vk_ts=1000&sign=verified')
  const token = 'e'.repeat(43)
  let resolveSession!: (response: Response) => void
  const pending = new Promise<Response>(resolve => { resolveSession = resolve })
  const logouts: string[] = []
  jest.mocked(global.fetch).mockImplementation(async (input, options) => {
    const url = String(input)
    if (url.endsWith('/session')) return pending
    if (url.endsWith('/logout')) {
      logouts.push(String((options?.headers as Record<string, string>)?.Authorization))
      return reply(200)
    }
    throw new Error('Stale session must not call profile or paid VK API')
  })
  const opened = startAccountAppSession()
  await stopAccountAppSession()
  resolveSession(reply(200, { session_token: token, account: { id: 'stale-vk-owner' } }))
  await expect(opened).rejects.toThrow()
  expect(logouts).toEqual(['Bearer ' + token])
  await stopAccountAppSession()
})

test('native VK feed like sends signed owner session and publication id only', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, {
    session_token: 'v'.repeat(43), account: { id: 'native-vk-account' },
  })).mockResolvedValueOnce(reply(200, {
    liked: true, likes_count: 8,
  })).mockResolvedValueOnce(reply(200))
  await expect(likeVkFeed(41)).resolves.toEqual({
    ok: true, liked: true, likes_count: 8,
  })
  expect(fetch.mock.calls[1][0]).toBe('/mini-app/api/account-preview/vk-feed-like')
  expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toEqual({ feed_gen_id: 41 })
  expect(fetch.mock.calls[1][1]?.headers).toEqual(expect.objectContaining({
    Authorization: 'Bearer ' + 'v'.repeat(43),
  }))
  expect(fetch.mock.calls[2][0]).toBe('/mini-app/api/account-preview/logout')
})

test('invalid VK publication reaction is rejected before network access', async () => {
  await expect(likeVkFeed(-1)).rejects.toThrow('Некорректная публикация')
  expect(global.fetch).not.toHaveBeenCalled()
})
