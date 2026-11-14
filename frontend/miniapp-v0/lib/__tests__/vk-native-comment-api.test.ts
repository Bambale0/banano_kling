import { postVkPublicFeedComment } from '../shared-account-api'
import { getApiBasePath, getInitData } from '../api'

jest.mock('../api', () => ({
  getApiBasePath: jest.fn(() => '/mini-app/api'),
  getInitData: jest.fn(() => 'signed-native-vk-launch'),
  setPlatformSessionToken: jest.fn(),
  clearPlatformSessionToken: jest.fn(),
}))

function reply(status: number, extra: Record<string, unknown> = {}) {
  return { status, ok: status === 200, json: async () => ({ ok: status === 200, ...extra }) } as Response
}
const key = 'vk_comment_client_000000000001'
beforeEach(() => {
  jest.clearAllMocks()
  global.fetch = jest.fn()
})
test('native VK writer signs with its own session and sends no Telegram identity', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'session-vk', account: { id: 'native' } }))
    .mockResolvedValueOnce(reply(200, {
      comments_count: 2, comment: {
        id: 'vk:11', gen_id: 41, text: 'Привет', author: 'Участник ВКонтакте',
        is_mine: true, created_at: '2026-11-14',
      },
    })).mockResolvedValueOnce(reply(200))
  const result = await postVkPublicFeedComment(41, ' Привет ', key)
  expect(result.comment.id).toBe('vk:11')
  expect(fetch.mock.calls[1][0]).toBe('/mini-app/api/account-preview/vk-feed-comment')
  expect(fetch.mock.calls[1][1]?.method).toBe('POST')
  expect(fetch.mock.calls[1][1]?.headers).toEqual(expect.objectContaining({
    Authorization: 'Bearer session-vk',
  }))
  const body = JSON.parse(String(fetch.mock.calls[1][1]?.body))
  expect(body).toEqual({ feed_gen_id: 41, text: 'Привет', client_request_id: key })
  expect(JSON.stringify(body)).not.toMatch(/telegram_id|user_id|shared_account_id|price/)
  expect(fetch.mock.calls.every(([url]) => !String(url).includes('session-vk'))).toBe(true)
  expect(getApiBasePath).toHaveBeenCalled()
  expect(getInitData).toHaveBeenCalled()
})

test.each([0, -4, 1.5, Number.NaN, 2 ** 54])(
  'invalid feed %s never obtains or leaks a signed session', async id => {
    await expect(postVkPublicFeedComment(id, 'Слово', key)).rejects.toThrow('Некорректная публикация')
    expect(global.fetch).not.toHaveBeenCalled()
  },
)

test('native VK write does not retry as a new claim on HTTP 429', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'scoped', account: { id: 'native' } }))
    .mockResolvedValueOnce(reply(429, { error_code: 'comment_rate_limited' }))
    .mockResolvedValueOnce(reply(200))
  await expect(postVkPublicFeedComment(41, 'Привет', key)).rejects.toThrow('Слишком частые комментарии')
  expect(fetch).toHaveBeenCalledTimes(3)
})

test('ambiguous malformed success payload never claims a confirmed comment', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(reply(200, { session_token: 'scoped', account: { id: 'native' } }))
    .mockResolvedValueOnce(reply(200, {
      comments_count: 1, comment: {
        id: 'vk:31', gen_id: 42, author: 'Other actor', is_mine: false,
        text: 'Привет', created_at: '2026-11-14',
      },
    })).mockResolvedValueOnce(reply(200))
  await expect(postVkPublicFeedComment(41, 'Привет', key))
    .rejects.toThrow('Сервер не подтвердил комментарий')
})

test('invalid comment and request key never send anything', async () => {
  await expect(postVkPublicFeedComment(41, 'x'.repeat(501), key)).rejects.toThrow('500')
  await expect(postVkPublicFeedComment(41, 'text', 'bad key')).rejects.toThrow('ключ')
  expect(global.fetch).not.toHaveBeenCalled()
})
