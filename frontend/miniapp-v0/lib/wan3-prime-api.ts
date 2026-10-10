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
// Match the existing Mini App media budget, per request rather than per file.
// A large file may need many chunks; completed chunks must not exhaust its next request.
export const WAN3_PRIME_MEDIA_TIMEOUT_MS = 900_000

async function mediaRequest<T>(request: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController()
  const abort = () => controller.abort()
  let timedOut = false
  const timeout = setTimeout(() => { timedOut = true; controller.abort() }, WAN3_PRIME_MEDIA_TIMEOUT_MS)
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) controller.abort()
  let rejectOnAbort: (() => void) | undefined
  try {
    if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError')
    const aborted = new Promise<never>((_, reject) => {
      rejectOnAbort = () => reject(new DOMException('Aborted', 'AbortError'))
      controller.signal.addEventListener('abort', rejectOnAbort, { once: true })
    })
    return await Promise.race([request(controller.signal), aborted])
  } catch (error) {
    if (timedOut) throw new Error('Сервер не ответил за 15 минут. Проверьте сеть и повторите загрузку.')
    throw error
  } finally {
    clearTimeout(timeout)
    signal?.removeEventListener('abort', abort)
    if (rejectOnAbort) controller.signal.removeEventListener('abort', rejectOnAbort)
  }
}

