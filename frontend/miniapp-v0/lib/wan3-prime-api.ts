'use client'

import { getApiBasePath, getInitData, getStartParamFallback } from './api'
import type { UploadedFile } from './types'

export type Wan3PrimeScenario = 'text' | 'first_frame' | 'first_last' | 'reference' | 'edit' | 'file' | 'link'
export type Wan3PrimeResolution = '480P' | '720P' | '1080P'
export type Wan3PrimeAspectRatio = 'adaptive' | '16:9' | '4:3' | '1:1' | '3:4' | '9:16'

export const WAN3_PRIME_MAX_IMAGE_BYTES = 20 * 1024 * 1024
export const WAN3_PRIME_MAX_VIDEO_BYTES = 100 * 1024 * 1024
export const WAN3_PRIME_MAX_AUDIO_BYTES = 15 * 1024 * 1024
export const WAN3_PRIME_MAX_FILE_BYTES = 100 * 1024 * 1024
const WAN3_PRIME_CHUNK_BYTES = 7 * 1024 * 1024

export interface Wan3PrimeRecipe {
  model: 'wan_3_prime'
  source_feed_gen_id?: number | null
  trend_id?: number | null
  repeat_plan_hash?: string
  repeat_replacements?: Record<string, string>
  scenario: Wan3PrimeScenario
  prompt: string
  resolution: Wan3PrimeResolution
  aspect_ratio: Wan3PrimeAspectRatio
  duration: -1 | number
  audio: boolean
  nsfw_checker: boolean
  seed?: number | null
  first_frame_url?: string | null
  last_frame_url?: string | null
  reference_image_urls?: string[]
  reference_video_urls?: string[]
  reference_audio_urls?: string[]
  reference_file_urls?: string[]
  reference_link_urls?: string[]
}

export interface Wan3PrimeQuoteRequest {
  recipe: Wan3PrimeRecipe
  client_request_id: string
}

export interface Wan3PrimeQuoteResponse {
  ok: true
  quote_hash: string
  reserve_cost: number
  estimated_final_cost?: number | null
  billing_duration_seconds: number
  source_video_duration_seconds: number
  tariff_missing: boolean
  admin_free: boolean
  auto_duration: boolean
  settlement_notice?: string | null
}

export interface Wan3PrimeGenerateRequest extends Wan3PrimeQuoteRequest {
  quote_hash: string
  idempotency_key: string
}

export interface Wan3PrimeGenerateResponse {
  ok: true
  status: 'queued' | 'accepted' | 'unknown' | 'done' | 'failed'
  charged_cost?: number
  refunded_cost?: number
  internal_task_id: string
  provider_task_id?: string | null
  credits?: number | null
  reserve_cost: number
}

export type Wan3PrimeUploadKind = 'image' | 'video' | 'audio' | 'file'

export interface Wan3PrimeUploadInitResponse {
  ok: true
  upload_id: string
  chunk_size: number
  expires_at?: string | null
}

export interface Wan3PrimeUploadCompleteResponse {
  ok: true
  url: string
  kind: Wan3PrimeUploadKind
  filename: string
  size: number
  reference?: {
    id?: string | number | null
    created_at?: string | null
    source?: string | null
  } | null
}

export interface Wan3PrimeImportResponse {
  ok: true
  url: string
  kind: Wan3PrimeUploadKind | 'link'
  filename?: string | null
  size?: number | null
}

export interface Wan3PrimeOwnerRecipeResponse {
  ok: true
  recipe: Wan3PrimeRecipe
  private_media_redacted?: boolean
}

export class Wan3PrimeApiError extends Error {
  constructor(message: string, public code: string, public status: number) {
    super(message)
    this.name = 'Wan3PrimeApiError'
  }
}

async function parseWan3Json<T>(response: Response, fallback: string): Promise<T> {
  const text = await response.text()
  let data: any
  try {
    data = JSON.parse(text)
  } catch {
    throw new Error(fallback)
  }
  if (!response.ok || data?.ok === false) {
    throw new Wan3PrimeApiError(data?.error || fallback, String(data?.code || ''), response.status)
  }
  return data as T
}

async function wan3PostJson<T>(path: string, payload: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  const initData = getInitData()
  if (!initData) throw new Error('Откройте Mini App из Telegram и попробуйте снова.')
  const response = await fetch(`${getApiBasePath()}/wan3/${path.replace(/^\/+/, '')}`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-Telegram-Init-Data': initData,
    },
    body: JSON.stringify({
      init_data: initData,
      start_param_fallback: getStartParamFallback(),
      ...payload,
    }),
    cache: 'no-store',
    credentials: 'same-origin',
    signal,
  })
  return parseWan3Json<T>(response, 'Wan 3.0: не удалось выполнить запрос.')
}

// POST /mini-app/api/wan3/quote
// Body: { init_data, start_param_fallback, client_request_id, recipe }
// Response: Wan3PrimeQuoteResponse. Server is authoritative for owned media,
// source durations, quote_hash, tariff availability, reserve and settlement text.
export function quoteWan3Prime(request: Wan3PrimeQuoteRequest, signal?: AbortSignal) {
  return wan3PostJson<Wan3PrimeQuoteResponse>('quote', request as unknown as Record<string, unknown>, signal)
}

// POST /mini-app/api/wan3/generate
// Body: { init_data, start_param_fallback, client_request_id, idempotency_key, quote_hash, recipe }
// Response: Wan3PrimeGenerateResponse. Duplicate idempotency_key must return the
// existing intent/task and must not create a second provider task.
export function generateWan3Prime(request: Wan3PrimeGenerateRequest, signal?: AbortSignal) {
  return wan3PostJson<Wan3PrimeGenerateResponse>('generate', request as unknown as Record<string, unknown>, signal)
}

