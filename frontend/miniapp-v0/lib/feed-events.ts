import type { FeedItem } from './types'

const STORAGE_KEY = 'banano:pending-publication'
const MAX_AGE_MS = 2 * 60 * 1000

export function notifyFeedChanged(item?: FeedItem): void {
  if (typeof window === 'undefined') return
  if (item) {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ item, savedAt: Date.now() }))
    } catch {
      // The event still refreshes mounted tabs when storage is unavailable.
    }
  }
  window.dispatchEvent(new CustomEvent<FeedItem | undefined>('banano:feed-changed', { detail: item }))
}

function pendingPublication(): FeedItem | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw) as { item?: FeedItem; savedAt?: number }
    if (!value.item?.id || Date.now() - Number(value.savedAt || 0) > MAX_AGE_MS) {
      window.sessionStorage.removeItem(STORAGE_KEY)
      return null
    }
    return value.item
  } catch {
    return null
  }
}

export function mergePendingPublication(items: FeedItem[], scope: 'feed' | 'profile'): FeedItem[] {
  const pending = pendingPublication()
  if (!pending || (scope === 'feed' && pending.publication_scope !== 'feed')) return items
  return [pending, ...items.filter((item) => item.id !== pending.id)]
}
