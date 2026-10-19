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
}
export interface RepeatDraft {
  draft_id: string
  revision: number
  status: 'draft' | 'launching' | 'launched' | 'unknown'
  template: RepeatTemplate
  preset_id: string | null
  user_values: Record<string, string>
  slots: Record<string, { state: 'EMPTY' | 'UPLOADING' | 'PROCESSING' | 'READY' | 'FAILED'; asset_id?: string; url?: string; upload_token?: string }>
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
  const response = await fetch(`${getApiBasePath()}/repeat/${action}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify({ ...payload, init_data: initData, start_param_fallback: getStartParamFallback() }),
  })
  const result = await response.json()
  if (!response.ok || result.ok === false) throw new SmartRepeatApiError(result.error || 'Не удалось подтвердить повтор.', result.code || 'REPEAT_UNAVAILABLE')
  return result as T
}
