import { confirmTelegramWriteAccess } from '../api'

const fetchMock = jest.fn()
beforeEach(() => {
  fetchMock.mockReset()
  global.fetch = fetchMock
  window.Telegram!.WebApp!.initData = 'synthetic-signed-permission'
  window.Telegram!.WebApp!.initDataUnsafe = { start_param: 'feed_47_ref_PARTNER' }
})

test('native confirmation preserves signed auth, original referral launch and cancellation', async () => {
  const body = { ok: true, chat_available: true, confirmation_sent: true, needs_bot_start: false }
  fetchMock.mockResolvedValue({ ok: true, status: 200, headers: { get: () => 'application/json' }, json: async () => body, text: async () => JSON.stringify(body) })
  const controller = new AbortController()
  await expect(confirmTelegramWriteAccess(controller.signal)).resolves.toEqual(body)
  expect(fetchMock.mock.calls[0][0]).toMatch(/\/write-access$/)
  expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal)
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ init_data: 'synthetic-signed-permission', granted: true, start_param_fallback: 'feed_47_ref_PARTNER' })
})
