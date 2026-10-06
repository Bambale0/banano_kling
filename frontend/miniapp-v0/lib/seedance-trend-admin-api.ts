'use client'

import type { PromptItem, TrendUserField } from './types'
import { getApiBasePath, getInitData, getStartParamFallback } from './api'

export interface SeedanceTrendReferenceItem {
  index: number
  preview_url: string
  default_action: 'replace_with_user' | 'keep_hidden'
}

export interface SeedanceTrendSource {
  task_id: string
  generation_id: number
  model: 'seedance_2' | 'seedance_2_5'
  duration?: number | null
  aspect_ratio?: string | null
  prompt: string
  result_url: string
  references: {
    images: SeedanceTrendReferenceItem[]
    videos: SeedanceTrendReferenceItem[]
    audios: SeedanceTrendReferenceItem[]
  }
}

function authorizedPayload(): Record<string, unknown> {
  const initData = getInitData()
  if (!initData) throw new Error('Откройте Mini App из Telegram и попробуйте снова.')
  const payload: Record<string, unknown> = { init_data: initData }
  const fallback = getStartParamFallback()
  if (fallback) payload.start_param_fallback = fallback
  return payload
}

async function postAdmin<T>(endpoint: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(`${getApiBasePath()}/${endpoint}`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    credentials: 'same-origin',
    cache: 'no-store',
    body: JSON.stringify({ ...authorizedPayload(), ...body }),
  })
  let payload: T & { ok?: boolean; error?: string }
  try {
    payload = (await response.json()) as T & { ok?: boolean; error?: string }
  } catch {
    throw new Error('Сервер вернул некорректный ответ')
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || 'Не удалось сохранить Seedance-тренд')
  }
  return payload
}

export async function fetchSeedanceTrendSource(taskId: string): Promise<SeedanceTrendSource> {
  const payload = await postAdmin<{ ok: true; source: SeedanceTrendSource }>(
    'admin/trends/seedance/source',
    { task_id: taskId },
  )
  return payload.source
}

export async function publishSeedanceTrend(payload: {
  taskId: string
  title: string
  description: string
  identityImageIndex: number
  fixedImageIndices: number[]
  fixedVideoIndices: number[]
  fixedAudioIndices: number[]
  replaceableImageIndices: number[]
  replaceableVideoIndices: number[]
  replaceableAudioIndices: number[]
}): Promise<PromptItem> {
  const response = await postAdmin<{ ok: true; prompt: PromptItem }>(
    'admin/trends/seedance/publish',
    {
      task_id: payload.taskId,
      title: payload.title,
      description: payload.description,
      identity_image_index: payload.identityImageIndex,
      fixed_image_indices: payload.fixedImageIndices,
      fixed_video_indices: payload.fixedVideoIndices,
      fixed_audio_indices: payload.fixedAudioIndices,
      replaceable_image_indices: payload.replaceableImageIndices,
      replaceable_video_indices: payload.replaceableVideoIndices,
      replaceable_audio_indices: payload.replaceableAudioIndices,
    },
  )
  return response.prompt
}


export interface SeedanceTrendUploadPayload {
  model: 'seedance_2' | 'seedance_2_5'
  title: string
  description: string
  promptText: string
  previewUrl: string
  previewType: 'image' | 'video'
  imageUrls: string[]
  videoUrls: string[]
  audioUrls: string[]
  identityImageIndex: number
  fixedImageIndices: number[]
  fixedVideoIndices: number[]
  fixedAudioIndices: number[]
  replaceableImageIndices: number[]
  replaceableVideoIndices: number[]
  replaceableAudioIndices: number[]
  duration: number
  aspectRatio: string
  userFields: TrendUserField[]
}

export async function publishSeedanceTrendUpload(payload: SeedanceTrendUploadPayload): Promise<PromptItem> {
  const response = await postAdmin<{ ok: true; prompt: PromptItem }>(
    'admin/trends/seedance/publish-upload',
    {
      model: payload.model,
      title: payload.title,
      description: payload.description,
      prompt_text: payload.promptText,
      preview_url: payload.previewUrl,
      preview_type: payload.previewType,
      image_urls: payload.imageUrls,
      video_urls: payload.videoUrls,
      audio_urls: payload.audioUrls,
      identity_image_index: payload.identityImageIndex,
      fixed_image_indices: payload.fixedImageIndices,
      fixed_video_indices: payload.fixedVideoIndices,
      fixed_audio_indices: payload.fixedAudioIndices,
      replaceable_image_indices: payload.replaceableImageIndices,
      replaceable_video_indices: payload.replaceableVideoIndices,
      replaceable_audio_indices: payload.replaceableAudioIndices,
      duration: payload.duration,
      aspect_ratio: payload.aspectRatio,
      user_fields: payload.userFields,
    },
  )
  return response.prompt
}
