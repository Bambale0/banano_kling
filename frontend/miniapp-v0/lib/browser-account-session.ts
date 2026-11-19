'use client'

import { currentAccountPlatform } from './account-platform'
import { getInitData } from './api'

const BROWSER_AUTH_SNAPSHOT_KEYS = [
  '__banano_tg_init_data',
  '__banano_initial_href',
  '__banano_initial_hash',
  '__banano_initial_search',
  '__telegram__initParams',
] as const

/** Browser-auth uses a server-signed Telegram payload with a browser_ query ID.
 * Native Telegram Mini Apps and VK sessions must never offer manual sign-out. */
export function isBrowserAccountSession(): boolean {
  if (typeof window === 'undefined' || currentAccountPlatform() !== 'telegram') return false
  const queryId = new URLSearchParams(getInitData()).get('query_id')
  return Boolean(queryId?.startsWith('browser_'))
}

/** Remove only browser authentication snapshots, preserving unrelated settings.
 * The browser login is a stateless signed payload, not a revocable server cookie.
 * Do not claim that clearing this client session invalidates old copied links. */
export function clearBrowserAccountCredentials(): void {
  if (typeof window === 'undefined') return
  try {
    for (const key of BROWSER_AUTH_SNAPSHOT_KEYS) window.sessionStorage.removeItem(key)
  } catch {
    // Storage may be restricted in a private browser; continue to redirect.
  }
  delete window.__BANANO_TG_INIT_DATA__
  delete window.__BANANO_INITIAL_LAUNCH__
  // Drop auth-bearing search/hash before navigating, so Back cannot revisit
  // this history entry with the signed payload still embedded in its URL.
  try {
    window.history.replaceState(null, '', window.location.pathname)
  } catch {
    // Navigation away is still mandatory if the browser forbids replaceState.
  }
}

export function signOutBrowserAccount(): void {
  if (!isBrowserAccountSession()) return
  clearBrowserAccountCredentials()
  window.location.replace('/login')
}
