export {}

jest.mock('../api', () => ({
  getApiBasePath: () => '/mini-app/api', getInitData: () => 'signed-init-data', getStartParamFallback: () => '',
}))

const fetchMock = jest.fn()
const response = (payload: unknown, status = 200) => ({ ok: status < 400, status, text: async () => JSON.stringify(payload) }) as Response
let api: typeof import('../wan3-prime-api')
const originalReader = global.FileReader
function success(url: string, options: RequestInit) {
  if (url.endsWith('/init')) return response({ ok: true, upload_id: JSON.parse(String(options.body)).upload_id, chunk_size: 5 })
  if (url.endsWith('/complete')) return response({ ok: true, url: 'https://owned.test/photo.jpeg', kind: 'image', filename: 'photo.jpeg', size: 10 })
  if (url.endsWith('/cancel')) return response({ ok: true, status: 'cancelled' })
  return response({ ok: true })
}
beforeEach(() => {
  jest.resetModules(); fetchMock.mockReset(); global.fetch = fetchMock
  jest.spyOn(navigator, 'userAgent', 'get').mockReturnValue('Desktop Chrome')
  api = jest.requireActual('../wan3-prime-api')
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => success(url, options))
})
afterEach(() => { jest.restoreAllMocks(); global.FileReader = originalReader })

test.each(['iPhone iOS 18_7', 'iPad', 'iPod', 'Android Chrome', 'Telegram-Android'])('uses bounded JSON chunks on %s', async userAgent => {
  jest.spyOn(navigator, 'userAgent', 'get').mockReturnValue(userAgent)
  const progress = jest.fn()
  await api.uploadWan3PrimeReference('image', new File(['0123456789'], 'Фото.jpeg', { type: 'image/jpeg' }), undefined, progress)
  const chunks = fetchMock.mock.calls.filter(([url]) => url.endsWith('/chunk'))
  expect(chunks).toHaveLength(2)
  chunks.forEach(([, options], index) => {
    expect(options.headers['Content-Type']).toBe('application/json')
    expect(options.headers['X-Telegram-Init-Data']).toBe('signed-init-data')
    const body = JSON.parse(options.body)
    expect(body).toMatchObject({ index, total: 2, init_data: 'signed-init-data', start_param_fallback: '' })
    expect(atob(body.chunk_base64)).toBe(index === 0 ? '01234' : '56789')
    expect(body.upload_id).toBe(JSON.parse(fetchMock.mock.calls[0][1].body).upload_id)
  })
  expect(progress.mock.calls).toEqual([[0, 10], [5, 10], [10, 10]])
})

test('desktop multipart rejection retries the same chunk once as JSON', async () => {
  let rejected = false
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => {
    if (url.endsWith('/chunk') && options.body instanceof FormData && !rejected) {
      rejected = true
      return response({ ok: false, code: 'invalid_upload_multipart', error: 'Не удалось прочитать загрузку.' }, 400)
    }
    return success(url, options)
  })
  await api.uploadWan3PrimeReference('image', new File(['01234'], 'photo.jpeg', { type: 'image/jpeg' }))
  const chunks = fetchMock.mock.calls.filter(([url]) => url.endsWith('/chunk'))
  expect(chunks).toHaveLength(2)
  expect(chunks[0][1].body).toBeInstanceOf(FormData)
  const body = JSON.parse(chunks[1][1].body)
  expect(body.upload_id).toBe(chunks[0][1].body.get('upload_id'))
  expect(body.index).toBe(0); expect(atob(body.chunk_base64)).toBe('01234')
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/init'))).toHaveLength(1)
})

test('desktop-mode iPad uses JSON chunks too', async () => {
  jest.spyOn(navigator, 'userAgent', 'get').mockReturnValue('Macintosh Safari')
  jest.spyOn(navigator, 'platform', 'get').mockReturnValue('MacIntel')
  Object.defineProperty(navigator, 'maxTouchPoints', { configurable: true, value: 5 })
  try {
    await api.uploadWan3PrimeReference('image', new File(['01234'], 'photo.jpeg'))
    expect(fetchMock.mock.calls[1][1].headers['Content-Type']).toBe('application/json')
  } finally { delete (navigator as any).maxTouchPoints }
})

