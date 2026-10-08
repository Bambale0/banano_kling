import type { Task } from './types'

export interface PendingVideoRepeat { sourceFeedGenId: number; taskId?: string }
const STORAGE_KEY = 'banano:accepted-video-repeats'
export const VIDEO_REPEAT_PENDING_CHANGED = 'banano:video-repeat-pending-changed'
let memory: Record<string, PendingVideoRepeat> = {}
let storageUnavailable = false

function pendingRepeats() {
  if (typeof window !== 'undefined' && !storageUnavailable) {
    try {
      const data: unknown = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || '{}')
      memory = {}
      if (data && typeof data === 'object') {
        for (const value of Object.values(data)) {
          if (value && Number.isInteger(value.sourceFeedGenId) && value.sourceFeedGenId > 0) {
            memory[value.sourceFeedGenId] = { sourceFeedGenId: value.sourceFeedGenId,
              ...(typeof value.taskId === 'string' && value.taskId ? { taskId: value.taskId } : {}) }
          }
        }
      }
    } catch { storageUnavailable = true }
  }
  return memory
}

function savePendingRepeats() {
  if (typeof window === 'undefined') return
  if (!storageUnavailable) {
    try { window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(memory)) }
    catch { storageUnavailable = true }
  }
  window.dispatchEvent(new Event(VIDEO_REPEAT_PENDING_CHANGED))
}

export function getPendingVideoRepeat(sourceFeedGenId?: number | null): PendingVideoRepeat | null {
  return sourceFeedGenId ? pendingRepeats()[sourceFeedGenId] || null : null
}

export function markVideoRepeatPending(sourceFeedGenId: number, taskId?: string) {
  memory = { ...pendingRepeats(), [sourceFeedGenId]: { sourceFeedGenId, ...(taskId ? { taskId } : {}) } }
  savePendingRepeats()
}

// Only the existing authenticated history/detail seam can resolve acceptance.
// Time passing, an empty refresh or reopening the form never permits a retry.
export function reconcilePendingVideoRepeats(tasks: Task[]) {
  const pending = pendingRepeats()
  let changed = false
  for (const [key, value] of Object.entries(pending)) {
    if (value.taskId && tasks.some((task) => task.task_id === value.taskId
      && (task.status === 'completed' || task.status === 'failed'))) {
      delete pending[key]
      changed = true
    }
  }
  if (changed) savePendingRepeats()
}

export function getPendingVideoTaskIds(): string[] {
  return [...new Set(Object.values(pendingRepeats()).flatMap((item) => item.taskId ? [item.taskId] : []))]
}

// Only call for a successful authenticated task-detail response to this exact
// requested ID. The server may resolve an owned local receipt to its provider ID.
export function reconcilePendingVideoDetail(requestedTaskId: string, task: Task) {
  if (!task?.task_id || !['pending', 'completed', 'failed'].includes(task.status)) return
  const pending = pendingRepeats()
  let changed = false
  for (const [key, value] of Object.entries(pending)) {
    if (value.taskId !== requestedTaskId) continue
    if (task.status === 'completed' || task.status === 'failed') {
      delete pending[key]
      changed = true
    } else if (task.task_id !== value.taskId) {
      pending[key] = { ...value, taskId: task.task_id }
      changed = true
    }
  }
  if (changed) savePendingRepeats()
}

export function isVideoStatusPending(error: unknown): error is Error & { code: string; taskId?: string } {
  return error instanceof Error && 'code' in error && error.code === 'video_status_pending'
}
