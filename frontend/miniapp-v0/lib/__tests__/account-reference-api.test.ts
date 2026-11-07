import {
  fetchAccountReferencePhotos, removeAccountReferencePhoto, saveAccountReferencePhoto,
} from '../shared-account-api'
import { setPlatformSessionToken } from '../api'

jest.mock('../api', () => ({
  getApiBasePath: () => '/mini-app/api', getInitData: () => 'telegram-data-must-not-be-used',
  setPlatformSessionToken: jest.fn(), clearPlatformSessionToken: jest.fn(),
}))

const item = { id: 'a'.repeat(32), mime: 'image/png', width: 3, height: 2, size_bytes: 78, created_at_epoch: 123 }
const blob = new Blob(['synthetic test image'], { type: 'image/png' })
function reply(status: number, payload = {}) {
  return { status, ok: status === 200, json: async () => ({ ok: status === 200, ...payload }) } as Response
}
function thumbnail(contentType = 'image/png') {
  return { status: 200, ok: true, headers: { get: () => contentType }, blob: async () => blob } as unknown as Response
}
function login() { return reply(200, { session_token: 'private-photo-session', account: { id: 'owner' } }) }

beforeEach(() => {
  jest.clearAllMocks()
  global.fetch = jest.fn()
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001&vk_ts=1000&sign=signed-vk')
})
afterEach(() => { window.history.replaceState({}, '', '/') })

test('VK photo upload uses multipart and acknowledges persistence before loading previews', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(login()).mockResolvedValueOnce(reply(200, { reference: item }))
    .mockResolvedValueOnce(reply(200))
  const file = new File(['photo'], 'private-name.png', { type: 'image/png' })
  const uploaded = await saveAccountReferencePhoto(file)
  expect(uploaded.id).toBe(item.id)
  expect(JSON.parse(String(fetch.mock.calls[0][1]?.body)).platform).toBe('vk')
  const request = fetch.mock.calls[1][1]!
  expect((request.body as FormData).get('file')).toBe(file)
  expect(request.headers).not.toHaveProperty('Content-Type')
  expect(fetch.mock.calls[1][1]?.headers).toEqual(expect.objectContaining({ Authorization: 'Bearer private-photo-session' }))
  expect(fetch.mock.calls.every(([url]) => !String(url).includes('private-photo-session'))).toBe(true)
  expect(fetch.mock.calls[2][0]).toBe('/mini-app/api/account-preview/logout')
  expect(setPlatformSessionToken).not.toHaveBeenCalled()
})

test('SPA HTML never becomes an image preview and does not hide saved metadata', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(login()).mockResolvedValueOnce(reply(200, { references: [item], next_offset: null }))
    .mockResolvedValueOnce(thumbnail('text/html')).mockResolvedValueOnce(reply(200))
  const page = await fetchAccountReferencePhotos()
  expect(page.references[0].id).toBe(item.id)
  expect(page.references[0].thumbnail).toBeNull()
})

test('one broken thumbnail keeps the other owned photos and a retryable placeholder', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(login()).mockResolvedValueOnce(reply(200, {
    references: [item, { ...item, id: 'b'.repeat(32) }], next_offset: null,
  })).mockResolvedValueOnce(thumbnail()).mockResolvedValueOnce(reply(404, { error_code: 'reference_unavailable' }))
    .mockResolvedValueOnce(reply(200))
  const page = await fetchAccountReferencePhotos()
  expect(page.references.map(photo => photo.thumbnail)).toEqual([blob, null])
  expect(fetch.mock.calls[2][1]?.headers).toEqual(expect.objectContaining({ Authorization: 'Bearer private-photo-session' }))
  expect(fetch.mock.calls.every(([url]) => !String(url).includes('private-photo-session'))).toBe(true)
  expect(fetch.mock.calls.at(-1)?.[0]).toBe('/mini-app/api/account-preview/logout')
})

test('revoked photo operation shows relaunch guidance and still closes its operation session', async () => {
  const fetch = jest.mocked(global.fetch)
  fetch.mockResolvedValueOnce(login()).mockResolvedValueOnce(reply(401)).mockResolvedValueOnce(reply(200))
  await expect(removeAccountReferencePhoto(item.id)).rejects.toThrow('Откройте приложение заново')
  expect(fetch.mock.calls[2][0]).toBe('/mini-app/api/account-preview/logout')
})

test('a stalled photo list has a deadline and late metadata never starts private media requests', async () => {
  jest.useFakeTimers()
  try {
    let resolve!: (response: Response) => void
    const fetch = jest.mocked(global.fetch)
    fetch.mockResolvedValueOnce(login()).mockReturnValueOnce(new Promise(done => { resolve = done }))
      .mockResolvedValueOnce(reply(200))
    const result = fetchAccountReferencePhotos()
    const rejection = expect(result).rejects.toThrow('Запрос занял слишком много времени')
    await jest.advanceTimersByTimeAsync(60_000)
    await rejection
    expect((fetch.mock.calls[1][1]?.signal as AbortSignal).aborted).toBe(true)
    resolve(reply(200, { references: [item], next_offset: null }))
    await jest.advanceTimersByTimeAsync(0)
    expect(fetch.mock.calls.filter(([url]) => String(url).includes('/thumbnail'))).toHaveLength(0)
    expect(fetch.mock.calls.at(-1)?.[0]).toBe('/mini-app/api/account-preview/logout')
  } finally {
    jest.useRealTimers()
  }
})

test('network failure during private photo login is shown in Russian', async () => {
  jest.mocked(global.fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'))
  await expect(fetchAccountReferencePhotos()).rejects.toThrow('Не удалось связаться с сервером')
})
