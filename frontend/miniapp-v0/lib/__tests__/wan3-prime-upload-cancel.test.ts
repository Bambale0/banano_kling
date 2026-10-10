const AUTH = 'user=%7B%22id%22%3A4242%7D&hash=synthetic'
const STORAGE_KEY = '__wan3_pending_upload_4242'
jest.mock('../api', () => ({
  getApiBasePath: () => '/mini-app/api', getInitData: jest.fn(() => AUTH), getStartParamFallback: () => '',
}))
let api: typeof import('../wan3-prime-api')
const fetchMock = jest.fn()
const file = () => new File(['0123456789'], 'Фото.jpg', { type: 'image/jpeg' })
const response = (payload: unknown, status = 200) => ({ ok: status < 400, status, text: async () => JSON.stringify(payload) }) as Response
const bodyOf = (options: RequestInit) => JSON.parse(String(options.body))
const cancelled = () => response({ ok: true, status: 'cancelled' })
const completed = () => response({ ok: true, url: 'https://owned.test/upload.jpg', kind: 'image', filename: 'upload.jpg', size: 10 })
async function until(condition: () => boolean) {
  for (let index = 0; index < 100 && !condition(); index += 1) await Promise.resolve()
  expect(condition()).toBe(true)
}
function serveSuccess(url: string, options: RequestInit): Promise<Response> {
  if (url.endsWith('/init')) return Promise.resolve(response({ ok: true, upload_id: bodyOf(options).upload_id, chunk_size: 10 }))
  if (url.endsWith('/cancel')) return Promise.resolve(cancelled())
  if (url.endsWith('/complete')) return Promise.resolve(completed())
  return Promise.resolve(response({ ok: true }))
}
beforeEach(() => {
  jest.resetModules(); sessionStorage.clear(); fetchMock.mockReset()
  global.fetch = fetchMock
  api = jest.requireActual<typeof import('../wan3-prime-api')>('../wan3-prime-api')
})

test('five cancelled uploads release five reservations before the next file starts', async () => {
  const reservations = new Set<string>(), ids: string[] = []
  let chunks = 0
  fetchMock.mockImplementation((url: string, options: RequestInit) => {
    if (url.endsWith('/init')) {
      const payload = bodyOf(options)
      expect(payload.upload_id).toMatch(/^[a-f0-9]{32}$/)
      expect(JSON.parse(sessionStorage.getItem(STORAGE_KEY)!).upload_id).toBe(payload.upload_id)
      expect(reservations.size).toBe(0)
      ids.push(payload.upload_id); reservations.add(payload.upload_id)
      return serveSuccess(url, options)
    }
    if (url.endsWith('/cancel')) { reservations.delete(bodyOf(options).upload_id); return Promise.resolve(cancelled()) }
    if (url.endsWith('/chunk')) { chunks += 1; return new Promise(() => {}) }
    return serveSuccess(url, options)
  })
  for (let index = 0; index < 5; index += 1) {
    const controller = new AbortController()
    const upload = api.uploadWan3PrimeReference('image', file(), controller.signal)
    const rejection = expect(upload).rejects.toMatchObject({ name: 'AbortError' })
    await until(() => chunks === index + 1)
    controller.abort(); await rejection
    expect(reservations.size).toBe(0)
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull()
  }
  expect(new Set(ids).size).toBe(5)
  fetchMock.mockImplementation(serveSuccess)
  await expect(api.uploadWan3PrimeReference('image', file())).resolves.toMatchObject({ url: 'https://owned.test/upload.jpg' })
})

test('cancel during init captures its delayed ID and waits for cleanup without admitting a second upload', async () => {
  let resolveInit: (value: Response) => void = () => {}, resolveCancel: (value: Response) => void = () => {}
  let initSignal: AbortSignal | undefined, uploadId = ''
  fetchMock.mockImplementation((url: string, options: RequestInit) => {
    if (url.endsWith('/init')) {
      uploadId = bodyOf(options).upload_id; initSignal = options.signal as AbortSignal
      return new Promise(resolve => { resolveInit = resolve })
    }
    if (url.endsWith('/cancel')) return new Promise(resolve => { resolveCancel = resolve })
    throw new Error('No chunks should start after cancellation')
  })
  const controller = new AbortController()
  const upload = api.uploadWan3PrimeReference('image', file(), controller.signal)
  const rejection = expect(upload).rejects.toMatchObject({ name: 'AbortError' })
  controller.abort()
  expect(initSignal?.aborted).toBe(false)
  await expect(api.uploadWan3PrimeReference('image', file())).rejects.toThrow('Предыдущая загрузка ещё завершается')
  expect(fetchMock).toHaveBeenCalledTimes(1)
  resolveInit(response({ ok: true, upload_id: uploadId, chunk_size: 10 }))
  await until(() => fetchMock.mock.calls.length === 2)
  expect(fetchMock.mock.calls[1][0]).toMatch(/\/cancel$/)
  expect(bodyOf(fetchMock.mock.calls[1][1]).upload_id).toBe(uploadId)
  await expect(api.uploadWan3PrimeReference('image', file())).rejects.toThrow('Предыдущая загрузка ещё завершается')
  resolveCancel(cancelled()); await rejection
  expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull()
})

