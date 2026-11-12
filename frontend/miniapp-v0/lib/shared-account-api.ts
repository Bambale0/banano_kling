import { clearPlatformSessionToken, getApiBasePath, getInitData, setPlatformSessionToken } from './api'
import { accountLaunch, currentAccountPlatform, setVerifiedVkCommunity, type AccountPlatform } from './account-platform'
import type { Task } from './types'

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
  if (response.status === 409 && (path === 'vk-image' || path === 'vk-trend')) throw new Error('Этот запрос уже используется для другой генерации. Измените данные и создайте новый запрос.')
  if (response.status === 409) throw new Error(path.startsWith('links') ? 'Состояние связи или индивидуальные условия изменились. Обновите статус и проверьте настройки аккаунтов.' : path === 'wallet' ? 'Операция уже обработана с другими параметрами или резерв закрыт.' : 'Настройки изменились. Обновите страницу.')
  if (response.status === 410) throw new Error('Ссылка истекла или отменена. Создайте новую.')
  if (response.status === 401) throw new Error('Откройте приложение заново для подтверждения входа.')
  if (response.status === 403 && path.startsWith('vk-')) throw new Error('VK-аккаунт не может выполнить операцию. Проверьте доступ к боту.')
  if (response.status === 403) throw new Error(path.startsWith('links')
    ? 'Это приглашение предназначено другому аккаунту или платформе.'
    : 'Требуется доступ администратора.')
  if (response.status === 402) throw new Error(path.startsWith('vk-') ? 'Недостаточно бананов на VK-балансе.' : 'Недостаточно доступных тестовых средств.')
  if (response.status === 404 && path.startsWith('trends?view=feed_item&gen_id=')) {
    throw new Error('Публикация не найдена.')
  }
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
  // A signed VK Mini App already keeps its session in memory. Reuse it for
  // profile/history/discovery instead of re-signing the original vk_ts query
  // on every refresh (VK launch signatures expire while the app stays open).
  if (activeAppSessionToken && activeAppSessionPlatform === 'vk' && currentAccountPlatform() === 'vk') {
    return operation({ Authorization: `Bearer ${activeAppSessionToken}` }, activeAppAccountId)
  }
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

export async function createAccountLink(targetPlatform: 'telegram' | 'vk', signal?: AbortSignal, confirmSource = false): Promise<AccountLink> {
  return withPreviewSession(async headers => (await request<{ link: AccountLink }>('links', {
    method: 'POST', headers, signal, body: JSON.stringify({ target_platform: targetPlatform, confirm_source: confirmSource }),
  })).link, signal)
}

export async function acceptAccountLink(token: string, signal?: AbortSignal, confirm = false): Promise<AccountLink> {
  return withPreviewSession(async headers => (await request<{ link: AccountLink }>('links/accept', {
    method: 'POST', headers, signal, body: JSON.stringify({ token, confirm }),
  })).link, signal)
}

export async function previewAccountLink(token: string, signal?: AbortSignal): Promise<AccountLink> {
  return withPreviewSession(async headers => (await request<{ link: AccountLink }>('links/preview', {
    method: 'POST', headers, signal, body: JSON.stringify({ token }),
  })).link, signal)
}

export async function updateAccountLink(link: AccountLink, action: 'get' | 'confirm' | 'cancel', signal?: AbortSignal): Promise<AccountLink> {
  return withPreviewSession(async headers => (await request<{ link: AccountLink }>(`links/${link.id}${action === 'get' ? '' : '/' + action}`, {
    method: action === 'get' ? 'GET' : 'POST', headers, signal,
    ...(action === 'get' ? {} : { body: JSON.stringify({ expected_revision: link.revision }) }),
  })).link, signal)
}

export interface VkNativeTask {
  task_id: number
  task_type: string
  model: string
  status: string
  cost: number
  result_url: string | null
  created_at: string
}

export interface VkNativeState {
  ok: true
  registered: boolean
  balance: number | null
  is_blocked: boolean
  tasks: VkNativeTask[]
  /** Same task-card DTO as Telegram Mini App; native VK history remains authoritative. */
  recent_tasks?: Task[]
}

export async function fetchVkNativeState(signal?: AbortSignal): Promise<VkNativeState> {
  // Resolve a fresh signed VK identity for each read. The native VK balance
  // is NEVER inferred from a Telegram identity or a client-supplied user ID.
  return withPreviewSession(headers => request<VkNativeState>(
    'vk-native-state', { headers, signal },
  ), signal)
}

export interface VkNativeModelCatalog {
  ok: true
  photo_models: {
    id: string
    label: string
    ratios: string[]
    resolutions: string[]
    max_references: number
  }[]
  video_models: {
    id: string
    label: string
    ratios: string[]
    duration_min: number
    duration_max: number
    scenarios: ('text' | 'imgtxt')[]
    max_image_references: number
  }[]
}

