import { publishSeedanceTrendUpload, type SeedanceTrendUploadPayload } from '@/lib/seedance-trend-admin-api'

describe('direct Seedance trend publication transport', () => {
  const originalFetch = global.fetch
  const fetchMock = jest.fn()
  const payload: SeedanceTrendUploadPayload = {
    model: 'seedance_2_5', title: 'Private template', description: 'Description',
    promptText: '@Image1 wears @Image2 following @Video1', previewUrl: '/uploads/refs/424242/cover.png', previewType: 'image',
    imageUrls: ['/uploads/refs/424242/face.png', '/uploads/refs/424242/clothes.png'],
    videoUrls: ['/uploads/refs/424242/motion.mp4'], audioUrls: ['/uploads/refs/424242/music.mp3'],
    identityImageIndex: 1, fixedImageIndices: [2], fixedVideoIndices: [], fixedAudioIndices: [1],
    replaceableImageIndices: [], replaceableVideoIndices: [1], replaceableAudioIndices: [],
    duration: 10, aspectRatio: '16:9', userFields: [{ key: 'Имя', label: 'Имя', type: 'text', required: true, max_length: 80 }],
  }

  beforeEach(() => {
    global.fetch = fetchMock
    fetchMock.mockReset().mockResolvedValue({ ok: true, json: async () => ({ ok: true, prompt: { id: 77, prompt_text: '', generation_settings: { reference_count: 2 } } }) })
    window.sessionStorage.clear()
    window.history.replaceState({}, '', '/mini-app/')
    if (window.Telegram?.WebApp) {
      window.Telegram.WebApp.initData = 'signed-init-data'
      window.Telegram.WebApp.initDataUnsafe = { start_param: 'ref_example' }
    }
  })
  afterAll(() => { global.fetch = originalFetch })
  afterEach(() => {
    if (window.Telegram?.WebApp) {
      window.Telegram.WebApp.initData = 'mock_init_data'
      window.Telegram.WebApp.initDataUnsafe = { start_param: '' }
    }
  })

  it('keeps preview distinct and sends ordered typed selections to the admin route', async () => {
    const result = await publishSeedanceTrendUpload(payload)
    expect(result.prompt_text).toBe('')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/mini-app/api/admin/trends/seedance/publish-upload')
    expect(options).toMatchObject({ method: 'POST', credentials: 'same-origin', cache: 'no-store' })
    expect(JSON.parse(options.body)).toEqual({
      init_data: 'signed-init-data', start_param_fallback: 'ref_example',
      model: 'seedance_2_5', title: payload.title, description: payload.description, prompt_text: payload.promptText,
      preview_url: payload.previewUrl, preview_type: 'image', image_urls: payload.imageUrls, video_urls: payload.videoUrls, audio_urls: payload.audioUrls,
      identity_image_index: 1, fixed_image_indices: [2], fixed_video_indices: [], fixed_audio_indices: [1],
      replaceable_image_indices: [], replaceable_video_indices: [1], replaceable_audio_indices: [],
      duration: 10, aspect_ratio: '16:9', user_fields: payload.userFields,
    })
  })

  it('surfaces validation errors without retrying a publication', async () => {
    fetchMock.mockResolvedValue({ ok: false, json: async () => ({ ok: false, error: 'Референс не принадлежит вам' }) })
    await expect(publishSeedanceTrendUpload(payload)).rejects.toThrow('Референс не принадлежит вам')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('fails safely on a malformed server response', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => { throw new Error('not json') } })
    await expect(publishSeedanceTrendUpload(payload)).rejects.toThrow('Сервер вернул некорректный ответ')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
