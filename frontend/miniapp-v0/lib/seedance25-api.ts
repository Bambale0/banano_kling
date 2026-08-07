'use client'

import { getApiBasePath, getInitData, getStartParamFallback } from './api'

export type Seedance25Scenario = 'text' | 'first_frame' | 'first_last' | 'multimodal'
export type Seedance25Resolution = '480p' | '720p'
export type Seedance25OutputFormat = 'mp4' | 'mov'

export interface Seedance25GeneratePayload {
  scenario: Seedance25Scenario
  prompt: string
  ratio: 'adaptive' | '16:9' | '9:16' | '1:1' | '4:3' | '3:4' | '21:9'
  duration: number
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
  status: 'queued'
  task_id: string
  credits: number
  cost: number
  model_label: string
  admin_free: true
  resolution: Seedance25Resolution
  duration: number
  aspect_ratio: string
  scenario: Seedance25Scenario
}

export async function generateSeedance25(
  payload: Seedance25GeneratePayload,
): Promise<Seedance25GenerateResponse> {
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
      prompt: payload.prompt,
      v_ratio: payload.ratio,
      v_duration: payload.duration,
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

  const text = await response.text()
  let data: any = null
  try {
    data = JSON.parse(text)
  } catch {
    throw new Error('Seedance 2.5 API вернул некорректный ответ.')
  }
  if (!response.ok || data?.ok === false) {
    throw new Error(data?.error || 'Не удалось запустить Seedance 2.5')
  }
  return data as Seedance25GenerateResponse
}