export async function fetchVkModelCatalog(signal?: AbortSignal): Promise<VkNativeModelCatalog> {
  // Only the signed VK actor's real native worker may define capabilities.
  return withPreviewSession(headers => request<VkNativeModelCatalog>('vk-models', {
    headers, signal,
  }), signal)
}

export interface VkNativeCommerce {
  ok: true
  registered: boolean
  balance: number | null
  payment_packages: { id: string; price_rub: number; credits: number; lava_offer_id: string | null; methods: string[] }[]
  payments: { amount_rub: number; status: 'paid' | 'pending' | 'failed'; created_at: string }[]
  referrals: { first_level_count: number; second_level_count: number; earned_rub: number }
}

export async function fetchVkNativeCommerce(signal?: AbortSignal): Promise<VkNativeCommerce> {
  // Native VK session owns the actor ID. No Telegram account projection.
  return withPreviewSession(headers => request<VkNativeCommerce>('vk-commerce', { headers, signal }), signal)
}

export interface VkPublicTrend {
  id: number
  share_link?: string | null
  can_repeat_in_app?: boolean
  user_fields?: { key: string; label: string; type?: 'text' | 'number' | 'date'; field_type?: string; required?: boolean; max_length?: number }[]
  title: string
  description: string
  preview_url: string | null
  preview_poster_url: string | null
  generation_type: 'image' | 'video'
}

export interface VkPublicTrendCategory {
  id: number | string
  title: string
  emoji: string
  total: number
  items: VkPublicTrend[]
}

export interface VkPublicFeedItem {
  id: number
  generation_type: 'image' | 'video'
  preview_url: string | null
  result_url: string | null
  likes_count: number
}

export type VkPublicDiscovery =
  | { ok: true; categories: VkPublicTrendCategory[]; can_generate_in_app: boolean }
  | { ok: true; items: VkPublicFeedItem[]; can_generate_in_app: boolean }

export async function fetchVkPublicDiscovery(
  view: 'trends' | 'feed',
  signal?: AbortSignal,
): Promise<VkPublicDiscovery> {
  // A new signed VK bearer is scoped to this read-only request, then revoked.
  // Never create or impersonate a Telegram user to fetch public media.
  return withPreviewSession(headers => request<VkPublicDiscovery>(
    'trends' + (view === 'feed' ? '?view=feed' : ''),
    { headers, signal },
  ), signal)
}

export interface VkPublicTrendLink {
  ok: true
  item: VkPublicTrend
  can_generate_in_app: boolean
}

export async function fetchVkPublicTrend(
  trendId: number, signal?: AbortSignal,
): Promise<VkPublicTrendLink> {
  if (!Number.isSafeInteger(trendId) || trendId < 1) {
    throw new Error('Некорректный тренд по ссылке.')
  }
  return withPreviewSession(headers => request<VkPublicTrendLink>(
    'trends?view=item&trend_id=' + trendId, { headers, signal },
  ), signal)
}

/** One public feed publication; NOT an editorial trend/prompt recipe.
 * Original references and prompts are deliberately excluded from this API.
 */
export interface VkPublicFeedLink {
  ok: true
  item: {
    id: number
    generation_type: 'image' | 'video'
    model: string
    preview_url: string | null
    preview_poster_url?: string | null
    result_url: string | null
    likes_count: number
    shares_count: number
    comments_count: number
    aspect_ratio: string
    duration?: number | null
    feed_blurred: boolean
    media_unavailable: boolean
    share_link: string
    /** Native VK feed remix is a separate authorized operation, not this read. */
    can_repeat_in_app: false
  }
}

export async function fetchVkPublicFeedItem(
  feedGenId: number, signal?: AbortSignal,
): Promise<VkPublicFeedLink> {
  if (!Number.isSafeInteger(feedGenId) || feedGenId < 1) {
    throw new Error('Некорректная публикация из ленты.')
  }
  return withPreviewSession(headers => request<VkPublicFeedLink>(
    'trends?view=feed_item&gen_id=' + feedGenId, { headers, signal },
  ), signal)
}

export interface VkPublicCategoryPage {
  ok: true
  category: { id: number | string; title: string; emoji: string }
  items: VkPublicTrend[]
  page: number
  has_more: boolean
  can_generate_in_app: boolean
}

export async function fetchVkPublicCategory(
  categoryId: number | string, page = 1, signal?: AbortSignal,
): Promise<VkPublicCategoryPage> {
  if (!Number.isSafeInteger(page) || page < 1 || page > 1000) {
    throw new Error('Некорректная страница трендов.')
  }
  return withPreviewSession(headers => request<VkPublicCategoryPage>(
    'trends?view=category&category_id=' + encodeURIComponent(categoryId) + '&page=' + page,
    { headers, signal },
  ), signal)
}

