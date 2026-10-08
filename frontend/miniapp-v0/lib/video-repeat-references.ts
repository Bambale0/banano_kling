import type { VideoRepeatReferenceSlots } from './types'

// Whitelist the small public contract. Unknown versions or malformed/stale cards
// fail closed; no source URL, filename, prompt or extra metadata enters the form.
export function normalizeVideoRepeatSlots(value: VideoRepeatReferenceSlots): VideoRepeatReferenceSlots {
  const unavailable: VideoRepeatReferenceSlots = { version: 1, available: false, images: [], videos: [] }
  if (!value || value.version !== 1 || value.available !== true) return unavailable
  const valid = (slots: VideoRepeatReferenceSlots['images'], roles: string[]) => Array.isArray(slots)
    && slots.every((slot) => slot && Number.isInteger(slot.index) && slot.index >= 0
      && roles.includes(slot.role) && ['fixed', 'upload'].includes(slot.binding))
    && new Set(slots.map((slot) => slot.index)).size === slots.length
  if (!valid(value.images, ['reference', 'first_frame', 'last_frame']) || !valid(value.videos, ['reference'])) return unavailable
  const clean = <T extends VideoRepeatReferenceSlots['images'][number]>(slots: T[]) => slots
    .map(({ index, role, binding }) => ({ index, role, binding }) as T)
    .sort((left, right) => left.index - right.index)
  return { version: 1, available: true, images: clean(value.images), videos: clean(value.videos) }
}
