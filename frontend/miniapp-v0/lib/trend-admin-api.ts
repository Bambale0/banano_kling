'use client'

import type { PromptItem } from './types'
import { getApiBasePath, getInitData, getStartParamFallback } from './api'

export type TrendPreviewKind = 'image' | 'video'

export async function updateTrendPreview(
  promptId: number,
  previewUrl: string,
  previewKind: TrendPreviewKind,
): Promise<PromptItem> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }

  const response = await fetch(`${getApiBasePath()}/admin/trends/preview`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    credentials: 'same-origin',
    cache: 'no-store',
    body: JSON.stringify({
      init_data: initData,
      start_param_fallback: getStartParamFallback(),
      prompt_id: promptId,
      preview_url: previewUrl,
      preview_kind: previewKind,
    }),
  })

  let payload: { ok?: boolean; error?: string; prompt?: PromptItem }
  try {
    payload = await response.json()
  } catch {
    throw new Error('Сервер вернул некорректный ответ при обновлении превью')
  }

  if (!response.ok || payload.ok === false || !payload.prompt) {
    throw new Error(payload.error || 'Не удалось обновить превью тренда')
  }
  return payload.prompt
}

export interface TrendContent {
  id: number
  title: string
  prompt_text: string
  prompt_editable: boolean
  revision: string
}

export async function trendContent(
  promptId: number,
  update?: Pick<TrendContent, 'title' | 'revision'> & { prompt_text?: string },
): Promise<TrendContent> {
  const initData = getInitData()
  if (!initData) throw new Error('Откройте Mini App из Telegram')
  const response = await fetch(`${getApiBasePath()}/admin/trends/content`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin', cache: 'no-store',
    body: JSON.stringify({ init_data: initData, start_param_fallback: getStartParamFallback(),
      prompt_id: promptId, op: update ? 'update' : 'get', ...update }),
  })
  const payload = await response.json()
  if (!response.ok || payload.ok !== true || !payload.content) {
    throw new Error(payload.error || 'Не удалось загрузить или сохранить тренд')
  }
  return payload.content
}
