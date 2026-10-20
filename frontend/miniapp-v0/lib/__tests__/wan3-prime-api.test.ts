import {
  generateWan3Prime,
  importWan3PrimeReference,
  quoteWan3Prime,
  uploadWan3PrimeReference,
  WAN3_PRIME_MEDIA_TIMEOUT_MS,
} from '../wan3-prime-api'

jest.mock('../api', () => ({
  getApiBasePath: () => '/mini-app/api',
  getInitData: () => 'signed-init-data',
  getStartParamFallback: () => 'start-ref',
}))

const fetchMock = jest.fn()
const UPLOAD_ID = '00000000000000000000000000000001'

beforeEach(() => {
  fetchMock.mockReset()
  jest.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-0000-0000-000000000001')
  ;(global as any).fetch = fetchMock
})

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name: string) => name.toLowerCase() === 'content-type' ? 'application/json' : '' },
    text: async () => JSON.stringify(payload),
  } as Response
}

test('quotes through the dedicated Wan endpoint with init data and complete recipe', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({
    ok: true,
    quote_hash: 'qh',
    reserve_cost: 30,
    billing_duration_seconds: 30,
    source_video_duration_seconds: 0,
    tariff_missing: false,
    admin_free: false,
    auto_duration: true,
  }))

  await quoteWan3Prime({
    client_request_id: 'client-1',
    recipe: {
      model: 'wan_3_prime',
      scenario: 'reference',
      prompt: '',
      resolution: '1080P',
      aspect_ratio: 'adaptive',
      duration: -1,
      audio: false,
      nsfw_checker: true,
      seed: 0,
      reference_audio_urls: ['https://cdn.test/a.mp3'],
    },
  })

  expect(fetchMock.mock.calls[0][0]).toBe('/mini-app/api/wan3/quote')
  const body = JSON.parse(fetchMock.mock.calls[0][1].body)
  expect(body.init_data).toBe('signed-init-data')
  expect(body.start_param_fallback).toBe('start-ref')
  expect(body.client_request_id).toBe('client-1')
  expect(body.recipe.seed).toBe(0)
  expect(body.recipe.audio).toBe(false)
  expect(body.recipe.reference_audio_urls).toEqual(['https://cdn.test/a.mp3'])
})

test('generate sends idempotency and quote hash without falling through generic video endpoint', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({
    ok: true,
    status: 'queued',
    internal_task_id: 'wan-internal',
    reserve_cost: 12,
  }))

  await generateWan3Prime({
    client_request_id: 'client-2',
    idempotency_key: 'idem-2',
    quote_hash: 'quote-2',
    recipe: {
      model: 'wan_3_prime',
      scenario: 'edit',
      prompt: 'Change the jacket.',
      resolution: '720P',
      aspect_ratio: '9:16',
      duration: 8,
      audio: true,
      nsfw_checker: false,
      reference_video_urls: ['https://cdn.test/source.mp4'],
    },
  })

  expect(fetchMock.mock.calls[0][0]).toBe('/mini-app/api/wan3/generate')
  const body = JSON.parse(fetchMock.mock.calls[0][1].body)
  expect(body.idempotency_key).toBe('idem-2')
  expect(body.quote_hash).toBe('quote-2')
  expect(body.recipe.scenario).toBe('edit')
})

test('import validates public Wan references through the dedicated route', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({
    ok: true,
    kind: 'link',
    url: 'https://example.test/page',
  }))

  await importWan3PrimeReference('link', 'https://example.test/page')

  expect(fetchMock.mock.calls[0][0]).toBe('/mini-app/api/wan3/import')
  expect(JSON.parse(fetchMock.mock.calls[0][1].body).kind).toBe('link')
})

test('chunk upload uses Wan limits and preserves large video capability', async () => {
  fetchMock
    .mockResolvedValueOnce(jsonResponse({ ok: true, upload_id: UPLOAD_ID, chunk_size: 5 }))
    .mockResolvedValueOnce(jsonResponse({ ok: true }))
    .mockResolvedValueOnce(jsonResponse({ ok: true }))
    .mockResolvedValueOnce(jsonResponse({
      ok: true,
      url: 'https://cdn.test/video.mp4',
      kind: 'video',
      filename: 'video.mp4',
      size: 10,
    }))

  const file = new File(['0123456789'], 'video.mp4', { type: 'video/mp4' })
  const uploaded = await uploadWan3PrimeReference('video', file)

  expect(uploaded.url).toBe('https://cdn.test/video.mp4')
  expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
    '/mini-app/api/wan3/upload/init',
    '/mini-app/api/wan3/upload/chunk',
    '/mini-app/api/wan3/upload/chunk',
    '/mini-app/api/wan3/upload/complete',
  ])
})

