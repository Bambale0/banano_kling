import { bootstrapApp } from '../api'

const originalFetch = global.fetch
beforeEach(() => {
  jest.useFakeTimers()
  sessionStorage.clear()
  window.Telegram = { WebApp: { initData: 'query_id=synthetic' } }
})
afterEach(() => { jest.useRealTimers(); global.fetch = originalFetch; delete window.Telegram })

test('a stalled bootstrap is aborted and rejected instead of leaving the loader forever', async () => {
  let transportSignal: AbortSignal | undefined
  global.fetch = jest.fn((_url, options) => new Promise((_resolve, reject) => {
    transportSignal = options?.signal as AbortSignal
    transportSignal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  })) as typeof fetch
  let error: Error | undefined
  const pending = bootstrapApp().catch(value => { error = value })
  await jest.advanceTimersByTimeAsync(15_001)
  expect(transportSignal?.aborted).toBe(true)
  expect(error?.name).toBe('BootstrapTimeoutError')
  await pending
})

test('deadline includes a response whose body never finishes', async () => {
  global.fetch = jest.fn(async (_url, options) => ({ ok: true, status: 200,
    headers: { get: () => 'application/json' },
    text: () => new Promise((_resolve, reject) => options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))),
  })) as unknown as typeof fetch
  let error: Error | undefined
  const pending = bootstrapApp().catch(value => { error = value })
  await jest.advanceTimersByTimeAsync(15_001)
  expect(error?.name).toBe('BootstrapTimeoutError')
  await pending
})

test('caller cancellation remains cancellation and clears the deadline', async () => {
  global.fetch = jest.fn((_url, options) => new Promise((_resolve, reject) => {
    options?.signal?.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError')))
  })) as typeof fetch
  const caller = new AbortController()
  const pending = bootstrapApp(caller.signal)
  caller.abort()
  await expect(pending).rejects.toHaveProperty('name', 'AbortError')
  expect(jest.getTimerCount()).toBe(0)
})

test('successful bootstrap clears its deadline without aborting a completed request', async () => {
  let requestSignal: AbortSignal | undefined
  global.fetch = jest.fn(async (_url, options) => {
    requestSignal = options?.signal as AbortSignal
    return { ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ ok: true, recent_tasks: [] }) }
  }) as unknown as typeof fetch
  await expect(bootstrapApp()).resolves.toHaveProperty('ok', true)
  await jest.advanceTimersByTimeAsync(20_000)
  expect(requestSignal?.aborted).not.toBe(true)
  expect(jest.getTimerCount()).toBe(0)
})

test('expired authentication remains distinguishable from a network timeout', async () => {
  global.fetch = jest.fn(async () => ({ ok: false, status: 401, headers: { get: () => 'application/json' },
    text: async () => JSON.stringify({ ok: false, error: 'Expired synthetic init data' }),
  })) as unknown as typeof fetch
  await expect(bootstrapApp()).rejects.toHaveProperty('status', 401)
  expect(jest.getTimerCount()).toBe(0)
})
