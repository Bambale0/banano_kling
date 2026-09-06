'use client'

import { getApiBasePath, getInitData, getStartParamFallback } from './api'
import type { Task, TaskDetail } from './types'

interface RunTrendResponse {
  ok: true
  status: 'queued' | 'done'
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

function providerReferenceUrl(value: string): string {
  try {
    const url = new URL(value)
    if (
      url.hostname.toLowerCase() === 'cdn.chillcreative.ru' &&
      url.pathname.startsWith('/uploads/')
    ) {
      return `https://tanyapi.chillcreative.ru${url.pathname}${url.search}${url.hash}`
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
    status: data.status === 'done' ? 'completed' : 'pending',
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

export async function runTrend(
  trendId: number,
  referenceUrls: string[],
  userValues: Record<string, string> = {},
): Promise<RunTrendResult> {
  const payload = authorizedPayload()
  payload.trend_id = trendId
  payload.reference_urls = referenceUrls.map(providerReferenceUrl)
  if (Object.keys(userValues).length) payload.user_values = userValues

  const response = await fetch(`${getApiBasePath()}/trends/run`, {
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
