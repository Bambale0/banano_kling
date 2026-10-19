'use client'

import { getApiBasePath, getInitData, getStartParamFallback } from './api'

export interface RepeatSlot {
  slot_id: string
  kind: 'image' | 'video' | 'audio'
  role: string
  label: string
  hint: string
  binding: 'fixed' | 'upload'
  required: boolean
  can_keep_original?: boolean
  added?: boolean
  min_files?: number
  max_files?: number
  constraints?: { mime_types?: string[]; max_bytes?: number; min_duration?: number; max_duration?: number; min_side?: number; max_side?: number }
}
export interface RepeatTemplate {
  contract_version: 1
  source_id: number
  version: number
  model: string
  type: 'image' | 'video'
  slots: RepeatSlot[]
  presets: Array<{ id: string; label: string; slot_ids: string[] }>
  variables: Array<{ id: string; label: string; required: boolean; max_length: number }>
  addable?: Partial<Record<'image' | 'video' | 'audio', { field: string; maximum: number }>>
}
export interface RepeatDraft {
  draft_id: string
  revision: number
  status: 'draft' | 'launching' | 'launched' | 'unknown' | 'rejected'
  template: RepeatTemplate
  preset_id: string | null
  prompt_changes?: string
  user_values: Record<string, string>
  slots: Record<string, { state: 'EMPTY' | 'UPLOADING' | 'PROCESSING' | 'READY' | 'FAILED'; asset_id?: string; url?: string; upload_token?: string; saved_reference_id?: string; wan3_media_id?: string; filename?: string | null }>
  quote: { cost: number; quote_id: string } | null
  task_id?: string | null
  result?: { status: number; body: Record<string, unknown> } | null
}

export class SmartRepeatApiError extends Error {
  constructor(message: string, public code: string) { super(message) }
}

export async function smartRepeatCall<T>(action: string, payload: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  const initData = getInitData()
  if (!initData) throw new SmartRepeatApiError('Откройте Mini App из Telegram.', 'AUTH_REQUIRED')
  const controller = new AbortController()
  const abort = () => controller.abort()
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) controller.abort()
  const timeout = setTimeout(abort, 120_000)
  try {
  const response = await fetch(`${getApiBasePath()}/repeat/${action}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
    body: JSON.stringify({ ...payload, init_data: initData, start_param_fallback: getStartParamFallback() }),
  })
  const result = await response.json()
  if (!response.ok || result.ok === false) throw new SmartRepeatApiError(result.error || 'Не удалось подтвердить повтор.', result.code || 'REPEAT_UNAVAILABLE')
  return result as T
  } finally { clearTimeout(timeout); signal?.removeEventListener('abort', abort) }
}
