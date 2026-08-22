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
