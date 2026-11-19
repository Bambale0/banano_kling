'use client'

import { currentAccountPlatform } from './account-platform'
import { getApiBasePath, getInitData } from './api'

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
  // In-flight React effects may call getInitData() before location.replace
  // completes. Prevent the Telegram bridge/snapshot from restoring credentials.
  window.__BANANO_BROWSER_SIGNOUT__ = true
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

/** Revoke the httpOnly web-auth cookie on the server before removing the
 * browser-signed Telegram payload. A local-only clear would silently re-login
 * a Yandex/email user whose web-auth cookie was still valid. */
export async function revokeBrowserAccountSession(): Promise<void> {
  const response = await fetch(`${getApiBasePath()}/web-auth/logout`, {
    method: 'POST',
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { Accept: 'application/json' },
  })
  const result = await response.json().catch(() => null) as { ok?: boolean } | null
  if (!response.ok || result?.ok !== true) {
    throw new Error('Не удалось выйти из аккаунта. Проверьте соединение и попробуйте ещё раз.')
  }
}

export async function signOutBrowserAccount(): Promise<void> {
  if (!isBrowserAccountSession()) return
  // Do not pretend logout succeeded if the server cannot revoke its cookie.
  await revokeBrowserAccountSession()
  clearBrowserAccountCredentials()
  window.location.replace('/login')
}
