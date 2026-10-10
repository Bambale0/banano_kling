import type { Seedance25GeneratePayload } from './seedance25-api'

export interface PendingSeedanceLaunch { quoteId: string; payload: Seedance25GeneratePayload }

export function seedancePendingKey(initData: string): string | null {
  try {
    const user = JSON.parse(new URLSearchParams(initData).get('user') || 'null')
    return user?.id ? `seedance25-pending:${user.id}` : null
  } catch { return null }
}

export function readPendingSeedance(storage: Storage, key: string): PendingSeedanceLaunch | null {
  try {
    const value = JSON.parse(storage.getItem(key) || 'null')
    return value && /^[a-f0-9]{32}$/.test(value.quoteId) && value.payload?.videoQuoteId === value.quoteId ? value : null
  } catch { return null }
}

export function clearPendingSeedance(storage: Storage, key: string, quoteId: string): boolean {
  if (readPendingSeedance(storage, key)?.quoteId !== quoteId) return false
  storage.removeItem(key)
  return true
}
