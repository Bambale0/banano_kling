import {
  generateWan3Prime,
  importWan3PrimeReference,
  quoteWan3Prime,
  uploadWan3PrimeReference,
} from '../wan3-prime-api'

jest.mock('../api', () => ({
  getApiBasePath: () => '/mini-app/api',
  getInitData: () => 'signed-init-data',
  getStartParamFallback: () => 'start-ref',
}))

const fetchMock = jest.fn()

beforeEach(() => {
  fetchMock.mockReset()
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
    .mockResolvedValueOnce(jsonResponse({ ok: true, upload_id: 'up1', chunk_size: 5 }))
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
