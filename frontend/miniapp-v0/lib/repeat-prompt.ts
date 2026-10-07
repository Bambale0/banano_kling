import type { VideoPromptPreset } from './types'

type PromptPolicy = { prompt_hidden?: boolean; prompt_actions_allowed?: boolean }

// Source DTOs may be stale or internally inconsistent. Never let a privacy
// denial lose to nonempty text while passing a repeat between UI surfaces.
export function normalizeRepeatPrompt(
  preset: VideoPromptPreset,
  policy?: PromptPolicy,
): VideoPromptPreset {
  const hidden = preset.promptHidden === true
    || policy?.prompt_hidden === true || policy?.prompt_actions_allowed === false
  if (!hidden || (preset.promptHidden === true && preset.prompt === '')) return preset
  return { ...preset, prompt: '', promptHidden: true }
}
