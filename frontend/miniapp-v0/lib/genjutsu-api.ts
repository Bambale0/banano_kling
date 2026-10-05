'use client'

import { getApiBasePath, getInitData, getStartParamFallback } from './api'

export type Operation = 'motion_transfer' | 'object_swap' | 'restyle'
export type Asset = { id: string; kind: 'image' | 'video' | 'audio'; url: string | null; duration_ms?: number; width?: number; height?: number; size_bytes?: number; has_audio?: boolean }
export type Reference = { asset_id: string; role: string; label: string; binding?: 'user' | 'fixed' }
export type Step = { operation: Operation; resolution: string; prompt: string; preserve: string; references: Reference[]; preset_id: string | null }
export type Plan = { source_asset_id: string; steps: Step[]; variants: number; continuation: 'automatic' | 'manual' }
export type Project = { id: string; revision: number; title: string; plan: Plan; updated_ms?: number }
export type Preset = { id: string; name: string; preview_url: string }
export type Capability = { label: string; resolutions: string[]; min_images: number; max_images: number; max_prompt_length: number; minimum_video_ms: number; maximum_video_ms: number; roles: string[] }
export type Allocation = { variant: number; ordinal: number; operation: Operation; billable_seconds: number; credits_per_second: number; reserved_credits: number; maximum_reserve: boolean }
export type Quote = { id: string; expires_ms: number; total_credits: number; allocations: Allocation[]; plan_hash: string }
export type RunStep = { id: string; variant: number; ordinal: number; status: string; spec: Partial<Step> & { operation: Operation; resolution: string }; reserved_credits: number; actual_credits: number | null; refunded_credits: number; error_code: string | null; delivery_status: string | null; delivery_error: string | null; source_asset?: Asset; output_asset?: Asset; provider_request_id?: string; provider_correlation_id?: string; attempt_id?: string }
export type Run = { id: string; owner?: number; project_id?: string; state: string; cancel_requested: number; admin_free: number; private_recipe: number; created_ms: number; credits: number; plan?: Plan; steps: RunStep[] }
export type RecipeSlot = { step_index: number; reference_index: number; role: string; label: string }
export type Recipe = { id: string; title: string; source_slot?: { kind: 'video'; label: string } | null; slots: RecipeSlot[]; user_fields: { key: string; label: string; type: 'text' | 'number' | 'date'; required?: boolean; max_length?: number }[]; steps: { operation: Operation; resolution: string }[]; variants: number; continuation: 'automatic' | 'manual'; current_cost: number | null }
export type RunSummary = Pick<Run, 'id' | 'owner' | 'project_id' | 'state' | 'created_ms'>
export type Prices = Record<Operation, Record<string, number | null>>
export type Settings = { public_enabled: boolean; admin_enabled: boolean; verified_operations: Operation[]; prices: Prices; [key: string]: unknown }
export type Bootstrap = { catalog: Record<Operation, Capability>; is_admin: boolean; configured: boolean; provider_ready: boolean; media_ready: boolean; enabled: boolean; limits: Record<string, unknown>; prices: Prices; config_version: number; credits: number; projects: Project[]; runs: RunSummary[]; assets: Asset[] }

export class GenjutsuError extends Error {
  constructor(public code: string, message: string, public status: number) { super(message) }
}

async function decode<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null)
  if (!response.ok || !body || body.ok !== true) {
    throw new GenjutsuError(body?.code || 'network_error', body?.error || 'Не удалось получить ответ. Проверьте связь и обновите состояние работы.', response.status)
  }
  return body as T
}

export async function genjutsuCall<T>(action: string, data: Record<string, unknown> = {}): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 90000)
  try {
    return await decode<T>(await fetch(`${getApiBasePath()}/genjutsu`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
      body: JSON.stringify({ ...data, action, init_data: getInitData(), start_param_fallback: getStartParamFallback() }),
    }))
  } finally { clearTimeout(timeout) }
}

export async function uploadGenjutsu(file: File, kind: Asset['kind']): Promise<Asset> {
  const form = new FormData(); form.append('file', file)
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 300000)
  try {
    const result = await decode<{ asset: Asset }>(await fetch(`${getApiBasePath()}/genjutsu/upload?kind=${kind}`, {
      method: 'POST', headers: { 'X-Telegram-Init-Data': getInitData() }, body: form, signal: controller.signal,
    }))
    return result.asset
  } finally { clearTimeout(timeout) }
}

const memoryKeys = new Map<string, string>()
export function launchKey(quoteId: string): string {
  const name = `genjutsu-launch:${quoteId}`
  let saved: string | null = memoryKeys.get(name) || null
  try { saved ||= sessionStorage.getItem(name) } catch { /* WebView may disable storage. */ }
  if (!saved) saved = crypto.randomUUID()
  memoryKeys.set(name, saved)
  try { sessionStorage.setItem(name, saved) } catch { /* The in-memory key still prevents duplicates. */ }
  return saved
}

export function openGenjutsu(options: { task_id?: string; run_id?: string; recipe_id?: string; admin?: boolean } = {}) {
  window.dispatchEvent(new CustomEvent('genjutsu:open', { detail: options }))
}

export function freshStep(): Step { return { operation: 'motion_transfer', resolution: '720p', prompt: '', preserve: '', references: [], preset_id: null } }
export function freshPlan(): Plan { return { source_asset_id: '', steps: [freshStep()], variants: 1, continuation: 'automatic' } }

export const operationLabels: Record<Operation, string> = { motion_transfer: 'Перенос движения', object_swap: 'Замена в видео', restyle: 'Стилизация' }
export const roleLabels: Record<string, string> = { character: 'Персонаж', wardrobe: 'Одежда', product: 'Товар', object: 'Предмет', location: 'Локация', style: 'Стиль' }
export const statusLabels: Record<string, string> = {
  ready: 'Готовится к отправке', submitting: 'Отправляется', submission_unknown: 'Проверяем отправку', recovery_review: 'Нужна безопасная проверка',
  queued: 'В очереди', in_progress: 'Генерация', storing: 'Сохраняем оригинал', blocked: 'Ожидает предыдущий шаг',
  awaiting_confirmation: 'Нужно подтверждение', completed: 'Готово', failed: 'Ошибка', canceled: 'Отменено',
  running: 'Выполняется', waiting: 'Ожидает подтверждения', partial: 'Выполнено частично', review: 'Нужна проверка',
  pending: 'Ожидает доставки', sending: 'Отправляется в Telegram', delivered: 'Доставлено', unavailable: 'Недоступен Telegram',
  delivery_unknown: 'Исход доставки неизвестен',
}
