'use client'

import { getApiBasePath, getInitData, getStartParamFallback } from './api'
import type { Task, TaskDetail } from './types'

interface RunTrendResponse {
  ok: true
  status: 'queued' | 'done' | 'failed'
  task_id: string
  task_type: 'image' | 'video' | 'audio' | 'character'
  saved_url?: string | null
  credits: number
  cost: number
  model: string
  model_label: string
  aspect_ratio: string
  duration?: number | null
  prompt_hidden: true
  prompt_actions_allowed: false
  trend_id: number
}

interface PinterestReferenceResponse {
  ok: true
  source_url: string
  image_url: string
}

export interface RunTrendResult {
  task: Task
  detail?: TaskDetail | null
  credits: number
}

export interface PinterestRepeatOptions {
  heightCm: number
  weightKg: number
  model: 'banana_pro' | 'seedream_5_pro'
}

export interface TrendReferenceInput {
  media_type: 'image' | 'video' | 'audio'
  position: number
  url: string
}

export class TrendRunRequestError extends Error {
  readonly retrySameRequest: boolean

  constructor(message: string, retrySameRequest: boolean) {
    super(message)
    this.name = 'TrendRunRequestError'
    this.retrySameRequest = retrySameRequest
  }
}

export function createTrendRunRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `trend_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 14)}`
}

function providerReferenceUrl(value: string): string {
  try {
    const url = new URL(value)
    if (
      url.hostname.toLowerCase() === 'cdn.chillcreative.ru' &&
      url.pathname.startsWith('/uploads/') &&
      typeof window !== 'undefined'
    ) {
      return `${window.location.origin}${url.pathname}${url.search}${url.hash}`
    }
  } catch {
    return value
  }
  return value
}

async function parseJson<T>(response: Response, fallback: string): Promise<T> {
  const text = await response.text()
  let payload: T | { ok?: false; error?: string }
  try {
    payload = JSON.parse(text) as T | { ok?: false; error?: string }
  } catch {
    throw new Error('Сервер вернул некорректный ответ. Обновите Mini App.')
  }

  if (!response.ok || (payload as { ok?: boolean }).ok !== true) {
    throw new Error(
      'error' in (payload as { error?: string }) && (payload as { error?: string }).error
        ? (payload as { error?: string }).error
        : fallback,
    )
  }
  return payload as T
}

async function parseResponse(response: Response): Promise<RunTrendResponse> {
  return parseJson<RunTrendResponse>(response, 'Не удалось запустить тренд')
}

async function parseTrendResponse(response: Response): Promise<RunTrendResponse> {
  const text = await response.text()
  let payload:
    | RunTrendResponse
    | { ok?: false; error?: string; retry_same_request?: boolean }
  try {
    payload = JSON.parse(text) as
      | RunTrendResponse
      | { ok?: false; error?: string; retry_same_request?: boolean }
  } catch {
    throw new TrendRunRequestError(
      'Сервер вернул некорректный ответ. Обновите Mini App.',
      response.status >= 500,
    )
  }

  if (!response.ok || payload.ok !== true) {
    const message =
      'error' in payload && payload.error
        ? payload.error
        : 'Не удалось запустить тренд'
    const retrySameRequest =
      'retry_same_request' in payload &&
      typeof payload.retry_same_request === 'boolean'
        ? payload.retry_same_request
        : response.status === 409
    throw new TrendRunRequestError(message, retrySameRequest)
  }
  return payload
}

function authorizedPayload(): Record<string, unknown> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте Mini App из Telegram и попробуйте снова.')
  }
  const payload: Record<string, unknown> = { init_data: initData }
  const startParam = getStartParamFallback()
  if (startParam) payload.start_param_fallback = startParam
  return payload
}

function toRunResult(data: RunTrendResponse, referenceUrls: string[]): RunTrendResult {
  const task: Task = {
    task_id: data.task_id,
    type: data.task_type,
    model: data.model,
    model_label: data.model_label,
    aspect_ratio: data.aspect_ratio,
    status: data.status === 'done' ? 'completed' : data.status === 'failed' ? 'failed' : 'pending',
    result_url: data.saved_url || null,
    created_at: new Date().toISOString(),
    prompt_preview: '',
    cost: data.cost,
    duration: data.duration ?? null,
    prompt_hidden: true,
    prompt_actions_allowed: false,
  }

  return {
    task,
    detail:
      data.status === 'done'
        ? {
            ...task,
            prompt: '',
            request_data: {
              reference_images: referenceUrls.map(providerReferenceUrl),
              trend_id: data.trend_id,
            },
          }
        : null,
    credits: data.credits,
  }
}

export async function resolvePinterestReference(url: string): Promise<PinterestReferenceResponse> {
  const payload = authorizedPayload()
  payload.url = url.trim()
  const response = await fetch(`${getApiBasePath()}/trends/pinterest-reference`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    cache: 'no-store',
    credentials: 'same-origin',
  })
  return parseJson<PinterestReferenceResponse>(
    response,
    'Не удалось загрузить фото из Pinterest',
  )
}