test('failed cleanup remains durable across module reload and is retried before a new init', async () => {
  let oldId = '', chunks = 0
  fetchMock.mockImplementation((url: string, options: RequestInit) => {
    if (url.endsWith('/init')) { oldId = bodyOf(options).upload_id; return serveSuccess(url, options) }
    if (url.endsWith('/chunk')) { chunks += 1; return new Promise(() => {}) }
    return Promise.resolve(response({ ok: false, error: 'cancel unavailable', code: 'temporary' }, 503))
  })
  const controller = new AbortController()
  const upload = api.uploadWan3PrimeReference('image', file(), controller.signal)
  const rejection = expect(upload).rejects.toMatchObject({ name: 'Wan3PrimeUploadCleanupError' })
  await until(() => chunks === 1); controller.abort(); await rejection
  const saved = sessionStorage.getItem(STORAGE_KEY)!
  expect(JSON.parse(saved)).toMatchObject({ upload_id: oldId, phase: 'known' })
  expect(saved).not.toContain('hash'); expect(saved).not.toContain(AUTH)
  jest.resetModules(); api = jest.requireActual<typeof import('../wan3-prime-api')>('../wan3-prime-api')
  fetchMock.mockClear(); fetchMock.mockImplementation(serveSuccess)
  await api.uploadWan3PrimeReference('image', file())
  expect(fetchMock.mock.calls[0][0]).toMatch(/\/cancel$/)
  expect(bodyOf(fetchMock.mock.calls[0][1]).upload_id).toBe(oldId)
  expect(fetchMock.mock.calls[1][0]).toMatch(/\/init$/)
  expect(bodyOf(fetchMock.mock.calls[1][1]).upload_id).not.toBe(oldId)
  expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull()
})

test('unknown init is reconciled using identical ID and metadata; another transport failure cannot create a new ID', async () => {
  fetchMock.mockRejectedValue(new TypeError('Network lost'))
  await expect(api.uploadWan3PrimeReference('image', file())).rejects.toMatchObject({ name: 'Wan3PrimeUploadCleanupError' })
  const original = bodyOf(fetchMock.mock.calls[0][1])
  await expect(api.uploadWan3PrimeReference('image', file())).rejects.toMatchObject({ name: 'Wan3PrimeUploadCleanupError' })
  expect(fetchMock).toHaveBeenCalledTimes(2)
  expect(bodyOf(fetchMock.mock.calls[1][1])).toEqual(original)
  expect(JSON.parse(sessionStorage.getItem(STORAGE_KEY)!).phase).toBe('initializing')
  jest.resetModules(); api = jest.requireActual<typeof import('../wan3-prime-api')>('../wan3-prime-api')
  fetchMock.mockClear(); fetchMock.mockImplementation(serveSuccess)
  await api.uploadWan3PrimeReference('image', file())
  expect(bodyOf(fetchMock.mock.calls[0][1])).toEqual(original)
  expect(fetchMock.mock.calls[1][0]).toMatch(/\/cancel$/)
  expect(bodyOf(fetchMock.mock.calls[1][1]).upload_id).toBe(original.upload_id)
  expect(bodyOf(fetchMock.mock.calls[2][1]).upload_id).not.toBe(original.upload_id)
})

test('init timeout retains its chosen ID; replay and cancellation fence a late initial response', async () => {
  jest.useFakeTimers()
  try {
    let resolveLate: (value: Response) => void = () => {}
    fetchMock.mockImplementationOnce(() => new Promise(resolve => { resolveLate = resolve }))
    const upload = api.uploadWan3PrimeReference('image', file())
    const rejection = expect(upload).rejects.toMatchObject({ name: 'Wan3PrimeUploadCleanupError' })
    const oldId = bodyOf(fetchMock.mock.calls[0][1]).upload_id
    await jest.advanceTimersByTimeAsync(api.WAN3_PRIME_MEDIA_TIMEOUT_MS); await rejection
    expect(JSON.parse(sessionStorage.getItem(STORAGE_KEY)!).upload_id).toBe(oldId)
    fetchMock.mockImplementation(serveSuccess)
    await api.uploadWan3PrimeReference('image', file())
    expect(bodyOf(fetchMock.mock.calls[1][1]).upload_id).toBe(oldId)
    expect(fetchMock.mock.calls[2][0]).toMatch(/\/cancel$/)
    const callCount = fetchMock.mock.calls.length
    resolveLate(response({ ok: true, upload_id: oldId, chunk_size: 10 }))
    await Promise.resolve(); await Promise.resolve()
    expect(fetchMock).toHaveBeenCalledTimes(callCount)
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull()
    expect(jest.getTimerCount()).toBe(0)
  } finally { jest.useRealTimers() }
})

