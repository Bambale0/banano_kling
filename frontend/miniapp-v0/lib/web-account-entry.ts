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
): 'telegram' | 'web' | 'linked' {
  if (!authenticated) return 'telegram'
  return studioReady ? 'linked' : 'web'
}