test('JSON fallback failure cancels once without creating another upload session', async () => {
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => {
    if (url.endsWith('/chunk')) return options.body instanceof FormData
      ? response({ ok: false, code: 'invalid_upload_multipart', error: 'multipart rejected' }, 400)
      : response({ ok: false, code: 'validation_error', error: 'Upload session not found' }, 404)
    return success(url, options)
  })
  await expect(api.uploadWan3PrimeReference('image', new File(['01234'], 'photo.jpeg'))).rejects.toThrow('Upload session not found')
  expect(fetchMock.mock.calls.map(([url]) => url.split('/').at(-1))).toEqual(['init', 'chunk', 'chunk', 'cancel'])
})

test('an authorization rejection does not try another transport', async () => {
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => url.endsWith('/chunk')
    ? response({ ok: false, code: 'auth_invalid', error: 'expired auth' }, 401) : success(url, options))
  await expect(api.uploadWan3PrimeReference('image', new File(['01234'], 'photo.jpeg'))).rejects.toThrow('expired auth')
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/chunk'))).toHaveLength(1)
  expect(fetchMock.mock.calls.at(-1)[0]).toMatch(/\/cancel$/)
})

test('cancelling during JSON file reading aborts the reader and releases the same reservation', async () => {
  jest.spyOn(navigator, 'userAgent', 'get').mockReturnValue('iPhone')
  let reader: FileReader | undefined
  global.FileReader = class {
    onload: (() => void) | null = null; onerror: (() => void) | null = null; onabort: (() => void) | null = null
    result: ArrayBuffer | null = null
    readAsArrayBuffer = () => { this.result = new Uint8Array(5).buffer; this.onload?.() }
    abort = jest.fn(() => { this.onabort?.() })
    readAsDataURL = jest.fn(() => { reader = this as unknown as FileReader })
  } as unknown as typeof FileReader
  const controller = new AbortController()
  const result = api.uploadWan3PrimeReference('image', new File(['01234'], 'photo.jpeg'), controller.signal)
  const rejected = expect(result).rejects.toMatchObject({ name: 'AbortError' })
  for (let turn = 0; turn < 100 && !reader; turn += 1) await Promise.resolve()
  expect(reader).toBeDefined()
  controller.abort(); await rejected
  expect(reader!.abort).toHaveBeenCalledTimes(1)
  expect(fetchMock.mock.calls.map(([url]) => url.split('/').at(-1))).toEqual(['init', 'cancel'])
})

test('a stalled JSON read times out and releases its reservation', async () => {
  jest.useFakeTimers()
  jest.spyOn(navigator, 'userAgent', 'get').mockReturnValue('Android')
  const abort = jest.fn()
  global.FileReader = class {
    result: ArrayBuffer | null = null; onload: (() => void) | null = null
    readAsArrayBuffer = () => { this.result = new Uint8Array(5).buffer; this.onload?.() }
    readAsDataURL = jest.fn(); abort = abort
  } as unknown as typeof FileReader
  try {
    const result = api.uploadWan3PrimeReference('image', new File(['01234'], 'photo.jpeg'))
    const rejected = expect(result).rejects.toThrow('Сервер не ответил за 15 минут')
    await jest.advanceTimersByTimeAsync(api.WAN3_PRIME_MEDIA_TIMEOUT_MS)
    await rejected
    expect(abort).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls.map(([url]) => url.split('/').at(-1))).toEqual(['init', 'cancel'])
    expect(jest.getTimerCount()).toBe(0)
  } finally { jest.useRealTimers() }
})