// POST /mini-app/api/wan3/import
// Body: { init_data, start_param_fallback, kind, url }. Backend performs SSRF-safe,
// bounded import and returns an owned URL for media/file, or validates public link.
export function importWan3PrimeReference(kind: Wan3PrimeUploadKind | 'link', url: string, signal?: AbortSignal) {
  return wan3PostJson<Wan3PrimeImportResponse>('import', { kind, url }, signal)
}

// POST /mini-app/api/wan3/recipe
// Body: { init_data, start_param_fallback, task_id }. Owner-only; public repeats
// must redact private media and hidden prompts.
export function fetchWan3PrimeOwnerRecipe(taskId: string, signal?: AbortSignal) {
  return wan3PostJson<Wan3PrimeOwnerRecipeResponse>('recipe', { task_id: taskId }, signal)
}

function maxBytesForKind(kind: Wan3PrimeUploadKind): number {
  if (kind === 'image') return WAN3_PRIME_MAX_IMAGE_BYTES
  if (kind === 'video') return WAN3_PRIME_MAX_VIDEO_BYTES
  if (kind === 'audio') return WAN3_PRIME_MAX_AUDIO_BYTES
  return WAN3_PRIME_MAX_FILE_BYTES
}

function uploadedFileFromWan3(file: File, data: Wan3PrimeUploadCompleteResponse): UploadedFile {
  return {
    id: data.reference?.id ? String(data.reference.id) : `wan3_${Date.now()}_${Math.random().toString(36).slice(2)}`,
    name: data.filename || file.name,
    url: data.url,
    type: data.kind === 'file' ? 'image' : data.kind,
    size: data.size || file.size,
    saved_reference_id: data.reference?.id ? String(data.reference.id) : null,
    created_at: data.reference?.created_at || null,
    source: data.reference?.source || 'miniapp_wan3_prime',
  }
}

// Chunked upload contract:
// 1. POST /wan3/upload/init { kind, filename, size, content_type }
// 2. POST /wan3/upload/chunk multipart { upload_id, index, total, chunk }
// 3. POST /wan3/upload/complete { upload_id }
// Parent lifecycle wires these routes to owned media validation/storage.
export async function uploadWan3PrimeReference(kind: Wan3PrimeUploadKind, file: File): Promise<UploadedFile> {
  if (file.size <= 0) throw new Error('Файл пустой.')
  const maxBytes = maxBytesForKind(kind)
  if (file.size > maxBytes) throw new Error(`Wan 3.0 принимает этот тип файла до ${Math.round(maxBytes / 1024 / 1024)} MB.`)
  const initData = getInitData()
  if (!initData) throw new Error('Откройте Mini App из Telegram и попробуйте снова.')

  const contentType = file.type || 'application/octet-stream'
  const init = await wan3PostJson<Wan3PrimeUploadInitResponse>('upload/init', {
    kind,
    filename: file.name,
    size: file.size,
    content_type: contentType,
  })
  const chunkSize = Number.isFinite(init.chunk_size) && init.chunk_size > 0 ? init.chunk_size : WAN3_PRIME_CHUNK_BYTES
  const total = Math.ceil(file.size / chunkSize)

  for (let index = 0; index < total; index += 1) {
    const form = new FormData()
    form.append('init_data', initData)
    form.append('start_param_fallback', getStartParamFallback())
    form.append('upload_id', init.upload_id)
    form.append('index', String(index))
    form.append('total', String(total))
    form.append('chunk', file.slice(index * chunkSize, Math.min(file.size, (index + 1) * chunkSize), contentType), file.name)
    const response = await fetch(`${getApiBasePath()}/wan3/upload/chunk`, {
      method: 'POST',
      headers: { Accept: 'application/json', 'X-Telegram-Init-Data': initData },
      body: form,
      cache: 'no-store',
      credentials: 'same-origin',
    })
    await parseWan3Json<{ ok: true }>(response, 'Wan 3.0: не удалось загрузить часть файла.')
  }

  const completed = await wan3PostJson<Wan3PrimeUploadCompleteResponse>('upload/complete', {
    upload_id: init.upload_id,
  })
  return uploadedFileFromWan3(file, completed)
}

export interface Wan3PrimeRepeatSlot {
  key: string
  kind: Wan3PrimeUploadKind | 'link'
  role: 'first_frame' | 'last_frame' | 'source_video' | 'reference'
  index: number
  binding: 'fixed' | 'upload'
}
export interface Wan3PrimeRepeatPlan {
  ok: true
  source_feed_gen_id?: number
  trend_id?: number
  repeat_plan_hash: string
  recipe: Wan3PrimeRecipe
  slots: Wan3PrimeRepeatSlot[]
}
export async function fetchWan3PrimeRepeatPlan(sourceId: number, signal?: AbortSignal): Promise<Wan3PrimeRepeatPlan> {
  return wan3PostJson('repeat-plan', { source_feed_gen_id: sourceId }, signal)
}

export async function fetchWan3PrimeTrendPlan(trendId: number, signal?: AbortSignal): Promise<Wan3PrimeRepeatPlan> {
  return wan3PostJson('repeat-plan', { trend_id: trendId }, signal)
}
export async function fetchWan3PrimeTrendRecipe(taskId: string): Promise<{ ok: true; recipe: Wan3PrimeRecipe; slots: Array<Wan3PrimeRepeatSlot & { url: string }> }> {
  return wan3PostJson('trends/recipe', { task_id: taskId })
}
export async function publishWan3PrimeTrend(payload: { task_id: string; title: string; description: string; replacement_keys: string[] }): Promise<{ ok: true; trend_id: number; replayed: boolean }> {
  return wan3PostJson('trends/publish', payload)
}
