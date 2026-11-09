import { getInitData, getRuntimeBotUsername, getStartParamFallback } from './api'

export type AccountPlatform = 'telegram' | 'vk'

export function currentAccountPlatform(): AccountPlatform {
  if (typeof window === 'undefined') return process.env.NEXT_PUBLIC_MINIAPP_PLATFORM === 'vk' ? 'vk' : 'telegram'
  const params = new URLSearchParams(window.location.search)
  return process.env.NEXT_PUBLIC_MINIAPP_PLATFORM === 'vk' || params.has('vk_app_id') || params.has('vk_user_id')
    ? 'vk'
    : 'telegram'
}

export function platformMiniAppUrl(startParam: string, telegramBotUsername = ''): string {
  const param = String(startParam || '').trim()
  if (!param) return ''
  if (currentAccountPlatform() === 'vk') {
    if (typeof window === 'undefined') return ''
    const appId = Number(new URLSearchParams(window.location.search).get('vk_app_id') || 0)
    return Number.isSafeInteger(appId) && appId > 0
      ? `https://vk.com/app${appId}#${encodeURIComponent(param)}`
      : ''
  }
  const username = telegramBotUsername.trim().replace(/^@/, '') || getRuntimeBotUsername()
  return /^[A-Za-z0-9_]+$/.test(username)
    ? `https://t.me/${username}?startapp=${encodeURIComponent(param)}`
    : ''
}


export function accountLaunch(): { platform: AccountPlatform; launch_data: string } {
  if (typeof window === 'undefined') throw new Error('Откройте приложение из ТГ или ВК.')
  // Explicit VK launch wins over a previous Telegram session in this browser.
  // The server verifies the entire signed query and its freshness.
  const search = window.location.search.slice(1)
  const params = new URLSearchParams(search)
  if (params.has('vk_app_id') || params.has('vk_user_id')) return { platform: 'vk', launch_data: search }
  if (process.env.NEXT_PUBLIC_MINIAPP_PLATFORM === 'vk') throw new Error('Откройте приложение из ВКонтакте.')
  const launch = getInitData()
  if (!launch) throw new Error('Откройте приложение из ТГ или ВК для подтверждения входа.')
  return { platform: 'telegram', launch_data: launch }
}

export function accountLinkUrl(platform: AccountPlatform, token: string, vkAppId: number | null, telegramBotUsername = ''): string {
  if (!/^[A-Za-z0-9_-]{43}$/.test(token)) throw new Error('Некорректная ссылка.')
  if (platform === 'vk') {
    if (!vkAppId) throw new Error('Сначала укажите ID приложения ВК.')
    return `https://vk.com/app${vkAppId}#link_${token}`
  }
  const username = telegramBotUsername.trim().replace(/^@/, '') || getRuntimeBotUsername()
  if (!/^[A-Za-z0-9_]+$/.test(username)) throw new Error('Имя бота пока не настроено.')
  return `https://t.me/${username}?startapp=link_${token}`
}

/** Build an OS-handled deep link only from a validated account-link invitation. */
export function nativeTelegramMiniAppUrl(httpsLink: string): string {
  let url: URL
  try {
    url = new URL(httpsLink)
  } catch {
    throw new Error('Некорректная ссылка.')
  }

  const username = url.pathname.slice(1)
  const startParam = url.searchParams.get('startapp')
  if (
    url.protocol !== 'https:' || url.hostname !== 't.me' || url.port ||
    url.username || url.password || url.hash ||
    !/^[A-Za-z0-9_]+$/.test(username) ||
    !startParam || !/^link_[A-Za-z0-9_-]{43}$/.test(startParam) ||
    [...url.searchParams.keys()].length !== 1
  ) {
    throw new Error('Некорректная ссылка.')
  }
  return `tg://resolve?domain=${encodeURIComponent(username)}&startapp=${encodeURIComponent(startParam)}`
}

export function incomingAccountLink(): string {
  if (typeof window === 'undefined') return ''
  const hash = window.location.hash.slice(1)
  const params = new URLSearchParams(window.location.search)
  const vk = process.env.NEXT_PUBLIC_MINIAPP_PLATFORM === 'vk' || params.has('vk_app_id') || params.has('vk_user_id')
  const start = vk ? '' : (new URLSearchParams(getInitData()).get('start_param') || getStartParamFallback())
  const initialHash = (window.__BANANO_INITIAL_LAUNCH__?.hash || '').replace(/^#/, '')
  const candidate = [hash, initialHash, start].find(value => /^link_[A-Za-z0-9_-]{43}$/.test(value)) || ''
  return candidate.slice(5)
}
