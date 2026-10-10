'use client'

import { getApiBasePath, getInitData, getStartParamFallback, uploadFile } from './api'
import type { UploadedFile } from './types'

export type Seedance25Scenario = 'text' | 'first_frame' | 'first_last' | 'multimodal'
export type Seedance25Resolution = '480p' | '720p'
export type Seedance25OutputFormat = 'mp4' | 'mov'

// KIE technical contract; keep aligned with Seedance25Service.MAX_PROMPT_LENGTH.
export const SEEDANCE25_MAX_PROMPT_LENGTH = 30_000
// Direct edit uses the currently published KIE limit; ordinary mode is unchanged.
export const SEEDANCE25_IDENTITY_MAX_PROMPT_LENGTH = 20_480

const DIRECT_VIDEO_UPLOAD_BYTES = 45 * 1024 * 1024
const VIDEO_CHUNK_BYTES = 7 * 1024 * 1024
const MAX_VIDEO_BYTES = 200 * 1024 * 1024

export interface Seedance25GeneratePayload {
  scenario: Seedance25Scenario
  prompt: string
  ratio: 'adaptive' | '16:9' | '9:16' | '1:1' | '4:3' | '3:4' | '21:9'
  duration: number
  videoEditing?: boolean
  identityTransfer?: boolean
  sourceFeedGenId?: number | null
  videoQuoteId?: string
  videoQuoteHash?: string
  identityQuote?: Seedance25IdentityQuote
  resolution: Seedance25Resolution
  outputFormat: Seedance25OutputFormat
  generateAudio: boolean
  returnLastFrame: boolean
  webSearch: boolean
  nsfwChecker: boolean
  firstFrameUrl?: string | null
  lastFrameUrl?: string | null
  referenceImages?: string[]
  referenceVideos?: string[]
  referenceAudios?: string[]
}

export interface Seedance25GenerateResponse {
  ok: true
  status: 'queued' | 'done' | 'failed'
  saved_url?: string | null
  task_id: string
  credits: number
  cost: number
  model_label: string
  admin_free: boolean
  resolution: Seedance25Resolution
  duration: number
  aspect_ratio: string
  scenario: Seedance25Scenario
}

export interface Seedance25IdentityQuote {
  cost: number
  billing_duration: number
  source_video_url: string
  resolution: Seedance25Resolution
}

export interface Seedance25QuoteResponse {
  ok: true
  quote_only: true
  quote_id?: string
  quote_hash?: string
  input_seconds?: number
  selected_output_seconds?: number
  cost: number
  billing_duration: number
  source_video_duration_seconds: number
  seedance25_identity_quote: Seedance25IdentityQuote
}

interface Seedance25UploadAssemblyResponse {
  ok: true
  url: string
  kind: 'video'
  filename: string
  reference?: {
    id?: string | number | null
    created_at?: string | null
    source?: string | null
  } | null
}

export class SeedanceApiError extends Error {
  constructor(message: string, public code?: string, public status?: number) { super(message) }
}

async function parseJsonResponse<T>(response: Response, fallback: string): Promise<T> {
  const text = await response.text()
  let data: any = null
  try {
    data = JSON.parse(text)
  } catch {
    throw new Error(fallback)
  }
  if (!response.ok || data?.ok === false) {
    throw new SeedanceApiError(data?.error || fallback, data?.code, response.status)
  }
  return data as T
}

export async function uploadSeedance25Video(file: File): Promise<UploadedFile> {
  if (file.size <= 0) throw new Error('Видео пустое.')
  if (file.size > MAX_VIDEO_BYTES) throw new Error('Seedance 2.5 принимает видео до 200 MB.')

  if (file.size <= DIRECT_VIDEO_UPLOAD_BYTES) {
    return uploadFile('seedance25_video_reference' as any, file)
  }

  const initData = getInitData()
  if (!initData) throw new Error('Откройте Mini App из Telegram и попробуйте снова.')

  const contentType = file.type || (file.name.toLowerCase().endsWith('.mov') ? 'video/quicktime' : 'video/mp4')
  const chunkUrls: string[] = []
  const chunkCount = Math.ceil(file.size / VIDEO_CHUNK_BYTES)

  try {
    for (let index = 0; index < chunkCount; index += 1) {
      const start = index * VIDEO_CHUNK_BYTES
      const end = Math.min(file.size, start + VIDEO_CHUNK_BYTES)
      const blob = file.slice(start, end, contentType)
      const chunkFile = new File(
        [blob],
        `${file.name}.part-${String(index + 1).padStart(3, '0')}-of-${String(chunkCount).padStart(3, '0')}`,
        { type: contentType, lastModified: file.lastModified },
      )
      const uploaded = await uploadFile('seedance25_video_chunk' as any, chunkFile)
      chunkUrls.push(uploaded.url)
    }

    const response = await fetch(`${getApiBasePath()}/generate-video`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
      credentials: 'same-origin',
      body: JSON.stringify({
        init_data: initData,
        start_param_fallback: getStartParamFallback(),
        v_model: 'seedance_2_5',
        seedance25_upload_only: true,
        seedance25_chunk_urls: chunkUrls,
        seedance25_original_filename: file.name,
        seedance25_original_size: file.size,
      }),
    })
    const data = await parseJsonResponse<Seedance25UploadAssemblyResponse>(
      response,
      'Не удалось собрать большое видео Seedance 2.5.',
    )
    return {
      id: data.reference?.id ? String(data.reference.id) : `seedance25_${Date.now()}_${Math.random().toString(36).slice(2)}`,
      name: data.filename,
      url: data.url,
      type: 'video',
      size: file.size,
      saved_reference_id: data.reference?.id ? String(data.reference.id) : null,
      created_at: data.reference?.created_at || null,
      source: data.reference?.source || 'miniapp_seedance25',
    }
  } catch (error) {
    // The backend removes all uploaded chunks once it receives the assembly
    // manifest. If a network failure happens before that point, generic upload
    // cleanup will remove temporary chunk files later.
    throw error
  }
}

