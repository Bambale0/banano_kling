import { normalizeWan3ImageForRetry, Wan3ImagePreparationError } from '@/lib/wan3-image-normalize'

test('re-encodes a phone JPEG into bounded JPEG without exposing original bytes', async () => {
  const image = { naturalWidth: 7000, naturalHeight: 3500, onload: null as null | (() => void), onerror: null as null | (() => void), src: '' }
  const drawImage = jest.fn()
  const getContext = jest.fn(() => ({ drawImage }))
  const toBlob = jest.fn((callback: (blob: Blob) => void) => callback(new Blob(['jpeg'], { type: 'image/jpeg' })))
  const createElement = jest.spyOn(document, 'createElement')
    .mockImplementation(((tag: string) => tag === 'canvas' ? ({ width: 0, height: 0, getContext, toBlob }) : document.createElement(tag)) as typeof document.createElement)
  const oldImage = global.Image
  const oldCreate = URL.createObjectURL
  const oldRevoke = URL.revokeObjectURL
  URL.createObjectURL = jest.fn(() => 'blob:phone')
  URL.revokeObjectURL = jest.fn()
  Object.defineProperty(global, 'Image', { configurable: true, value: function Image() {
    queueMicrotask(() => image.onload?.())
    return image
  } })
  try {
    const original = new File(['raw'], 'IMG_0729.jpeg', { type: 'image/jpeg' })
    const result = await normalizeWan3ImageForRetry(original)
    expect(result.name).toBe('IMG_0729.jpg')
    expect(result.type).toBe('image/jpeg')
    expect(drawImage).toHaveBeenCalledWith(image, 0, 0, 4096, 2048)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:phone')
  } finally {
    Object.defineProperty(global, 'Image', { configurable: true, value: oldImage })
    URL.createObjectURL = oldCreate
    URL.revokeObjectURL = oldRevoke
    createElement.mockRestore()
  }
})

test('aborted conversion never starts a replacement upload', async () => {
  const abort = new AbortController()
  abort.abort()
  await expect(normalizeWan3ImageForRetry(new File(['raw'], 'IMG_0729.jpeg'), abort.signal))
    .rejects.toHaveProperty('name', 'AbortError')
})

test('no browser image encoder returns actionable local error', async () => {
  const oldCreate = URL.createObjectURL
  URL.createObjectURL = undefined as unknown as typeof URL.createObjectURL
  try {
    await expect(normalizeWan3ImageForRetry(new File(['raw'], 'IMG_0729.jpeg')))
      .rejects.toBeInstanceOf(Wan3ImagePreparationError)
  } finally {
    URL.createObjectURL = oldCreate
  }
})
