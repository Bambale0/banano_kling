import { uploadFile } from '../api'

describe('Mini App upload transport', () => {
  const originalFetch = global.fetch
  const originalXhr = global.XMLHttpRequest
  const originalUserAgent = navigator.userAgent

  afterEach(() => {
    jest.useRealTimers()
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

  it.each(['seedance25_image_reference', 'seedance25_video_reference', 'seedance25_video_chunk'])(
    'avoids broken native multipart for %s in mobile WebViews', async (fileKind) => {
      Object.defineProperty(navigator, 'userAgent', { configurable: true,
        value: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) Mobile/15E148' })
      Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: jest.fn(() => true) })
      const xhrConstructor = jest.fn(() => { throw new Error('native multipart lost its file bytes') })
      global.XMLHttpRequest = xhrConstructor as unknown as typeof XMLHttpRequest
      let sent: Record<string, unknown> | undefined
      global.fetch = jest.fn(async (_url, options) => {
        sent = JSON.parse(String(options?.body))
        return { status: 200, text: async () => JSON.stringify({ ok: true,
          url: 'https://example.test/reference', kind: fileKind.includes('image') ? 'image' : 'video',
          filename: 'reference.bin' }) }
      }) as unknown as typeof fetch
      const uploaded = await uploadFile(fileKind as Parameters<typeof uploadFile>[0],
        new File(['exact-original-bytes'], 'reference.bin', { type: 'application/octet-stream' }))
      expect(uploaded.url).toBe('https://example.test/reference')
      expect(xhrConstructor).not.toHaveBeenCalled()
      expect(sent).toMatchObject({ file_kind: fileKind, data_base64: btoa('exact-original-bytes') })
    },
  )

  it('bounds JSON uploads even if the connection ignores cancellation', async () => {
    jest.useFakeTimers()
    Object.defineProperty(navigator, 'userAgent', { configurable: true, value: 'iPhone' })
    Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: jest.fn(() => true) })
    jest.spyOn(FileReader.prototype, 'readAsDataURL').mockImplementation(function (this: FileReader) {
      Object.defineProperty(this, 'result', { value: 'data:image/jpeg;base64,Ynl0ZXM=' })
      this.onload?.({ target: this } as unknown as ProgressEvent<FileReader>)
    })
    global.fetch = jest.fn(() => new Promise(() => {})) as typeof fetch
    const upload = uploadFile('image_reference', new File(['bytes'], 'ref.jpg', { type: 'image/jpeg' }))
    const assertion = expect(upload).rejects.toThrow('Загрузка не завершилась за 15 минут')
    await jest.advanceTimersByTimeAsync(900_001)
    await assertion
    expect((jest.mocked(global.fetch).mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true)
    expect(global.fetch).toHaveBeenCalledTimes(1)
  })
})