async function requestSeedance25<T>(
  payload: Seedance25GeneratePayload,
  quoteOnly = false,
): Promise<T> {
  if (payload.identityTransfer && Array.from(payload.prompt.trim()).length > SEEDANCE25_IDENTITY_MAX_PROMPT_LENGTH) {
    throw new Error(`Прямая замена — максимум ${SEEDANCE25_IDENTITY_MAX_PROMPT_LENGTH} символов`)
  }
  const initData = getInitData()
  if (!initData) throw new Error('Откройте Mini App из Telegram и попробуйте снова.')

  const response = await fetch(`${getApiBasePath()}/generate-video`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    cache: 'no-store',
    credentials: 'same-origin',
    body: JSON.stringify({
      init_data: initData,
      start_param_fallback: getStartParamFallback(),
      v_model: 'seedance_2_5',
      v_type:
        payload.scenario === 'text'
          ? 'text'
          : payload.scenario === 'multimodal'
            ? 'video'
            : 'imgtxt',
      seedance25_scenario: payload.scenario,
      ...(payload.sourceFeedGenId ? { source_feed_gen_id: payload.sourceFeedGenId } : {}),
      ...(quoteOnly ? { seedance25_quote_only: true } : {}),
      seedance25_identity_transfer: payload.identityTransfer === true,
      ...(payload.videoQuoteId ? { video_quote_id: payload.videoQuoteId } : {}),
      ...(payload.videoQuoteHash ? { video_quote_hash: payload.videoQuoteHash } : {}),
      ...(payload.identityQuote ? { seedance25_identity_quote: payload.identityQuote } : {}),
      prompt: payload.prompt,
      v_ratio: payload.videoEditing || payload.identityTransfer ? 'adaptive' : payload.ratio,
      v_duration: payload.videoEditing || payload.identityTransfer ? -1 : payload.duration,
      seedance25_video_editing: payload.videoEditing === true,
      seedance25_resolution: payload.resolution,
      seedance25_output_format: payload.outputFormat,
      seedance25_generate_audio: payload.generateAudio,
      seedance25_return_last_frame: payload.returnLastFrame,
      seedance25_web_search: payload.webSearch,
      seedance25_nsfw_checker: payload.nsfwChecker,
      seedance25_first_frame_url: payload.firstFrameUrl || null,
      seedance25_last_frame_url: payload.lastFrameUrl || null,
      reference_images: payload.referenceImages || [],
      v_reference_videos: payload.referenceVideos || [],
      seedance25_reference_audio_urls: payload.referenceAudios || [],
    }),
  })

  return parseJsonResponse<T>(
    response,
    'Seedance 2.5 API вернул некорректный ответ.',
  )
}

export async function generateSeedance25(payload: Seedance25GeneratePayload): Promise<Seedance25GenerateResponse> {
  return requestSeedance25<Seedance25GenerateResponse>(payload)
}

export async function quoteSeedance25Identity(payload: Seedance25GeneratePayload): Promise<Seedance25QuoteResponse> {
  return requestSeedance25<Seedance25QuoteResponse>(payload, true)
}


export async function seedance25QuoteStatus(quoteId: string): Promise<Seedance25GenerateResponse | { ok: true; status: string; quote_id: string }> {
  const response = await fetch(`${getApiBasePath()}/generate-video`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ init_data: getInitData(), start_param_fallback: getStartParamFallback(),
      v_model: 'seedance_2_5', seedance25_status_only: true, video_quote_id: quoteId }),
  })
  return parseJsonResponse(response, 'Не удалось проверить запуск Seedance')
}