test.each(['Desktop Chrome', 'iPhone'])('retries a disconnected chunk once with the same upload and bytes on %s', async userAgent => {
  jest.spyOn(navigator, 'userAgent', 'get').mockReturnValue(userAgent)
  let interrupted = false
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => {
    if (url.endsWith('/chunk') && !interrupted) {
      interrupted = true
      return response({ ok: false, code: 'upload_interrupted', error: 'Connection lost' }, 499)
    }
    return success(url, options)
  })
  await api.uploadWan3PrimeReference('image', new File(['01234'], 'photo.jpeg'))
  const chunks = fetchMock.mock.calls.filter(([url]) => url.endsWith('/chunk'))
  expect(chunks).toHaveLength(2)
  const firstId = chunks[0][1].body instanceof FormData ? chunks[0][1].body.get('upload_id') : JSON.parse(chunks[0][1].body).upload_id
  const retried = JSON.parse(chunks[1][1].body)
  expect(retried.upload_id).toBe(firstId)
  expect(retried.index).toBe(0)
  expect(atob(retried.chunk_base64)).toBe('01234')
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/init'))).toHaveLength(1)
})

test('persistent disconnection stops after two chunk attempts and cancels the reservation', async () => {
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => url.endsWith('/chunk')
    ? response({ ok: false, code: 'upload_interrupted', error: 'Connection lost' }, 499) : success(url, options))
  await expect(api.uploadWan3PrimeReference('image', new File(['01234'], 'photo.jpeg'))).rejects.toThrow('Connection lost')
  expect(fetchMock.mock.calls.map(([url]) => url.split('/').at(-1))).toEqual(['init', 'chunk', 'chunk', 'cancel'])
})

// Models an Android picker/content-provider handle that cannot be re-opened
// after the event turn has yielded to remote initialization.
test('snapshots the picked image before awaiting a remote upload session', async () => {
  jest.spyOn(navigator, 'userAgent', 'get').mockReturnValue('Telegram-Android Samsung')
  const picked = new File(['0123456789'], 'picked.jpeg', { type: 'image/jpeg' })
  const slice = picked.slice.bind(picked)
  let networkStarted = false
  jest.spyOn(picked, 'slice').mockImplementation((...args) => {
    if (networkStarted) throw new DOMException('Native picker handle expired', 'NotReadableError')
    return slice(...args)
  })
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => {
    networkStarted = true
    return success(url, options)
  })
  await expect(api.uploadWan3PrimeReference('image', picked)).resolves.toMatchObject({ url: 'https://owned.test/photo.jpeg' })
  const chunks = fetchMock.mock.calls.filter(([url]) => url.endsWith('/chunk'))
  expect(chunks).toHaveLength(2)
  expect(chunks.map(([, opts]) => atob(JSON.parse(opts.body).chunk_base64)).join('')).toBe('0123456789')
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/cancel'))).toHaveLength(0)
})

test('unreadable picked photo fails before reserving server quota', async () => {
  global.FileReader = class {
    onerror: (() => void) | null = null
    readAsArrayBuffer() { this.onerror?.() }
  } as unknown as typeof FileReader
  await expect(api.uploadWan3PrimeReference('image', new File(['photo'], 'photo.jpeg'))).rejects.toBeInstanceOf(api.Wan3ImageReadError)
  expect(fetchMock).not.toHaveBeenCalled()
  expect(api.wan3SafeError(new api.Wan3ImageReadError(), 'fallback')).toContain('Выберите его заново')
})

test('cancelling the initial picked-photo read creates no server reservation', async () => {
  let reader: FileReader | undefined
  global.FileReader = class {
    readAsArrayBuffer() { reader = this as unknown as FileReader }
    abort = jest.fn()
  } as unknown as typeof FileReader
  const controller = new AbortController()
  const result = api.uploadWan3PrimeReference('image', new File(['photo'], 'photo.jpeg'), controller.signal)
  const rejected = expect(result).rejects.toMatchObject({ name: 'AbortError' })
  expect(reader).toBeDefined()
  controller.abort(); await rejected
  expect(reader!.abort).toHaveBeenCalledTimes(1)
  expect(fetchMock).not.toHaveBeenCalled()
})
