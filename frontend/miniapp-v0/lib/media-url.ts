export function normalizeMiniAppMediaUrl(value?: string | null): string {
  const raw = String(value || '').trim()
  if (!raw || typeof window === 'undefined') return raw
  if (raw.startsWith('blob:') || raw.startsWith('data:')) return raw

  try {
    const url = new URL(raw, window.location.origin)
    const host = url.hostname.toLowerCase()
    const localUploadHosts = new Set([
      'tanyapi.chillcreative.ru',
      'cdn.chillcreative.ru',
      'tanyapp.chillcreative.ru',
      'tanyapp.xn--e1aikcel5c5a.online',
    ])
    if (
      url.pathname.startsWith('/uploads/')
      && (url.origin === window.location.origin || localUploadHosts.has(host))
    ) {
      return `${window.location.origin}${url.pathname}${url.search}${url.hash}`
    }
    return url.toString()
  } catch {
    return raw
  }
}

export function mediaAspectRatio(value?: string | null, fallback = '16 / 9'): string {
  const match = String(value || '').match(/^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/)
  if (!match) return fallback
  const width = Number(match[1])
  const height = Number(match[2])
  if (!width || !height) return fallback
  return `${width} / ${height}`
}

export function videoPreviewFrameUrl(value?: string | null): string {
  const normalized = normalizeMiniAppMediaUrl(value)
  if (!normalized || typeof window === 'undefined' || normalized.startsWith('blob:')) return normalized
  try {
    const url = new URL(normalized, window.location.origin)
    if (!url.hash && /\.(mp4|m4v|mov|webm)$/i.test(url.pathname)) {
      url.hash = 't=0.001'
    }
    return url.toString()
  } catch {
    return normalized
  }
}