test('explicit init collision fences the old ID before accepting cancel not_found', async () => {
  fetchMock.mockRejectedValueOnce(new TypeError('Uncertain init'))
  await expect(api.uploadWan3PrimeReference('image', file())).rejects.toMatchObject({ name: 'Wan3PrimeUploadCleanupError' })
  const oldId = bodyOf(fetchMock.mock.calls[0][1]).upload_id
  fetchMock.mockResolvedValueOnce(response({ ok: false, error: 'conflict', code: 'upload_session_conflict' }, 409))
    .mockResolvedValueOnce(response({ ok: true, status: 'not_found' }))
    .mockImplementation(serveSuccess)
  await api.uploadWan3PrimeReference('image', file())
  expect(bodyOf(fetchMock.mock.calls[1][1]).upload_id).toBe(oldId)
  expect(fetchMock.mock.calls[2][0]).toMatch(/\/cancel$/)
  expect(bodyOf(fetchMock.mock.calls[3][1]).upload_id).not.toBe(oldId)
})

test.each([400, 429, 504])('an unrecognized parsed HTTP %s failure retains the uncertain init fence', async status => {
  fetchMock.mockResolvedValue(response({ ok: false, error: 'Uncertain rejection', code: 'unrecognized_error' }, status))
  await expect(api.uploadWan3PrimeReference('image', file())).rejects.toMatchObject({ name: 'Wan3PrimeUploadCleanupError' })
  const oldId = bodyOf(fetchMock.mock.calls[0][1]).upload_id
  expect(JSON.parse(sessionStorage.getItem(STORAGE_KEY)!)).toMatchObject({ upload_id: oldId, phase: 'initializing' })
  await expect(api.uploadWan3PrimeReference('image', file())).rejects.toMatchObject({ name: 'Wan3PrimeUploadCleanupError' })
  expect(fetchMock.mock.calls.every(call => call[0].endsWith('/init'))).toBe(true)
  expect(bodyOf(fetchMock.mock.calls[1][1]).upload_id).toBe(oldId)
})

test.each(['Unsupported upload kind', 'Upload size is not allowed', 'Upload extension is not allowed', 'Invalid upload ID'])('fresh deterministic validation rejection is released: %s', async error => {
  fetchMock.mockResolvedValueOnce(response({ ok: false, error, code: 'validation_error' }, 400))
    .mockImplementation(serveSuccess)
  await expect(api.uploadWan3PrimeReference('image', file())).rejects.toThrow(error)
  expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull()
  await api.uploadWan3PrimeReference('image', file())
  expect(fetchMock.mock.calls.filter(call => call[0].endsWith('/init'))).toHaveLength(2)
  expect(fetchMock.mock.calls.some(call => call[0].endsWith('/cancel'))).toBe(false)
})

test('a deterministic rejection cannot discard an earlier uncertain init during reconciliation', async () => {
  fetchMock.mockRejectedValueOnce(new TypeError('Lost initial response'))
    .mockResolvedValueOnce(response({ ok: false, error: 'Upload extension is not allowed', code: 'validation_error' }, 400))
  await expect(api.uploadWan3PrimeReference('image', file())).rejects.toMatchObject({ name: 'Wan3PrimeUploadCleanupError' })
  const id = bodyOf(fetchMock.mock.calls[0][1]).upload_id
  await expect(api.uploadWan3PrimeReference('image', file())).rejects.toMatchObject({ name: 'Wan3PrimeUploadCleanupError' })
  expect(JSON.parse(sessionStorage.getItem(STORAGE_KEY)!)).toMatchObject({ upload_id: id, phase: 'initializing' })
  expect(bodyOf(fetchMock.mock.calls[1][1]).upload_id).toBe(id)
})

