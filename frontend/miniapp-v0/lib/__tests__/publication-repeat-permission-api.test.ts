import { publishGeneration } from '@/lib/api'

describe('publishGeneration private repeat consent transport', () => {
  const originalFetch = global.fetch
  const fetchMock = jest.fn()

  beforeEach(() => {
    fetchMock.mockReset().mockResolvedValue({
      ok: true,
      headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ ok: true, feed_item: { task_id: 'image-task' } }),
    })
    global.fetch = fetchMock
    window.sessionStorage.clear()
    window.history.replaceState({}, '', '/mini-app/')
  })

  afterAll(() => { global.fetch = originalFetch })

  it('sends separate source indices for repeat permission without reference URLs', async () => {
    await publishGeneration('image-task', {
      referencesVisible: false,
      referenceImageIndices: [1],
      referenceVideoIndices: [],
      repeatReferenceImageIndices: [4],
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/mini-app/api/generations/share')
    expect(options.method).toBe('POST')
    expect(JSON.parse(String(options.body))).toEqual({
      init_data: 'mock_init_data',
      task_id: 'image-task',
      prompt_visible: false,
      references_visible: false,
      reference_image_indices: [1],
      reference_video_indices: [],
      repeat_reference_image_indices: [4],
      feed_blurred: false,
      publication_scope: 'feed',
      adult_content: false,
    })
  })

  it('sends separate typed video consent indices without source URLs', async () => {
    await publishGeneration('video-task', { repeatReferenceImageIndices: [2], repeatReferenceVideoIndices: [5] })
    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body))
    expect(body.repeat_reference_image_indices).toEqual([2])
    expect(body.repeat_reference_video_indices).toEqual([5])
  })

  it('sends an explicit empty array to revoke consent', async () => {
    await publishGeneration('image-task', { repeatReferenceImageIndices: [] })
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body)).repeat_reference_image_indices).toEqual([])
  })

  it('does not add repeat consent for callers that omit the option', async () => {
    await publishGeneration('legacy-or-video-task', { referencesVisible: true })
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).not.toHaveProperty('repeat_reference_image_indices')
  })
})