test('upload reports acknowledged chunk progress and keeps original Cyrillic filenames in the unchanged protocol', async () => {
  fetchMock
    .mockResolvedValueOnce(jsonResponse({ ok: true, upload_id: UPLOAD_ID, chunk_size: 5 }))
    .mockResolvedValueOnce(jsonResponse({ ok: true }))
    .mockResolvedValueOnce(jsonResponse({ ok: true }))
    .mockResolvedValueOnce(jsonResponse({ ok: true, url: 'https://cdn.test/upload.mov', kind: 'video', filename: 'upload.mov', size: 10 }))
  const controller = new AbortController()
  const progress = jest.fn()
  const result = await uploadWan3PrimeReference('video', new File(['0123456789'], 'Видео.mov', { type: 'video/quicktime' }), controller.signal, progress)
  expect(progress.mock.calls).toEqual([[0, 10], [5, 10], [10, 10]])
  expect(JSON.parse(fetchMock.mock.calls[0][1].body).filename).toBe('Видео.mov')
  expect(fetchMock.mock.calls[1][1].body.get('chunk').name).toBe('Видео.mov')
  expect(fetchMock.mock.calls.every(call => call[1].signal instanceof AbortSignal)).toBe(true)
  expect(result.url).toBe('https://cdn.test/upload.mov')
})

test.each(['init', 'chunk', 'complete'])('aborting %s captures init then awaits cancellation and discards late media', async stage => {
  let finish: (response: Response) => void = () => {}
  let pendingSignal: AbortSignal | undefined
  fetchMock.mockImplementation((url, options) => {
    if (url.endsWith('/cancel')) return Promise.resolve(jsonResponse({ ok: true, status: 'cancelled' }))
    if (url.endsWith(`/${stage}`)) {
      pendingSignal = options.signal
      return new Promise(resolve => { finish = resolve })
    }
    return Promise.resolve(jsonResponse({ ok: true, upload_id: UPLOAD_ID, chunk_size: 10 }))
  })
  const controller = new AbortController()
  const promise = uploadWan3PrimeReference('image', new File(['01234'], 'Фото.jpg', { type: 'image/jpeg' }), controller.signal)
  const rejected = expect(promise).rejects.toMatchObject({ name: 'AbortError' })
  for (let turn = 0; turn < 20 && !pendingSignal; turn += 1) await Promise.resolve()
  expect(pendingSignal).toBeDefined()
  const count = fetchMock.mock.calls.length
  controller.abort()
  if (stage === 'init') {
    expect(pendingSignal?.aborted).toBe(false)
    finish(jsonResponse({ ok: true, upload_id: UPLOAD_ID, chunk_size: 10 }))
  }
  await rejected
  expect(pendingSignal?.aborted).toBe(stage !== 'init')
  finish(jsonResponse({ ok: true, url: 'https://cdn.test/late.jpg', kind: 'image', filename: 'late.jpg' }))
  await Promise.resolve(); await Promise.resolve()
  expect(fetchMock).toHaveBeenCalledTimes(count + 1)
  expect(fetchMock.mock.calls.at(-1)[0]).toBe('/mini-app/api/wan3/upload/cancel')
})

test('a stalled chunk times out, aborts its request and exposes a retryable error', async () => {
  jest.useFakeTimers()
  try {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: true, upload_id: UPLOAD_ID, chunk_size: 5 }))
      .mockImplementationOnce(() => new Promise(() => {}))
      .mockResolvedValueOnce(jsonResponse({ ok: true, status: 'cancelled' }))
    const result = uploadWan3PrimeReference('image', new File(['012345'], 'Фото.jpg', { type: 'image/jpeg' }))
    const rejected = expect(result).rejects.toThrow('Сервер не ответил за 15 минут')
    await jest.advanceTimersByTimeAsync(WAN3_PRIME_MEDIA_TIMEOUT_MS)
    await rejected
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[1][1].signal.aborted).toBe(true)
    expect(jest.getTimerCount()).toBe(0)
  } finally { jest.useRealTimers() }
})

test('large multi-chunk files receive a fresh timeout budget per request', async () => {
  jest.useFakeTimers()
  try {
    fetchMock.mockImplementation((url: string) => new Promise(resolve => setTimeout(() => resolve(jsonResponse(
      url.endsWith('/init') ? { ok: true, upload_id: UPLOAD_ID, chunk_size: 5 }
        : url.endsWith('/complete') ? { ok: true, url: 'https://cdn.test/video.mov', kind: 'video', filename: 'Видео.mov', size: 10 }
          : { ok: true },
    )), WAN3_PRIME_MEDIA_TIMEOUT_MS - 1)))
    const result = uploadWan3PrimeReference('video', new File(['0123456789'], 'Видео.mov', { type: 'video/quicktime' }))
    await jest.runAllTimersAsync()
    await expect(result).resolves.toMatchObject({ url: 'https://cdn.test/video.mov' })
    expect(fetchMock).toHaveBeenCalledTimes(4)
    expect(jest.getTimerCount()).toBe(0)
  } finally { jest.useRealTimers() }
})

test('cancelled import keeps its request abortable without altering the import body', async () => {
  fetchMock.mockImplementation(() => new Promise(() => {}))
  const controller = new AbortController()
  const imported = importWan3PrimeReference('link', 'https://example.test/page', controller.signal)
  const rejected = expect(imported).rejects.toMatchObject({ name: 'AbortError' })
  controller.abort()
  await rejected
  expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true)
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ kind: 'link', url: 'https://example.test/page' })
})
