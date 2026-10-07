import { fetchTaskDetail } from './api'
import { normalizeRepeatPrompt } from './repeat-prompt'
import type { FeedItem, UploadedFile, VideoPromptPreset } from './types'

function references(value: unknown, type: 'image' | 'video'): UploadedFile[] {
  if (!Array.isArray(value)) return []
  return value.filter((url): url is string => typeof url === 'string' && !!url.trim()).map((url, index) => ({
    id: `identity-repeat-${type}-${index}`, name: `${type === 'image' ? 'Фото' : 'Видео'} ${index + 1}`,
    url, type, size: 0,
  }))
}

// Only the owner-only detail seam can reveal identity inputs. Public feed
// metadata and another person's private references must never be broadened.
export async function hydrateSeedance25IdentityPreset(
  item: FeedItem,
  preset: VideoPromptPreset,
): Promise<VideoPromptPreset> {
  const safePreset = normalizeRepeatPrompt(preset, item)
  if (item.model !== 'seedance_2_5' || item.is_mine !== true) return safePreset
  const detail = await fetchTaskDetail(item.task_id || String(item.id))
  const data = detail.request_data
  const safeDetailPreset = normalizeRepeatPrompt(safePreset, detail)
  if (data?.seedance25_identity_transfer !== true) return safeDetailPreset
  return {
    ...safeDetailPreset,
    seedance25IdentityTransfer: true,
    seedance25Resolution: data.resolution === '480p' ? '480p' : '720p',
    scenario: 'video',
    prompt: safeDetailPreset.promptHidden ? '' : detail.prompt || safeDetailPreset.prompt,
    initialStartImage: [],
    initialPhotoReferences: references(data.reference_images, 'image'),
    initialVideoReferences: references(data.v_reference_videos, 'video'),
  }
}
