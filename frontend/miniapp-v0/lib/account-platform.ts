import { getInitData, getRuntimeBotUsername } from './api'

export type AccountPlatform = 'telegram' | 'vk'

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

export function incomingAccountLink(): string {
  if (typeof window === 'undefined') return ''
  const hash = window.location.hash.slice(1)
  const params = new URLSearchParams(window.location.search)
  const vk = process.env.NEXT_PUBLIC_MINIAPP_PLATFORM === 'vk' || params.has('vk_app_id') || params.has('vk_user_id')
  const start = vk ? '' : new URLSearchParams(getInitData()).get('start_param') || ''
  const initialHash = (window.__BANANO_INITIAL_LAUNCH__?.hash || '').replace(/^#/, '')
  const candidate = [hash, initialHash, start].find(value => /^link_[A-Za-z0-9_-]{43}$/.test(value)) || ''
  return candidate.slice(5)
}
