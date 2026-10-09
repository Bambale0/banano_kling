/** Validate an executable link without rebuilding its server-owned query string. */
export function isNavigableShareLink(value: string): boolean {
  if (!value || /[\u0000-\u0020\u007f\\]/.test(value)) return false
  try {
    const parsed = new URL(value)
    return (parsed.protocol === 'https:' || parsed.protocol === 'http:')
      && Boolean(parsed.hostname) && !parsed.username && !parsed.password
  } catch {
    return false
  }
}

/** Same synchronous bridge pattern as the bot-start gate; false keeps anchor fallback. */
export function tryOpenTelegramShareLink(value: string): boolean {
  if (!isNavigableShareLink(value) || typeof window === 'undefined') return false
  // Telegram's bundled SDK accepts only t.me; other HTTP(S) links stay native.
  if (new URL(value).hostname !== 't.me') return false
  try {
    const webApp = window.Telegram?.WebApp
    if (!webApp?.openTelegramLink) return false
    webApp.openTelegramLink(value)
    return true
  } catch {
    // A missing/unsupported native bridge must not make the link a dead control.
    return false
  }
}
