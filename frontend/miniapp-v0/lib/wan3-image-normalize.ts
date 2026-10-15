/** One local JPEG recovery when the server rejects image bytes after a complete
 * chunked upload. Never touches the author's hidden media or changes server
 * permissions/price. The caller controls consent and session cleanup.
 */
export class Wan3ImagePreparationError extends Error {
  constructor() {
    super('Фото не удалось преобразовать. Сохраните его как JPEG или PNG и загрузите ещё раз.')
    this.name = 'Wan3ImagePreparationError'
  }
}

export async function normalizeWan3ImageForRetry(file: File, signal?: AbortSignal): Promise<File> {
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  if (typeof document === 'undefined' || typeof URL.createObjectURL !== 'function') throw new Wan3ImagePreparationError()
  const src = URL.createObjectURL(file)
  try {
    const image = new Image()
    await new Promise<void>((resolve, reject) => {
      const finish = (error?: Error) => {
        signal?.removeEventListener('abort', abort)
        image.onload = null
        image.onerror = null
        if (error) reject(error)
        else resolve()
      }
      const abort = () => { image.src = ''; finish(new DOMException('Aborted', 'AbortError')) }
      image.onload = () => finish()
      image.onerror = () => finish(new Wan3ImagePreparationError())
      signal?.addEventListener('abort', abort, { once: true })
      if (signal?.aborted) { abort(); return }
      image.src = src
    })
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    const width = image.naturalWidth, height = image.naturalHeight
    if (!width || !height || Math.min(width, height) < 240
      || Math.max(width, height) / Math.min(width, height) > 8) throw new Wan3ImagePreparationError()
    const scale = Math.min(1, 4096 / Math.max(width, height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(width * scale))
    canvas.height = Math.max(1, Math.round(height * scale))
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Wan3ImagePreparationError()
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height)
    const jpeg = await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(blob => blob ? resolve(blob) : reject(new Wan3ImagePreparationError()), 'image/jpeg', 0.88))
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    if (!jpeg.size || jpeg.size > 20 * 1024 * 1024) throw new Wan3ImagePreparationError()
    const name = (file.name.replace(/\.[^.]+$/, '').slice(0, 80) || 'reference') + '.jpg'
    return new File([jpeg], name, { type: 'image/jpeg', lastModified: file.lastModified })
  } finally {
    URL.revokeObjectURL(src)
  }
}
