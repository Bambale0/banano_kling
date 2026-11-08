import { clearPlatformSessionToken, getApiBasePath, getInitData, setPlatformSessionToken } from './api'
import { accountLaunch } from './account-platform'

export interface AccountPreviewSettings {
  enabled: boolean
  revision: number
  vk_app_id: number | null
  vk_admin_ids: number[]
  session_ttl_seconds: number
  launch_max_age_seconds: number
  link_ttl_seconds?: number
  vk_community_id?: number | null
  vk_result_delivery_enabled?: boolean
  vk_delivery_max_attempts?: number
  vk_delivery_retry_seconds?: number
  vk_result_message_template?: string
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBasePath()}/account-preview/${path}`, {
    ...init,
    cache: 'no-store',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })
  if (response.status === 400 && path.startsWith('commerce')) {
    const result = await response.json().catch(() => ({}))
    throw new Error(result.error_code === 'commerce_invalid' ? result.error : 'Проверьте значения настроек.')
  }
  if (response.status === 400 && path === 'settings') {
    const result = await response.json().catch(() => ({}))
    throw new Error(result.error_code === 'vk_sender_unconfigured'
      ? 'Сначала подключите отправителя выбранного сообщества ВК на сервере.'
      : 'Проверьте значения настроек и текст сообщения ВК.')
  }
  if (response.status === 409 && path.startsWith('vk-deliveries/')) {
    const result = await response.json().catch(() => ({}))
    throw new Error(result.error_code === 'vk_delivery_uncertain'
      ? 'ВК не подтвердил отправку. Проверьте чат перед повторными действиями.'
      : 'Доставка пока недоступна или её статус изменился. Обновите статус.')
  }
  if (response.status === 409) throw new Error(path.startsWith('links') ? 'Состояние связи или индивидуальные условия изменились. Обновите статус и проверьте настройки аккаунтов.' : path === 'wallet' ? 'Операция уже обработана с другими параметрами или резерв закрыт.' : 'Настройки изменились. Обновите страницу.')
  if (response.status === 410) throw new Error('Ссылка истекла или отменена. Создайте новую.')
  if (response.status === 401) throw new Error('Откройте приложение заново для подтверждения входа.')
  if (response.status === 403) throw new Error('Требуется доступ администратора.')
  if (response.status === 402) throw new Error('Недостаточно доступных тестовых средств.')
  if (response.status === 404) throw new Error(path.startsWith('vk-deliveries/')
    ? 'Результат или доставка сейчас недоступны. Обновите список задач.' : 'Проверка аккаунтов пока выключена.')
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
  try {
    return await operation(headers, login.account.id)
  } finally {
    const cleanup = new AbortController()
    const timeout = setTimeout(() => cleanup.abort(), 3000)
    try {
      await request('logout', { method: 'POST', headers, signal: cleanup.signal })
    } catch {
      // Session cleanup is best-effort and must never turn a successful
      // idempotent operation (including account merge) into a client failure.
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

export interface AccountReferencePhoto {
  id: string
  mime: 'image/png'
  width: number
  height: number
  size_bytes: number
  created_at_epoch: number
}

export interface AccountReferencePage {
  references: Array<AccountReferencePhoto & { thumbnail: Blob | null }>
  next_offset: number | null
}

function ownedPhotoId(id: string): string {
  if (!/^[a-f0-9]{32}$/.test(id)) throw new Error('Фото недоступно. Обновите список.')
  return id
}

function photoMetadata(value: unknown): AccountReferencePhoto {
  if (!value || typeof value !== 'object') throw new Error('Не удалось прочитать данные фото. Обновите список.')
  const photo = value as AccountReferencePhoto
  ownedPhotoId(photo.id)
  if (photo.mime !== 'image/png' || !Number.isSafeInteger(photo.width) || photo.width <= 0
    || !Number.isSafeInteger(photo.height) || photo.height <= 0 || !Number.isSafeInteger(photo.size_bytes)
    || photo.size_bytes <= 0 || !Number.isSafeInteger(photo.created_at_epoch)) {
    throw new Error('Не удалось прочитать данные фото. Обновите список.')
  }
  const { id, mime, width, height, size_bytes, created_at_epoch } = photo
  return { id, mime, width, height, size_bytes, created_at_epoch }
}

async function photoJSON(response: Response): Promise<Record<string, unknown>> {
  const result: unknown = await response.json().catch(() => null)
  if (!result || typeof result !== 'object' || (result as Record<string, unknown>).ok !== true) {
    throw new Error('Не удалось прочитать ответ. Обновите список фото.')
  }
  return result as Record<string, unknown>
}

function checkPhotoAbort(signal?: AbortSignal | null): void {
  if (signal?.aborted) throw new DOMException('Request aborted', 'AbortError')
}

async function photoRequest(path: string, headers: Record<string, string>, init: RequestInit): Promise<Response> {
  checkPhotoAbort(init.signal)
  const result = await fetch(`${getApiBasePath()}/account-preview/references${path}`, {
    ...init, headers, credentials: 'same-origin', cache: 'no-store',
  })
  checkPhotoAbort(init.signal)
  if (result.ok) return result
  if (result.status === 401) throw new Error('Откройте приложение заново для подтверждения входа.')
  if (result.status === 403) throw new Error('Требуется доступ администратора.')
  const body = await result.json().catch(() => ({}))
  const messages: Record<string, string> = {
    media_decode_failed: 'Не удалось прочитать фото. Выберите другой файл.',
    image_format_not_supported: 'Этот формат фото не поддерживается. Используйте JPG, PNG или WEBP.',
    media_dimensions_limit: 'У фото слишком большое разрешение. Уменьшите его размер.',
    media_too_large: 'Файл слишком большой. Выберите фото меньшего размера.',
    empty_file: 'Файл пустой. Выберите другое фото.',
    upload_one_photo: 'Выберите одно фото для загрузки.',
    upload_timeout: 'Загрузка заняла слишком много времени. Повторите попытку.',
    reference_unavailable: 'Фото недоступно. Обновите список.',
    preview_unavailable: 'Проверка аккаунтов пока выключена.',
  }
  throw new Error(messages[body.error_code] || 'Не удалось выполнить запрос фото. Попробуйте ещё раз.')
}

async function withPhotoSession<T>(
  operation: (headers: Record<string, string>, signal: AbortSignal) => Promise<T>,
  signal?: AbortSignal, timeoutMs = 60_000,
): Promise<T> {
  checkPhotoAbort(signal)
  const controller = new AbortController()
  let stop!: (reason: Error) => void
  const interrupted = new Promise<never>((_resolve, reject) => { stop = reject })
  const cancel = () => {
    stop(new DOMException('Request aborted', 'AbortError'))
    controller.abort()
  }
  signal?.addEventListener('abort', cancel, { once: true })
  const timer = setTimeout(() => {
    stop(new Error('Запрос занял слишком много времени. Обновите список фото.'))
    controller.abort()
  }, timeoutMs)
  try {
    return await Promise.race([
      withPreviewSession(headers => {
        checkPhotoAbort(controller.signal)
        return operation(headers, controller.signal)
      }, controller.signal),
      interrupted,
    ])
  } catch (failure) {
    if (failure instanceof TypeError || failure instanceof SyntaxError) {
      throw new Error('Не удалось связаться с сервером. Обновите список фото.')
    }
    throw failure
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', cancel)
  }
}

export async function saveAccountReferencePhoto(file: File, signal?: AbortSignal): Promise<AccountReferencePhoto> {
  return withPhotoSession(async (headers, signal) => {
    const body = new FormData()
    body.append('file', file)
    const response = await photoRequest('', headers, { method: 'POST', body, signal })
    return photoMetadata((await photoJSON(response)).reference)
  }, signal, 900_000)
}

export async function fetchAccountReferencePhotos(offset = 0, signal?: AbortSignal): Promise<AccountReferencePage> {
  if (!Number.isSafeInteger(offset) || offset < 0) throw new Error('Обновите список фото.')
  return withPhotoSession(async (headers, signal) => {
    const response = await photoRequest(`?offset=${offset}`, headers, { signal })
    const data = await photoJSON(response)
    const next = data.next_offset
    if (!Array.isArray(data.references) || data.references.length > 24
      || (next !== null && (typeof next !== 'number' || !Number.isSafeInteger(next) || next <= offset))) {
      throw new Error('Не удалось прочитать список фото.')
    }
    const metadata = data.references.map(photoMetadata)
    const references = await Promise.all(metadata.map(async (photo: AccountReferencePhoto) => {
      try {
        const media = await photoRequest(`/${photo.id}/thumbnail`, headers, { signal })
        if (media.headers.get('Content-Type')?.split(';')[0].toLowerCase() !== 'image/png') throw new Error('Invalid image response')
        const thumbnail = await media.blob()
        if (thumbnail.type.split(';')[0].toLowerCase() !== 'image/png') throw new Error('Invalid image response')
        return { ...photo, thumbnail }
      } catch (error) {
        if (signal?.aborted) throw error
        return { ...photo, thumbnail: null }
      }
    }))
    return { references, next_offset: next as number | null }
  }, signal)
}

export async function removeAccountReferencePhoto(id: string, signal?: AbortSignal): Promise<void> {
  ownedPhotoId(id)
  await withPhotoSession(async (headers, signal) => {
    await photoJSON(await photoRequest(`/${id}`, headers, { method: 'DELETE', signal }))
  }, signal)
}

export type VkChatDeliveryState = 'not_applicable' | 'not_requested' | 'pending' | 'preparing' | 'sending'
  | 'delivered' | 'permission_required' | 'uncertain' | 'failed' | 'access_revoked' | 'configuration_required' | 'disabled'
export interface VkChatDeliveryStatus {
  state: VkChatDeliveryState
  community_id: number | null
  can_request: boolean
  representation?: 'photo' | 'link' | null
}

async function vkChatDelivery(taskId: string, post: boolean, signal?: AbortSignal): Promise<VkChatDeliveryStatus> {
  if (!taskId || taskId.length > 200) throw new Error('Откройте результат заново.')
  try {
    return await withPreviewSession(async headers => {
      const payload = await request<{ delivery: VkChatDeliveryStatus }>(`vk-deliveries/${encodeURIComponent(taskId)}`, {
        method: post ? 'POST' : 'GET', headers, signal, ...(post ? { body: '{}' } : {}),
      })
      const delivery = payload.delivery
      const states: VkChatDeliveryState[] = ['not_applicable', 'not_requested', 'pending', 'preparing', 'sending', 'delivered',
        'permission_required', 'uncertain', 'failed', 'access_revoked', 'configuration_required', 'disabled']
      if (!delivery || !states.includes(delivery.state) || typeof delivery.can_request !== 'boolean'
        || (delivery.community_id !== null && (!Number.isSafeInteger(delivery.community_id) || delivery.community_id <= 0))
        || (delivery.representation != null && !['photo', 'link'].includes(delivery.representation))) {
        throw new Error('Не удалось прочитать статус доставки. Обновите его.')
      }
      return { state: delivery.state, community_id: delivery.community_id, can_request: delivery.can_request,
        representation: delivery.representation ?? null }
    }, signal)
  } catch (failure) {
    if (failure instanceof TypeError || failure instanceof SyntaxError) throw new Error('Не удалось проверить доставку. Попробуйте ещё раз.')
    throw failure
  }
}

export const fetchVkChatDelivery = (taskId: string, signal?: AbortSignal) => vkChatDelivery(taskId, false, signal)
export const requestVkChatDelivery = (taskId: string, signal?: AbortSignal) => vkChatDelivery(taskId, true, signal)

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

export interface AccountPreviewAccess {
  revision: number
  vk_app_id: number | null
  telegram_bot_username: string
  telegram_linked: boolean
  linked_platforms?: ('telegram' | 'vk')[]
}

let activeAppSessionToken = ''

async function revokeAppSession(token: string): Promise<void> {
  if (!token) return
  try {
    await request('logout', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
  } catch {
    // Expiry, policy changes and account merges already revoke the session.
  }
}

export async function startAccountAppSession(signal?: AbortSignal): Promise<AccountPreviewAccess> {
  if (activeAppSessionToken) await stopAccountAppSession()
  const login = await request<{ session_token: string; account: { id: string } }>('session', {
    method: 'POST',
    signal,
    body: JSON.stringify(accountLaunch()),
  })
  const token = login.session_token
  if (!/^[A-Za-z0-9_-]{43}$/.test(token)) throw new Error('Не удалось подтвердить сессию ВК.')
  try {
    const profile = await request<{ account: { id: string }; preview: AccountPreviewAccess }>('me', {
      signal,
      headers: { Authorization: `Bearer ${token}` },
    })
    if (profile.account.id !== login.account.id) throw new Error('Не удалось подтвердить аккаунт.')
    if (!profile.preview.telegram_linked) {
      await revokeAppSession(token)
      return profile.preview
    }
    setPlatformSessionToken(token)
    activeAppSessionToken = token
    return profile.preview
  } catch (error) {
    await revokeAppSession(token)
    throw error
  }
}

export async function stopAccountAppSession(): Promise<void> {
  const token = activeAppSessionToken
  activeAppSessionToken = ''
  clearPlatformSessionToken()
  await revokeAppSession(token)
}

export async function fetchAccountPreviewAccess(signal?: AbortSignal): Promise<AccountPreviewAccess> {
  return withPreviewSession(async headers => (await request<{ preview: AccountPreviewAccess }>('me', { headers, signal })).preview, signal)
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

export interface CommercialCatalog {
  revision: number
  default_tariff_id: string | null
  default_partner_group_id: string | null
  tariffs: Record<string, { label: string; prices: Record<string, { amount: string; unit: 'job' | 'second' }> }>
  partner_groups: Record<string, { label: string; first_level_percent: string; second_level_percent: string; repeat_reward_rub: string }>
}
export interface CommercialTerms {
  revision: number
  tariff_id: string | null
  partner_group_id: string | null
  first_level_percent: string | null
  second_level_percent: string | null
  repeat_reward_rub: string | null
}
export interface CommercialTarget {
  account_id: string
  settings: CommercialTerms
  effective: Omit<CommercialTerms, 'revision'>
}
export interface CommercialQuote {
  id: string
  scope: 'preview'
  platform: 'telegram' | 'vk'
  total: string
  terms: CommercialTarget['effective']
  allowed_payment_providers: string[]
}
export async function fetchCommercialCatalog(signal?: AbortSignal): Promise<CommercialCatalog> {
  return withPreviewSession(async headers => (await request<{ catalog: CommercialCatalog }>('commerce', { headers, signal })).catalog, signal)
}
export async function saveCommercialCatalog(catalog: CommercialCatalog, signal?: AbortSignal): Promise<CommercialCatalog> {
  const { revision, ...settings } = catalog
  return withPreviewSession(async headers => (await request<{ catalog: CommercialCatalog }>('commerce', {
    method: 'PUT', headers, signal, body: JSON.stringify({ expected_revision: revision, settings }),
  })).catalog, signal)
}
export async function findCommercialAccount(platform: 'telegram' | 'vk', externalId: string, signal?: AbortSignal): Promise<CommercialTarget> {
  const query = new URLSearchParams({ platform, external_id: externalId })
  return withPreviewSession(async headers => (await request<{ target: CommercialTarget }>('commerce/accounts?' + query, { headers, signal })).target, signal)
}
export async function fetchOwnCommercialTerms(signal?: AbortSignal): Promise<CommercialTarget> {
  return withPreviewSession(async (headers, accountId) => (await request<{ target: CommercialTarget }>(`commerce/accounts/${accountId}`, { headers, signal })).target, signal)
}
export async function saveCommercialTerms(target: CommercialTarget, signal?: AbortSignal): Promise<CommercialTarget> {
  const { revision, ...settings } = target.settings
  return withPreviewSession(async headers => (await request<{ target: CommercialTarget }>(`commerce/accounts/${target.account_id}`, {
    method: 'PUT', headers, signal, body: JSON.stringify({ expected_revision: revision, settings }),
  })).target, signal)
}
export async function createCommercialQuote(priceKey: string, quantity: number, signal?: AbortSignal): Promise<CommercialQuote> {
  return withPreviewSession(async headers => (await request<{ quote: CommercialQuote }>('commerce/quote', {
    method: 'POST', headers, signal, body: JSON.stringify({ price_key: priceKey, quantity }),
  })).quote, signal)
}

export async function fetchCommercialTerms(accountId: string, signal?: AbortSignal): Promise<CommercialTarget> {
  return withPreviewSession(async headers => (await request<{ target: CommercialTarget }>(`commerce/accounts/${accountId}`, { headers, signal })).target, signal)
}