export interface VkNativeGenerationResult {
  ok: true
  task_id: number
  cost: number
  quote_only?: boolean
}

export interface VkImageRequest {
  model: string
  prompt: string
  aspect: string
  resolution: string
  reference_photos: string[]
  client_request_id?: string
  quote_only?: boolean
  expected_cost?: number
}

export interface VkTrendRequest {
  trend_id: number
  reference_urls: string[]
  user_values: Record<string, string>
  client_request_id?: string
  quote_only?: boolean
  expected_cost?: number
}

// The shared-account backend rejects request bodies above 32 KiB. Count
// UTF-8 bytes (not JS characters) before creating a session or uploading data.
function vkGenerationBody(payload: VkImageRequest | VkTrendRequest): string {
  const body = JSON.stringify(payload)
  if (new Blob([body]).size > 32768) {
    throw new Error('Сократите промпт или число референсов: запрос слишком большой.')
  }
  return body
}

export async function generateVkImage(payload: VkImageRequest, signal?: AbortSignal) {
  const body = vkGenerationBody(payload)
  return withPreviewSession(headers => request<VkNativeGenerationResult>('vk-image', {
    method: 'POST', headers, body, signal,
  }), signal)
}

export async function repeatVkTrend(payload: VkTrendRequest, signal?: AbortSignal) {
  const body = vkGenerationBody(payload)
  return withPreviewSession(headers => request<VkNativeGenerationResult>('vk-trend', {
    method: 'POST', headers, body, signal,
  }), signal)
}

export async function uploadVkImage(file: File, signal?: AbortSignal): Promise<string> {
  if (!file || !file.size || file.size > 12 * 1024 * 1024) {
    throw new Error('Фото должно быть не больше 12 МБ.')
  }
  return withPreviewSession(async headers => {
    const body = new FormData()
    body.append('image', file)
    const response = await fetch(getApiBasePath() + '/account-preview/vk-image-upload', {
      method: 'POST', cache: 'no-store', credentials: 'same-origin', headers,
      body, signal,
    })
    if (response.status === 401) throw new Error('Откройте приложение заново для подтверждения входа.')
    if (response.status === 413) throw new Error('Фото слишком большое. Используйте файл до 12 МБ.')
    if (!response.ok) throw new Error('Не удалось загрузить фото. Попробуйте другое изображение.')
    const data = await response.json() as { ok?: boolean; url?: string }
    if (!data.ok || !data.url || !/^https:\/\//.test(data.url)) {
      throw new Error('Не удалось получить сохранённое фото.')
    }
    return data.url
  }, signal)
}

export interface AccountPreviewAccess {
  revision: number
  vk_app_id: number | null
  vk_community_id?: number | null
  telegram_bot_username: string
  telegram_linked: boolean
  /** Server-advertised readiness for every shared-shell operation. Not an identity link. */
  full_app_ready?: boolean
  linked_platforms?: ('telegram' | 'vk')[]
}

let activeAppSessionToken = ''
let activeAppAccountId = ''
let activeAppSessionPlatform: AccountPlatform | null = null

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
  const verifiedLaunch = accountLaunch()
  const login = await request<{ session_token: string; account: { id: string } }>('session', {
    method: 'POST',
    signal,
    body: JSON.stringify(verifiedLaunch),
  })
  const token = login.session_token
  if (!/^[A-Za-z0-9_-]{43}$/.test(token)) throw new Error('Не удалось подтвердить сессию ВК.')
  try {
    const profile = await request<{ account: { id: string }; preview: AccountPreviewAccess }>('me', {
      signal,
      headers: { Authorization: `Bearer ${token}` },
    })
    if (profile.account.id !== login.account.id) throw new Error('Не удалось подтвердить аккаунт.')
    // Even an unlinked VK account owns a real VK-side balance and history.
    // Keep the same revocable session in memory for these endpoints without
    // inventing a Telegram user or exposing the bearer to URL/storage.
    setPlatformSessionToken(token)
    activeAppSessionToken = token
    activeAppAccountId = login.account.id
    activeAppSessionPlatform = verifiedLaunch.platform
    setVerifiedVkCommunity(
      verifiedLaunch.platform === 'vk' ? profile.preview.vk_app_id : null,
      verifiedLaunch.platform === 'vk' ? (profile.preview.vk_community_id ?? null) : null,
    )
    return profile.preview
  } catch (error) {
    await revokeAppSession(token)
    throw error
  }
}

export async function stopAccountAppSession(): Promise<void> {
  const token = activeAppSessionToken
  activeAppSessionToken = ''
  activeAppAccountId = ''
  activeAppSessionPlatform = null
  setVerifiedVkCommunity(null, null)
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
