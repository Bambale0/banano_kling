import { fetchTrendCatalog } from './trend-catalog-api'

jest.mock('./api', () => ({
  getInitData: () => 'synthetic-signed-init',
  getApiBasePath: () => '/mini-app/api',
  getStartParamFallback: () => '',
}))

describe('trends catalog recovery from stalled network', () => {
  const originalFetch = global.fetch
  afterEach(() => {
    jest.useRealTimers()
    Object.defineProperty(global, 'fetch', { configurable: true, value: originalFetch })
  })

  it('aborts a request whose response never arrives rather than spinning forever', async () => {
    jest.useFakeTimers()
    const mock = jest.fn((_url: string, options: { signal: AbortSignal }) =>
      new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      }))
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    const pending = fetchTrendCatalog(6)
    const check = expect(pending).rejects.toMatchObject({
      name: 'ShowcaseApiError', code: 'timeout',
    })
    await jest.advanceTimersByTimeAsync(12_000)
    await check
    expect(mock).toHaveBeenCalledTimes(1)
  })

  it('does not abort a successfully returned catalog after the request completes', async () => {
    jest.useFakeTimers()
    const mock = jest.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({
        ok: true, categories: [{
          id: 1, title: 'Тренды', emoji: '', sort_order: 0,
          revision: 1, is_visible: true, total: 1, items: [],
        }],
      }),
    })
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    await expect(fetchTrendCatalog(6)).resolves.toHaveLength(1)
    const signal = mock.mock.calls[0][1].signal as AbortSignal
    await jest.advanceTimersByTimeAsync(12_000)
    expect(signal.aborted).toBe(false)
  })
})
