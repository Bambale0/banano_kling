/** Distinguish an explicit Telegram launch from stale browser initData snapshots. */
export function hasExplicitTelegramLaunch(): boolean {
  if (typeof window === 'undefined') return false
  const signedBySdk = String(window.Telegram?.WebApp?.initData || '')
  if (signedBySdk) return true
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const query = new URLSearchParams(window.location.search)
  const snapshot = window.__BANANO_INITIAL_LAUNCH__
  const initialHash = new URLSearchParams(String(snapshot?.hash || '').replace(/^#/, ''))
  const initialSearch = new URLSearchParams(String(snapshot?.search || '').replace(/^\?/, ''))
  return Boolean(
    hash.get('tgWebAppData') || query.get('tgWebAppData')
    || initialHash.get('tgWebAppData') || initialSearch.get('tgWebAppData')
  )
}

export function browserEntryMode(
  authenticated: boolean,
  studioReady: boolean,
): 'login' | 'web' | 'linked' {
  if (!authenticated) return 'login'
  return studioReady ? 'linked' : 'web'
}


/** Keep only recognised internal account-intent parameters across browser login.
 * Never forward an untrusted external URL as a post-login destination.
 */
export function browserLoginUrl(search: string): string {
  const provided = new URLSearchParams(search)
  const safe = new URLSearchParams()
  for (const key of ['ref', 'startapp', 'intent', 'package_id', 'provider']) {
    const value = provided.get(key)
    if (value && value.length <= 128 && /^[a-zA-Z0-9_-]+$/.test(value)) {
      safe.set(key, value)
    }
  }
  const returnTo = provided.get('return_to')
  if (returnTo && returnTo.length <= 512
      && /^\/mini-app(?:\/|\?|$)/.test(returnTo)
      && !/[\\\x00-\x1F]/.test(returnTo)) {
    safe.set('return_to', returnTo)
  }
  const query = safe.toString()
  return '/login' + (query ? '?' + query : '')
}


/** Next.js basePath=/mini-app rewrites router.replace('/login') into
 * /mini-app/login/; login is served by Nginx at the site root. Force a
 * document-level navigation so the browser uses the canonical /login URL.
 */
export function navigateToWebsiteLogin(target: string): void {
  window.location.replace(target)
}
