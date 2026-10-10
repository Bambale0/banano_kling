/** Owner-keyed pending receipt state. Old responses cannot clear a newer launch. */
export function pendingMotionId(raw: string | null): string | null {
  if (!raw) return null
  try {
    const saved = JSON.parse(raw)
    return typeof saved.requestId === 'string' && /^[a-f0-9]{32}$/.test(saved.requestId) ? saved.requestId : null
  } catch { return null }
}

export function clearPendingMotion(storage: Pick<Storage, 'getItem' | 'removeItem'>, key: string, requestId: string): boolean {
  if (pendingMotionId(storage.getItem(key)) !== requestId) return false
  storage.removeItem(key)
  return true
}
