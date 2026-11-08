import { fetchVkChatDelivery, requestVkChatDelivery } from '../shared-account-api'
import { setPlatformSessionToken } from '../api'

jest.mock('../api', () => ({
  getApiBasePath: () => '/mini-app/api', getInitData: () => 'must-not-use-telegram',
  setPlatformSessionToken: jest.fn(), clearPlatformSessionToken: jest.fn(),
}))
function reply(status: number, payload = {}) {
  return { status, ok: status === 200, json: async () => ({ ok: status === 200, ...payload }) } as Response
}
const login = () => reply(200, { session_token: 'operation-only-vk-session', account: { id: 'owner' } })

beforeEach(() => {
  jest.resetAllMocks()
  global.fetch = jest.fn()
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001&sign=signed-vk')
})
afterEach(() => { window.history.replaceState({}, '', '/') })

test('status is read-only and uses an operation VK session, never a token URL', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(login()).mockResolvedValueOnce(reply(200, { delivery: { state: 'delivered', community_id: 456, can_request: false } }))
    .mockResolvedValueOnce(reply(200))
  expect((await fetchVkChatDelivery('task-one')).state).toBe('delivered')
  expect(JSON.parse(String(fetch.mock.calls[0][1]?.body)).platform).toBe('vk')
  expect(fetch.mock.calls[1][1]?.method).toBe('GET')
  expect(fetch.mock.calls[1][1]?.headers).toEqual(expect.objectContaining({ Authorization: 'Bearer operation-only-vk-session' }))
  expect(fetch.mock.calls.every(([url]) => !String(url).includes('operation-only-vk-session'))).toBe(true)
  expect(fetch.mock.calls.at(-1)?.[0]).toBe('/mini-app/api/account-preview/logout')
  expect(setPlatformSessionToken).not.toHaveBeenCalled()
})

test('owner acceptance contains no selectable recipient, result or platform', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(login()).mockResolvedValueOnce(reply(200, { delivery: { state: 'pending', community_id: 456, can_request: false } }))
    .mockResolvedValueOnce(reply(200))
  await requestVkChatDelivery('task-one')
  expect(fetch.mock.calls[1][1]?.method).toBe('POST')
  expect(fetch.mock.calls[1][1]?.body).toBe('{}')
})

test('uncertain receipt conflict keeps the check-chat instruction and revokes its session', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(login()).mockResolvedValueOnce(reply(409, { error_code: 'vk_delivery_uncertain' })).mockResolvedValueOnce(reply(200))
  await expect(requestVkChatDelivery('task-one')).rejects.toThrow('ВК не подтвердил отправку')
  expect(fetch.mock.calls.at(-1)?.[0]).toBe('/mini-app/api/account-preview/logout')
})

test('unknown state cannot fabricate a delivered receipt', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(login()).mockResolvedValueOnce(reply(200, { delivery: { state: 'guessed', community_id: 456, can_request: false } }))
    .mockResolvedValueOnce(reply(200))
  await expect(fetchVkChatDelivery('task-one')).rejects.toThrow('Не удалось прочитать статус')
})

test('an unavailable task uses neutral recovery text without claiming preview was disabled', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(login()).mockResolvedValueOnce(reply(404)).mockResolvedValueOnce(reply(200))
  await expect(fetchVkChatDelivery('stale-task')).rejects.toThrow('Результат или доставка сейчас недоступны')
})
