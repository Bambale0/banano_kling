import { repeatFeedVideo } from '../api'

describe('repeatFeedVideo', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    window.history.replaceState({}, '', '/mini-app/')
    const webApp = window.Telegram?.WebApp
    if (!webApp) throw new Error('Telegram WebApp mock is unavailable')
    webApp.initData = 'signed-init-data'
    webApp.initDataUnsafe = { start_param: '' }
  })

  afterEach(() => {
    jest.restoreAllMocks()
    const webApp = window.Telegram?.WebApp
    if (webApp) {
      webApp.initData = 'mock_init_data'
      webApp.initDataUnsafe = { start_param: '' }
    }
  })

  it('sends only the source id so the server restores the private video recipe', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({
        ok: true,
        status: 'queued',
        task_id: 'repeat-task-1',
        task_type: 'video',
        credits: 88,
        cost: 12,
        model: 'seedance_2_5',
        model_label: 'Seedance 2.5',
        aspect_ratio: '9:16',
        duration: 12,
        scenario: 'multimodal',
        prompt_hidden: true,
        prompt_actions_allowed: false,
        source_feed_gen_id: 42,
      }),
    })
    global.fetch = fetchMock as unknown as typeof fetch

    const result = await repeatFeedVideo(42)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/mini-app/api/generate-video')
    expect(options.method).toBe('POST')
    expect(JSON.parse(String(options.body))).toEqual({
      init_data: 'signed-init-data',
      source_feed_gen_id: 42,
    })
    expect(result.task.model).toBe('seedance_2_5')
    expect(result.task.aspect_ratio).toBe('9:16')
    expect(result.task.prompt_hidden).toBe(true)
  })
})
