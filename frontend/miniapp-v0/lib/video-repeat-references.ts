import type { VideoRepeatReferenceSlots } from './types'

// Whitelist the small public contract. Unknown versions or malformed/stale cards
// fail closed; no source URL, filename, prompt or extra metadata enters the form.
export function normalizeVideoRepeatSlots(value: VideoRepeatReferenceSlots): VideoRepeatReferenceSlots {
  const unavailable: VideoRepeatReferenceSlots = { version: 1, available: false, images: [], videos: [] }
  if (!value || value.version !== 1 || value.available !== true) return unavailable
  if (typeof value.cost_multiplier !== 'number' || !Number.isFinite(value.cost_multiplier) || value.cost_multiplier <= 0) return unavailable
  let durationCosts: Record<string, number> | undefined
  if (value.duration_costs !== undefined) {
    if (!value.duration_costs || typeof value.duration_costs !== 'object' || Array.isArray(value.duration_costs)) return unavailable
    const entries = Object.entries(value.duration_costs)
    if (!entries.length || entries.some(([duration, cost]) => !/^(?:-1|[1-9]\d*)$/.test(duration)
      || typeof cost !== 'number' || !Number.isFinite(cost) || cost <= 0)) return unavailable
    durationCosts = Object.fromEntries(entries)
  }
  if (value.pricing_quality !== undefined && !['480p', '720p'].includes(value.pricing_quality)) return unavailable
  const valid = (slots: VideoRepeatReferenceSlots['images'], roles: string[]) => Array.isArray(slots)
    && slots.every((slot) => slot && Number.isInteger(slot.index) && slot.index >= 0
      && roles.includes(slot.role) && ['fixed', 'upload'].includes(slot.binding))
    && new Set(slots.map((slot) => slot.index)).size === slots.length
  if (!valid(value.images, ['reference', 'first_frame', 'last_frame']) || !valid(value.videos, ['reference'])) return unavailable
  const clean = <T extends VideoRepeatReferenceSlots['images'][number]>(slots: T[]) => slots
    .map(({ index, role, binding }) => ({ index, role, binding }) as T)
    .sort((left, right) => left.index - right.index)
  return { version: 1, available: true, cost_multiplier: value.cost_multiplier,
    ...(durationCosts ? { duration_costs: durationCosts } : {}),
    ...(value.pricing_quality ? { pricing_quality: value.pricing_quality } : {}),
    images: clean(value.images), videos: clean(value.videos) }
}
