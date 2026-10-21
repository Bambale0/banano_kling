import { fetchTaskHistory } from '../api'

const fetchMock = jest.fn()
const response = (payload: unknown) => ({ ok: true, status: 200, headers: { get: () => 'application/json' }, json: async () => payload, text: async () => JSON.stringify(payload) }) as unknown as Response
beforeEach(() => { fetchMock.mockReset(); global.fetch = fetchMock; window.Telegram!.WebApp!.initData = 'synthetic-signed-history' })

test('owned history sends signed auth, cursor, no-store and caller cancellation', async () => {
  fetchMock.mockResolvedValue(response({ ok: true, recent_tasks: [], next_cursor: null }))
  await fetchTaskHistory('task-8')
  expect(fetchMock.mock.calls[0][0]).toMatch(/\/task-history$/)
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ init_data: 'synthetic-signed-history', cursor: 'task-8' })
  expect(fetchMock.mock.calls[0][1].cache).toBe('no-store')
})

test('a hanging request expires, aborts transport and permits a fresh retry', async () => {
  jest.useFakeTimers()
  try {
    fetchMock.mockImplementationOnce(() => new Promise(() => {})).mockResolvedValueOnce(response({ ok: true, recent_tasks: [], next_cursor: null }))
    const pending = fetchTaskHistory('task-8')
    const failed = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    await jest.advanceTimersByTimeAsync(10_000)
    await failed
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true)
    await expect(fetchTaskHistory('task-8')).resolves.toMatchObject({ recent_tasks: [] })
    expect(jest.getTimerCount()).toBe(0)
  } finally { jest.useRealTimers() }
})

test('caller cancellation settles even if transport ignores abort', async () => {
  fetchMock.mockImplementation(() => new Promise(() => {}))
  const controller = new AbortController()
  const pending = fetchTaskHistory('task-8', controller.signal)
  const failed = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  controller.abort()
  await failed
  expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true)
})

test.each([{ recent_tasks: {}, next_cursor: null }, { recent_tasks: [null], next_cursor: null }, { recent_tasks: [], next_cursor: {} }])('malformed pages fail safely: %j', async payload => {
  fetchMock.mockResolvedValue(response({ ok: true, ...payload }))
  await expect(fetchTaskHistory()).rejects.toThrow('Не удалось загрузить историю.')
})
