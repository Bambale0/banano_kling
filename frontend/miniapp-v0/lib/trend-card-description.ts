import type { PromptItem } from './types'

/** Remove only the exact historical system prefix; keep the author's description. */
export function trendCardDescription(trend: Pick<PromptItem, 'description' | 'successful_runs_count'>): string {
  const description = (trend.description || '').trim()
  if (!Number.isSafeInteger(trend.successful_runs_count) || (trend.successful_runs_count ?? -1) < 0) return description
  const prefix = `✅ Успешных запусков: ${trend.successful_runs_count}`
  if (description === prefix) return ''
  return description.startsWith(prefix + ' · ') ? description.slice(prefix.length + 3) : description
}