test.each(['timeout', 'invalid-status'])('cancel %s retains known cleanup and blocks fresh init until resolved', async failure => {
  jest.useFakeTimers()
  try {
    fetchMock.mockImplementation((url: string, options: RequestInit) => {
      if (url.endsWith('/chunk')) return Promise.reject(new TypeError('Chunk disconnected'))
      if (url.endsWith('/cancel')) return failure === 'timeout' ? new Promise(() => {}) : Promise.resolve(response({ ok: true, status: 'unconfirmed' }))
      return serveSuccess(url, options)
    })
    const pending = api.uploadWan3PrimeReference('image', file())
    const rejection = expect(pending).rejects.toMatchObject({ name: 'Wan3PrimeUploadCleanupError' })
    await jest.advanceTimersByTimeAsync(api.WAN3_PRIME_MEDIA_TIMEOUT_MS); await rejection
    const id = bodyOf(fetchMock.mock.calls[0][1]).upload_id
    expect(JSON.parse(sessionStorage.getItem(STORAGE_KEY)!)).toMatchObject({ upload_id: id, phase: 'known' })
    expect(fetchMock.mock.calls.filter(call => call[0].endsWith('/init'))).toHaveLength(1)
    fetchMock.mockResolvedValue(response({ ok: true, status: 'unconfirmed' }))
    await expect(api.uploadWan3PrimeReference('image', file())).rejects.toMatchObject({ name: 'Wan3PrimeUploadCleanupError' })
    expect(fetchMock.mock.calls.filter(call => call[0].endsWith('/init'))).toHaveLength(1)
    fetchMock.mockImplementation(serveSuccess)
    await api.uploadWan3PrimeReference('image', file())
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull()
    expect(jest.getTimerCount()).toBe(0)
  } finally { jest.useRealTimers() }
})

test('another signed owner cannot cancel or reuse the first owner reservation', async () => {
  fetchMock.mockRejectedValueOnce(new TypeError('Lost init'))
  await expect(api.uploadWan3PrimeReference('image', file())).rejects.toMatchObject({ name: 'Wan3PrimeUploadCleanupError' })
  const original = bodyOf(fetchMock.mock.calls[0][1])
  const otherAuth = 'user=%7B%22id%22%3A4343%7D&hash=other-synthetic'
  jest.requireMock('../api').getInitData.mockReturnValue(otherAuth)
  fetchMock.mockImplementation(serveSuccess)
  await api.uploadWan3PrimeReference('image', file())
  expect(bodyOf(fetchMock.mock.calls[1][1]).init_data).toBe(otherAuth)
  expect(bodyOf(fetchMock.mock.calls[1][1]).upload_id).not.toBe(original.upload_id)
  expect(fetchMock.mock.calls.some(call => call[0].endsWith('/cancel'))).toBe(false)
  expect(JSON.parse(sessionStorage.getItem(STORAGE_KEY)!).upload_id).toBe(original.upload_id)
  jest.requireMock('../api').getInitData.mockReturnValue(AUTH)
  const next = fetchMock.mock.calls.length
  await api.uploadWan3PrimeReference('image', file())
  expect(bodyOf(fetchMock.mock.calls[next][1])).toEqual(original)
  expect(fetchMock.mock.calls[next + 1][0]).toMatch(/\/cancel$/)
})

test('cleanup uses the captured signed owner even when active browser auth changes', async () => {
  let chunkStarted = false
  fetchMock.mockImplementation((url: string, options: RequestInit) => {
    if (url.endsWith('/chunk')) { chunkStarted = true; return new Promise(() => {}) }
    return serveSuccess(url, options)
  })
  const controller = new AbortController()
  const pending = api.uploadWan3PrimeReference('image', file(), controller.signal)
  const rejection = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  await until(() => chunkStarted)
  jest.requireMock('../api').getInitData.mockReturnValue('user=%7B%22id%22%3A4343%7D&hash=other')
  controller.abort(); await rejection
  const cancel = fetchMock.mock.calls.find(call => call[0].endsWith('/cancel'))!
  expect(bodyOf(cancel[1]).init_data).toBe(AUTH)
  expect(cancel[1].headers['X-Telegram-Init-Data']).toBe(AUTH)
})

test('complete/cancel race accepts completed cleanup without deleting or attaching late media', async () => {
  let resolveComplete: (value: Response) => void = () => {}, completing = false
  fetchMock.mockImplementation((url: string, options: RequestInit) => {
    if (url.endsWith('/complete')) { completing = true; return new Promise(resolve => { resolveComplete = resolve }) }
    if (url.endsWith('/cancel')) return Promise.resolve(response({ ok: true, status: 'completed' }))
    return serveSuccess(url, options)
  })
  const controller = new AbortController()
  const upload = api.uploadWan3PrimeReference('image', file(), controller.signal)
  const rejection = expect(upload).rejects.toMatchObject({ name: 'AbortError' })
  await until(() => completing); controller.abort(); await rejection
  const count = fetchMock.mock.calls.length
  resolveComplete(completed()); await Promise.resolve(); await Promise.resolve()
  expect(fetchMock).toHaveBeenCalledTimes(count)
  expect(fetchMock.mock.calls.map(call => call[0])).toEqual([
    '/mini-app/api/wan3/upload/init', '/mini-app/api/wan3/upload/chunk', '/mini-app/api/wan3/upload/complete', '/mini-app/api/wan3/upload/cancel',
  ])
  expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull()
})
