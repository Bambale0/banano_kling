import { getApiBasePath, getInitData } from './api'

export interface AccountPreviewSettings {
  enabled: boolean
  revision: number
  vk_app_id: number | null
  vk_admin_ids: number[]
  session_ttl_seconds: number
  launch_max_age_seconds: number
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBasePath()}/account-preview/${path}`, {
    ...init,
    cache: 'no-store',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })
  if (response.status === 409) throw new Error('Настройки изменились. Обновите страницу.')
  if (response.status === 401) throw new Error('Откройте приложение заново для подтверждения входа.')
  if (response.status === 403) throw new Error('Требуется доступ администратора.')
  if (response.status === 404) throw new Error('Проверка аккаунтов пока выключена.')
  if (!response.ok) throw new Error('Не удалось выполнить запрос. Попробуйте ещё раз.')
  const result = await response.json()
  if (!result.ok) throw new Error('Не удалось выполнить запрос. Попробуйте ещё раз.')
  return result as T
}

function launchData(): string {
  const launch = getInitData()
  if (!launch) throw new Error('Откройте приложение из Telegram для подтверждения доступа.')
  return launch
}

export async function fetchAccountPreviewSettings(signal?: AbortSignal): Promise<AccountPreviewSettings> {
  const result = await request<{ settings: AccountPreviewSettings }>('settings', {
    headers: { 'X-Telegram-Init-Data': launchData() }, signal,
  })
  return result.settings
}

export async function saveAccountPreviewSettings(
  settings: Omit<AccountPreviewSettings, 'revision'>, expectedRevision: number, signal?: AbortSignal,
): Promise<AccountPreviewSettings> {
  const result = await request<{ settings: AccountPreviewSettings }>('settings', {
    method: 'PUT', signal,
    body: JSON.stringify({ init_data: launchData(), expected_revision: expectedRevision, settings }),
  })
  return result.settings
}

export async function checkAccountPreviewLogin(signal?: AbortSignal): Promise<void> {
  const login = await request<{ session_token: string; account: { id: string } }>('session', {
    method: 'POST', signal, body: JSON.stringify({ platform: 'telegram', launch_data: launchData() }),
  })
  // The token lives only in this operation's memory, never in a URL/storage.
  const headers = { Authorization: `Bearer ${login.session_token}` }
  let profileFailed = false
  try {
    const profile = await request<{ account: { id: string } }>('me', { headers, signal })
    if (profile.account.id !== login.account.id) throw new Error('Не удалось подтвердить аккаунт.')
  } catch (error) {
    profileFailed = true
    throw error
  } finally {
    const cleanup = new AbortController()
    const timeout = setTimeout(() => cleanup.abort(), 3000)
    try {
      await request('logout', { method: 'POST', headers, signal: cleanup.signal })
    } catch (error) {
      if (!profileFailed) throw error
    } finally {
      clearTimeout(timeout)
    }
  }
}
