import type { PromptItem } from './types'

export const PINTEREST_REPEAT_TREND_ID = 900_000_001

export const PINTEREST_REPEAT_TREND: PromptItem = {
  id: PINTEREST_REPEAT_TREND_ID,
  title: 'Повтори фото с Pinterest',
  description:
    'Фото 1 задаёт композицию, позу, ракурс, одежду, фон и свет. Фото 2 задаёт ваше лицо и идентичность.',
  prompt_text: '',
  category: 'photo',
  tags: ['trend', 'builtin-trend', 'pinterest-repeat'],
  uses_count: 0,
  likes: 0,
  preview_url: null,
  model: null,
  generation_settings: {
    kind: 'image',
    user_input: 'photo',
    model: '',
    ratio: 'auto',
    required_reference_count: 2,
    reference_hint:
      'Фото 1 — референс Pinterest: композиция, поза, ракурс, одежда, фон и свет. Фото 2 — ваше фото: лицо и идентичность.',
  },
  author_id: 0,
  status: 'approved',
}

export function isBuiltinTrend(trend: PromptItem | null | undefined): boolean {
  return trend?.id === PINTEREST_REPEAT_TREND_ID
}

export function withBuiltinTrends(trends: PromptItem[]): PromptItem[] {
  const hasPinterestTrend = trends.some(
    (trend) =>
      trend.id === PINTEREST_REPEAT_TREND_ID ||
      (trend.tags || []).some((tag) => String(tag).trim().toLowerCase() === 'pinterest-repeat'),
  )
  return hasPinterestTrend ? trends : [PINTEREST_REPEAT_TREND, ...trends]
}
