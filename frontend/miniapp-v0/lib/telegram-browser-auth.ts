'use client'

export interface TelegramBrowserAuthConfig {
  ok: boolean
  enabled: boolean
  expires_in?: number
}

export async function getTelegramBrowserAuthConfig(): Promise<TelegramBrowserAuthConfig> {
  const response = await fetch('/mini-app/api/browser-auth/config', {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
    credentials: 'same-origin',
  })
  if (!response.ok) {
    return { ok: false, enabled: false }
  }
  return response.json() as Promise<TelegramBrowserAuthConfig>
}

export function buildTelegramBrowserLoginUrl(): string {
  if (typeof window === 'undefined') return ''
  const returnTo = new URL(window.location.href)
  returnTo.hash = ''
  returnTo.searchParams.delete('auth_error')

  const authUrl = new URL('/mini-app/api/browser-auth/start', window.location.origin)
  authUrl.searchParams.set('return_to', returnTo.toString())
  return authUrl.toString()
}

export function getTelegramBrowserAuthError(): string {
  if (typeof window === 'undefined') return ''
  const url = new URL(window.location.href)
  const code = url.searchParams.get('auth_error') || ''
  if (!code) return ''
  url.searchParams.delete('auth_error')
  window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`)
  return code === 'telegram_login_cancelled'
    ? 'Вход отменён. Попробуйте ещё раз.'
    : 'Не удалось войти через Telegram. Попробуйте ещё раз.'
}
