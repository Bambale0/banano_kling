import { getApiBasePath, getInitData } from './api'
import { accountLaunch } from './account-platform'

export interface AccountPreviewSettings {
  enabled: boolean
  revision: number
  vk_app_id: number | null
  vk_admin_ids: number[]
  session_ttl_seconds: number
  launch_max_age_seconds: number
  link_ttl_seconds?: number
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBasePath()}/account-preview/${path}`, {
    ...init,
    cache: 'no-store',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })
  if (response.status === 409) throw new Error(path.startsWith('links') ? 'Состояние связи изменилось. Нажмите «Обновить статус».' : path === 'wallet' ? 'Операция уже обработана с другими параметрами или резерв закрыт.' : 'Настройки изменились. Обновите страницу.')
  if (response.status === 410) throw new Error('Ссылка истекла или отменена. Создайте новую.')
  if (response.status === 401) throw new Error('Откройте приложение заново для подтверждения входа.')
  if (response.status === 403) throw new Error('Требуется доступ администратора.')
  if (response.status === 402) throw new Error('Недостаточно доступных тестовых средств.')
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

async function withPreviewSession<T>(operation: (headers: Record<string, string>, accountId: string) => Promise<T>, signal?: AbortSignal): Promise<T> {
  const login = await request<{ session_token: string; account: { id: string } }>('session', {
    method: 'POST', signal, body: JSON.stringify(accountLaunch()),
  })
  // The token lives only in this operation's memory, never in a URL/storage.
  const headers = { Authorization: `Bearer ${login.session_token}` }
  let profileFailed = false
  try {
    return await operation(headers, login.account.id)
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

export async function checkAccountPreviewLogin(signal?: AbortSignal): Promise<void> {
  await withPreviewSession(async (headers, accountId) => {
    const profile = await request<{ account: { id: string } }>('me', { headers, signal })
    if (profile.account.id !== accountId) throw new Error('Не удалось подтвердить аккаунт.')
  }, signal)
}

export interface PreviewWalletReceipt {
  operation_key: string
  kind: string
  amount: string
  reference_key: string
  sequence: number
  replayed?: boolean
}

export interface PreviewWallet {
  scope: 'sandbox'
  balance: { available: string; reserved: string; revision: number }
  entries: PreviewWalletReceipt[]
  receipt: PreviewWalletReceipt | null
}

export interface PreviewWalletOperation {
  action: 'credit' | 'reserve' | 'capture' | 'release' | 'refund'
  amount: string
  idempotency_key: string
  reference_key: string
}

export async function fetchAccountPreviewWallet(signal?: AbortSignal): Promise<PreviewWallet> {
  return withPreviewSession(headers => request<PreviewWallet>('wallet', { headers, signal }), signal)
}

export async function applyAccountPreviewWallet(operation: PreviewWalletOperation, signal?: AbortSignal): Promise<PreviewWallet> {
  return withPreviewSession(headers => request<PreviewWallet>('wallet', { method: 'POST', headers, signal, body: JSON.stringify(operation) }), signal)
}

export interface AccountLink {
  id: string
  state: 'pending' | 'awaiting_confirmation' | 'committed' | 'cancelled'
  revision: number
  expires_at_epoch: number
  source_platform?: 'telegram' | 'vk'
  target_platform?: 'telegram' | 'vk'
  source_confirmed?: boolean
  target_confirmed?: boolean
  account_id?: string | null
  token?: string
  source_identity?: { platform: 'telegram' | 'vk'; external_id: string }
  target_identity?: { platform: 'telegram' | 'vk'; external_id: string } | null
}

export async function createAccountLink(targetPlatform: 'telegram' | 'vk', signal?: AbortSignal): Promise<AccountLink> {
  return withPreviewSession(async headers => (await request<{ link: AccountLink }>('links', {
    method: 'POST', headers, signal, body: JSON.stringify({ target_platform: targetPlatform }),
  })).link, signal)
}

export async function acceptAccountLink(token: string, signal?: AbortSignal): Promise<AccountLink> {
  return withPreviewSession(async headers => (await request<{ link: AccountLink }>('links/accept', {
    method: 'POST', headers, signal, body: JSON.stringify({ token }),
  })).link, signal)
}

export async function updateAccountLink(link: AccountLink, action: 'get' | 'confirm' | 'cancel', signal?: AbortSignal): Promise<AccountLink> {
  return withPreviewSession(async headers => (await request<{ link: AccountLink }>(`links/${link.id}${action === 'get' ? '' : '/' + action}`, {
    method: action === 'get' ? 'GET' : 'POST', headers, signal,
    ...(action === 'get' ? {} : { body: JSON.stringify({ expected_revision: link.revision }) }),
  })).link, signal)
}

export async function fetchAccountPreviewAccess(signal?: AbortSignal): Promise<{ revision: number; vk_app_id: number | null }> {
  return withPreviewSession(async headers => (await request<{ preview: { revision: number; vk_app_id: number | null } }>('me', { headers, signal })).preview, signal)
}

export interface PreviewWalletReconciliation {
  scope: 'sandbox'
  consistent: boolean
  issues: string[]
  ledger_entries: number
  open_reservations: number
  balance: PreviewWallet['balance']
}

export async function reconcileAccountPreviewWallet(signal?: AbortSignal): Promise<PreviewWalletReconciliation> {
  return withPreviewSession(headers => request<PreviewWalletReconciliation>('wallet/reconcile', { headers, signal }), signal)
}