export async function runPinterestRepeatTrend(
  trendId: number,
  referenceUrls: string[],
  options: PinterestRepeatOptions,
): Promise<RunTrendResult> {
  const payload = authorizedPayload()
  payload.trend_id = trendId
  payload.reference_urls = referenceUrls.map(providerReferenceUrl)
  payload.height_cm = options.heightCm
  payload.weight_kg = options.weightKg
  payload.model = options.model
  payload.confirmed = true

  const response = await fetch(`${getApiBasePath()}/trends/pinterest-repeat/run`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    cache: 'no-store',
    credentials: 'same-origin',
  })
  const data = await parseResponse(response)
  return toRunResult(data, referenceUrls)
}

export interface TrendQuote {
  quote_id: string; quote_hash: string; cost: number; charge_cost: number;
  input_seconds: number; selected_output_seconds: number;
}

function trendPayload(trendId: number, referenceUrls: string[], userValues: Record<string,string>,
                      clientRequestId: string, referenceInputs: TrendReferenceInput[]): Record<string,unknown> {
  const payload = authorizedPayload()
  payload.trend_id = trendId
  payload.reference_urls = referenceUrls.map(providerReferenceUrl)
  if (referenceInputs.length) payload.reference_inputs = referenceInputs.map(input => ({ ...input, url: providerReferenceUrl(input.url) }))
  payload.client_request_id = clientRequestId
  if (Object.keys(userValues).length) payload.user_values = userValues
  return payload
}

async function requestTrend(payload: Record<string,unknown>): Promise<RunTrendResponse> {
  let response: Response
  try {
    response = await fetch(`${getApiBasePath()}/trends/run`, {
      method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), cache: 'no-store', credentials: 'same-origin',
    })
  } catch (cause) {
    throw new TrendRunRequestError(cause instanceof Error ? cause.message : 'Не удалось связаться с сервером', true)
  }
  return parseTrendResponse(response)
}

export async function quoteTrend(trendId: number, refs: string[], values: Record<string,string>, inputs: TrendReferenceInput[]): Promise<TrendQuote> {
  return await requestTrend({ ...trendPayload(trendId, refs, values, createTrendRunRequestId(), inputs), video_quote_only: true }) as unknown as TrendQuote
}

function trendPendingKey(): string | null {
  try {
    const user = JSON.parse(new URLSearchParams(getInitData()).get('user') || 'null')
    return user?.id ? `trend-quote-pending:${user.id}` : null
  } catch { return null }
}

export function readPendingTrend(): { payload: Record<string, unknown>; refs: string[]; model: string; quoteId: string } | null {
  try {
    const key = trendPendingKey()
    const value = key && JSON.parse(localStorage.getItem(key) || 'null')
    return value && /^[a-f0-9]{32}$/.test(value.quoteId) && value.payload?.video_quote_id === value.quoteId ? value : null
  } catch { return null }
}

function clearPendingTrend(quoteId: string): void {
  const key = trendPendingKey()
  if (key && readPendingTrend()?.quoteId === quoteId) localStorage.removeItem(key)
}

export async function recoverPendingTrend(): Promise<RunTrendResult | null> {
  const pending = readPendingTrend()
  if (!pending) return null
  const response = await fetch(`${getApiBasePath()}/generate-video`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', cache: 'no-store',
    body: JSON.stringify({ ...authorizedPayload(), v_model: pending.model, video_quote_id: pending.quoteId,
      video_quote_status_only: true, seedance25_status_only: pending.model === 'seedance_2_5' }),
  })
  const data = await parseTrendResponse(response)
  const status = data.status as string
  if (status === 'quoted') {
    const resumed = await requestTrend({ ...pending.payload, ...authorizedPayload() })
    clearPendingTrend(pending.quoteId)
    return toRunResult(resumed, pending.refs)
  }
  if (['queued','done','failed'].includes(status)) {
    clearPendingTrend(pending.quoteId)
    return toRunResult(data, pending.refs)
  }
  if (['rejected','provider_failed'].includes(status)) clearPendingTrend(pending.quoteId)
  return null
}

export async function runTrend(
  trendId: number, referenceUrls: string[], userValues: Record<string,string> = {},
  clientRequestId: string = createTrendRunRequestId(), referenceInputs: TrendReferenceInput[] = [],
  quote?: TrendQuote, model?: string,
): Promise<RunTrendResult> {
  const payload = trendPayload(trendId, referenceUrls, userValues, clientRequestId, referenceInputs)
  if (quote) {
    const pending = readPendingTrend()
    if (pending && pending.quoteId !== quote.quote_id) throw new TrendRunRequestError('Проверяем статус предыдущего запуска', true)
    payload.video_quote_id = quote.quote_id
    payload.video_quote_hash = quote.quote_hash
    const key = trendPendingKey()
    if (!key) throw new Error('Не удалось сохранить идентификатор запуска')
    // Persist only user-submitted references; hidden provider assets never reach this record.
    const { init_data: _initData, ...savedPayload } = payload
    localStorage.setItem(key, JSON.stringify({ payload: savedPayload, refs: referenceUrls, model, quoteId: quote.quote_id }))
  }
  try {
    const data = await requestTrend(payload)
    if (quote) clearPendingTrend(quote.quote_id)
    return toRunResult(data, referenceUrls)
  } catch (error) {
    if (quote && error instanceof TrendRunRequestError && !error.retrySameRequest) clearPendingTrend(quote.quote_id)
    throw error
  }
}