export interface Wan3PrimeRecipe {
  model: 'wan_3_prime' | 'wan_3'
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
  model?: 'wan_3_prime' | 'wan_3'
  provider_model?: string
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

async function wan3PostJson<T>(path: string, payload: Record<string, unknown>, signal?: AbortSignal, signedInitData?: string): Promise<T> {
  const initData = signedInitData || getInitData()
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
  return mediaRequest(activeSignal => wan3PostJson<Wan3PrimeImportResponse>('import', { kind, url }, activeSignal), signal)
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

interface PendingWanUpload {
  upload_id: string
  kind: Wan3PrimeUploadKind
  filename: string
  size: number
  content_type: string
  phase: 'initializing' | 'known'
}
interface UploadScope { key: string; storageKey?: string }
const pendingUploads = new Map<string, PendingWanUpload>()
const activeUploads = new Set<string>()

export class Wan3PrimeUploadCleanupError extends Error {
  constructor() {
    super('Не удалось подтвердить отмену предыдущей загрузки. Повтор сначала проверит и освободит её; новая загрузка пока не создаётся.')
    this.name = 'Wan3PrimeUploadCleanupError'
  }
}

function uploadScope(initData: string): UploadScope {
  try {
    const user = JSON.parse(new URLSearchParams(initData).get('user') || 'null')
    if (Number.isSafeInteger(user?.id) && user.id > 0) {
      return { key: `owner:${user.id}`, storageKey: `__wan3_pending_upload_${user.id}` }
    }
  } catch { /* Non-Telegram test/auth payloads stay memory-only. */ }
  return { key: initData }
}

function rememberUpload(scope: UploadScope, pending: PendingWanUpload | null) {
  if (pending) pendingUploads.set(scope.key, pending)
  else pendingUploads.delete(scope.key)
  if (!scope.storageKey) return
  try {
    if (pending) sessionStorage.setItem(scope.storageKey, JSON.stringify(pending))
    else sessionStorage.removeItem(scope.storageKey)
  } catch { /* Storage can be unavailable; the in-memory fence remains active. */ }
}

function previousUpload(scope: UploadScope): PendingWanUpload | undefined {
  const existing = pendingUploads.get(scope.key)
  if (existing || !scope.storageKey) return existing
  try {
    const saved = JSON.parse(sessionStorage.getItem(scope.storageKey) || 'null')
    if (saved && /^[a-f0-9]{32}$/.test(saved.upload_id) && ['image', 'video', 'audio', 'file'].includes(saved.kind)
      && typeof saved.filename === 'string' && typeof saved.content_type === 'string'
      && Number.isSafeInteger(saved.size) && saved.size > 0 && ['initializing', 'known'].includes(saved.phase)) {
      pendingUploads.set(scope.key, saved)
      return saved
    }
  } catch { /* No usable persisted reservation. */ }
}

function initializeUpload(pending: PendingWanUpload, initData: string) {
  const { phase: _phase, ...payload } = pending
  // Do not bind init to the UI abort signal: capture its reservation before cancelling.
  // The per-request deadline still bounds a lost response. The chosen ID is durable.
  return mediaRequest(signal => wan3PostJson<Wan3PrimeUploadInitResponse>('upload/init', payload, signal, initData))
}

function uploadConflict(error: unknown): boolean {
  return error instanceof Wan3PrimeApiError && error.status === 409 && error.code === 'upload_session_conflict'
}

function rejectedBeforeReservation(error: unknown): boolean {
  // These exact backend validations run before reservation creation. Only a fresh
  // first attempt may be cleared here; never clear a previously uncertain init.
  return error instanceof Wan3PrimeApiError && error.status === 400 && error.code === 'validation_error'
    && ['Unsupported upload kind', 'Upload size is not allowed', 'Upload extension is not allowed', 'Invalid upload ID'].includes(error.message)
}

async function releaseUpload(scope: UploadScope, pending: PendingWanUpload, initData: string) {
  try {
    if (pending.phase === 'initializing') {
      try {
        const initialized = await initializeUpload(pending, initData)
        if (initialized.upload_id !== pending.upload_id) throw new Error('Unexpected upload session')
      } catch (error) {
        // Existing-key conflicts are a durable fence against delayed init creation.
        if (!uploadConflict(error)) throw error
      }
      pending.phase = 'known'; rememberUpload(scope, pending)
    }
    const cancelled = await mediaRequest(signal => wan3PostJson<{ ok: true; status: 'cancelled' | 'completed' | 'not_found' }>(
      'upload/cancel', { upload_id: pending.upload_id }, signal, initData,
    ))
    if (!['cancelled', 'completed', 'not_found'].includes(cancelled.status)) throw new Error('Unconfirmed upload cancellation')
    rememberUpload(scope, null)
  } catch { throw new Wan3PrimeUploadCleanupError() }
}

// Chunked upload contract:
// 1. POST /wan3/upload/init { upload_id, kind, filename, size, content_type }
// 2. POST /wan3/upload/chunk multipart { upload_id, index, total, chunk }
// 3. POST /wan3/upload/complete { upload_id }
// 4. On interrupted work: reconcile uncertain init with the same ID, then
//    POST /wan3/upload/cancel { upload_id }. Never remove completed media.
// Parent lifecycle wires these routes to owned media validation/storage.
export async function uploadWan3PrimeReference(kind: Wan3PrimeUploadKind, file: File, signal?: AbortSignal, onProgress?: (uploadedBytes: number, totalBytes: number) => void): Promise<UploadedFile> {
  if (file.size <= 0) throw new Error('Файл пустой.')
  const maxBytes = maxBytesForKind(kind)
  if (file.size > maxBytes) throw new Error(`Wan 3.0 принимает этот тип файла до ${Math.round(maxBytes / 1024 / 1024)} MB.`)
  const initData = getInitData()
  if (!initData) throw new Error('Откройте Mini App из Telegram и попробуйте снова.')
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  const scope = uploadScope(initData)
  if (activeUploads.has(scope.key)) throw new Error('Предыдущая загрузка ещё завершается. Дождитесь подтверждения отмены.')
  activeUploads.add(scope.key)
  let pending: PendingWanUpload | undefined
  try {
    const previous = previousUpload(scope)
    if (previous) await releaseUpload(scope, previous, initData)
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    const contentType = file.type || 'application/octet-stream'
    pending = { upload_id: crypto.randomUUID().replace(/-/g, ''), kind, filename: file.name,
      size: file.size, content_type: contentType, phase: 'initializing' }
    rememberUpload(scope, pending)
    onProgress?.(0, file.size)
    const init = await initializeUpload(pending, initData)
    if (init.upload_id !== pending.upload_id) throw new Error('Сервер вернул другую сессию загрузки.')
    pending.phase = 'known'; rememberUpload(scope, pending)
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
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
      await mediaRequest(async activeSignal => {
        const response = await fetch(`${getApiBasePath()}/wan3/upload/chunk`, {
          method: 'POST',
          headers: { Accept: 'application/json', 'X-Telegram-Init-Data': initData },
          body: form,
          cache: 'no-store',
          credentials: 'same-origin',
          signal: activeSignal,
        })
        return parseWan3Json<{ ok: true }>(response, 'Wan 3.0: не удалось загрузить часть файла.')
      }, signal)
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
      onProgress?.(Math.min(file.size, (index + 1) * chunkSize), file.size)
    }

    const completed = await mediaRequest(activeSignal => wan3PostJson<Wan3PrimeUploadCompleteResponse>('upload/complete', {
      upload_id: init.upload_id,
    }, activeSignal, initData), signal)
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    rememberUpload(scope, null)
    return uploadedFileFromWan3(file, completed)
  } catch (error) {
    if (pending) {
      if (pending.phase === 'initializing' && rejectedBeforeReservation(error)) {
        rememberUpload(scope, null)
        throw error
      }
      if (pending.phase === 'initializing') throw new Wan3PrimeUploadCleanupError()
      await releaseUpload(scope, pending, initData)
    }
    throw error
  } finally { activeUploads.delete(scope.key) }
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
