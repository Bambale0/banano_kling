/** Website-only public links. Telegram/VK deep links are separate products. */
const CODE = /^[A-Z0-9_-]{1,60}$/

export function normalizeWebPublicCode(value: unknown): string {
  if (typeof value !== 'string') return ''
  const code = value.trim().toUpperCase()
  return CODE.test(code) ? code : ''
}

function websiteOrigin(): string {
  if (typeof window === 'undefined') return ''
  const origin = window.location.origin
  // Never turn a link into a Telegram/VK destination or an opaque scheme.
  return /^https?:\/\//.test(origin) ? origin : ''
}

export function webProfileUrl(rawCode: unknown): string {
  const code = normalizeWebPublicCode(rawCode)
  const origin = websiteOrigin()
  if (!code || !origin) return ''
  const url = new URL('/mini-app/', origin)
  url.searchParams.set('web', '1')
  url.searchParams.set('profile', code)
  url.searchParams.set('ref', code)
  return url.toString()
}

export function webReferralUrl(rawCode: unknown): string {
  const code = normalizeWebPublicCode(rawCode)
  const origin = websiteOrigin()
  if (!code || !origin) return ''
  const url = new URL('/login', origin)
  url.searchParams.set('web', '1')
  url.searchParams.set('ref', code)
  return url.toString()
}

export function publicProfileCodeFromSearch(search: string): string {
  const params = new URLSearchParams(search)
  const direct = normalizeWebPublicCode(params.get('profile'))
  if (direct) return direct
  const start = params.get('startapp') || ''
  if (!start.startsWith('profile_')) return ''
  const code = start.slice('profile_'.length).split('_ref_')[0]
  return normalizeWebPublicCode(code)
}

export function incomingWebReferralCode(search: string): string {
  const params = new URLSearchParams(search)
  const code = normalizeWebPublicCode(params.get('ref'))
  if (code) return code
  const start = params.get('startapp') || ''
  if (start.startsWith('ref_')) return normalizeWebPublicCode(start.slice(4))
  if (start.startsWith('profile_')) {
    const suffix = start.split('_ref_')[1]
    return normalizeWebPublicCode(suffix)
  }
  return ''
}


/** Convert only a verified platform referral URL, never arbitrary redirects.
 * The Telegram bot deep link stays untouched in bot-specific delivery. */
export function webReferralFromPlatformLink(rawLink: string): string {
  try {
    const url = new URL(rawLink)
    if (url.protocol !== 'https:' || !['t.me', 'www.t.me', 'vk.com', 'www.vk.com'].includes(url.hostname)) return ''
    const token = url.searchParams.get('startapp') || url.searchParams.get('start')
      || url.hash.replace(/^#/, '')
    if (!token?.startsWith('ref_')) return ''
    return webReferralUrl(token.slice(4))
  } catch {
    return ''
  }
}
