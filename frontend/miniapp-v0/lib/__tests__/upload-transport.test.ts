import { uploadFile } from '../api'

describe('Mini App upload transport', () => {
  const originalFetch = global.fetch
  const originalXhr = global.XMLHttpRequest
  const originalUserAgent = navigator.userAgent

  afterEach(() => {
    global.fetch = originalFetch
    global.XMLHttpRequest = originalXhr
    Object.defineProperty(navigator, 'userAgent', {
      configurable: true,
      value: originalUserAgent,
    })
    jest.restoreAllMocks()
  })

  it('uses JSON directly for small trend videos in Telegram iOS WebView', async () => {
    Object.defineProperty(navigator, 'userAgent', {
      configurable: true,
      value:
        'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148',
    })
    Object.defineProperty(navigator, 'sendBeacon', {
      configurable: true,
      value: jest.fn(() => true),
    })

    const xhrConstructor = jest.fn(() => {
      throw new Error('multipart transport must not be attempted')
    })
    global.XMLHttpRequest = xhrConstructor as unknown as typeof XMLHttpRequest
    global.fetch = jest.fn(async () => ({
      status: 200,
      text: async () =>
        JSON.stringify({
          ok: true,
          url: 'https://example.test/trend.mov',
          kind: 'video',
          filename: 'trend.mov',
        }),
    })) as unknown as typeof fetch

    const uploaded = await uploadFile(
      'trend_video_preview',
      new File(['video-bytes'], 'trend.mov', { type: 'video/quicktime' }),
    )

    expect(uploaded.url).toBe('https://example.test/trend.mov')
    expect(xhrConstructor).not.toHaveBeenCalled()
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/upload'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
        }),
      }),
    )
  })

  it('uses JSON directly for image references in Telegram Android WebView', async () => {
    Object.defineProperty(navigator, 'userAgent', {
      configurable: true,
      value:
        'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Telegram-Android/12.9.2',
    })
    Object.defineProperty(navigator, 'sendBeacon', {
      configurable: true,
      value: jest.fn(() => true),
    })

    const xhrConstructor = jest.fn(() => {
      throw new Error('multipart transport must not be attempted')
    })
    global.XMLHttpRequest = xhrConstructor as unknown as typeof XMLHttpRequest
    global.fetch = jest.fn(async () => ({
      status: 200,
      text: async () =>
        JSON.stringify({
          ok: true,
          url: 'https://example.test/uploaded.jpg',
          kind: 'image',
          filename: 'reference.jpg',
        }),
    })) as unknown as typeof fetch

    const uploaded = await uploadFile(
      'image_reference',
      new File(['image-bytes'], 'reference.jpg', { type: 'image/jpeg' }),
    )

    expect(uploaded.url).toBe('https://example.test/uploaded.jpg')
    expect(xhrConstructor).not.toHaveBeenCalled()
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/upload'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
        }),
      }),
    )
  })
})
