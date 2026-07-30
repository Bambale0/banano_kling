import type { FeedItem } from './types'

const STORAGE_KEY = 'banano:pending-publication'
const MAX_AGE_MS = 2 * 60 * 1000

type PendingPublication = {
  item: FeedItem
  savedAt: number
}

// Telegram WebView may reject or delay sessionStorage writes. Keep the latest
// publication in memory as the primary same-session source of truth, then use
// sessionStorage only as a fallback across tab remounts.
let latestPublication: PendingPublication | null = null

function isFresh(value: PendingPublication | null): value is PendingPublication {
  return Boolean(
    value?.item?.id &&
      Number.isFinite(value.savedAt) &&
      Date.now() - value.savedAt <= MAX_AGE_MS
  )
}

function isVisibleOnSurface(item: FeedItem, scope: 'feed' | 'profile'): boolean {
  if (scope === 'feed') return item.publication_scope === 'feed'
  return item.publication_scope !== 'private' && item.is_profile_visible !== false
}

export function notifyFeedChanged(item?: FeedItem): void {
  if (typeof window === 'undefined') return
  if (item) {
    latestPublication = { item, savedAt: Date.now() }
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(latestPublication))
    } catch {
      // The in-memory copy still lets mounted and remounted profile tabs update.
    }
  }
  window.dispatchEvent(new CustomEvent<FeedItem | undefined>('banano:feed-changed', { detail: item }))
}

function pendingPublication(): FeedItem | null {
  if (isFresh(latestPublication)) return latestPublication.item
  latestPublication = null

  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw) as PendingPublication
    if (!isFresh(value)) {
      window.sessionStorage.removeItem(STORAGE_KEY)
      return null
    }
    latestPublication = value
    return value.item
  } catch {
    return null
  }
}

export function mergePublication(
  items: FeedItem[],
  item: FeedItem | null | undefined,
  scope: 'feed' | 'profile'
): FeedItem[] {
  if (!item?.id || !isVisibleOnSurface(item, scope)) return items
  return [item, ...items.filter((current) => current.id !== item.id)]
}

export function mergePendingPublication(items: FeedItem[], scope: 'feed' | 'profile'): FeedItem[] {
  return mergePublication(items, pendingPublication(), scope)
}
