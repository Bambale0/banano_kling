import { parseMiniAppStartParam, startParamFromLocation } from '../lib/start-params'
import type { PromptItem } from '../lib/types'
import { isVideoTrendItem } from '../lib/trend-settings'

const publicVideoTrend = {
  id: 1126,
  title: 'Закрытый тренд',
  description: 'Публичное описание',
  prompt_text: '',
  category: 'video',
  tags: ['trend', 'trend-video'],
  uses_count: 0,
  likes: 0,
  model: null,
  generation_settings: { kind: 'video', ratio: '9:16' },
  author_id: 1,
  status: 'approved',
} as unknown as PromptItem

describe('shared trend deeplink privacy', () => {
  it('does not classify a redacted shared trend as a generic video repeat', () => {
    expect(isVideoTrendItem(publicVideoTrend, [])).toBe(false)
  })

  it('keeps full admin trend settings classifiable as video', () => {
    const adminTrend = {
      ...publicVideoTrend,
      prompt_text: 'private template prompt',
      model: 'seedance_2',
      generation_settings: {
        kind: 'video',
        user_input: 'photo',
        model: 'seedance_2',
        ratio: '9:16',
      },
    } as PromptItem

    expect(isVideoTrendItem(adminTrend, [])).toBe(true)
  })
})


describe('trend referral navigation', () => {
  it('opens the same template for legacy and personalized links', () => {
    expect(parseMiniAppStartParam('prompt_42')).toEqual({
      kind: 'prompt', promptId: 42, referralCodeForAttribution: '',
    })
    expect(parseMiniAppStartParam('prompt_42_ref_PARTNER')).toEqual({
      kind: 'prompt', promptId: 42, referralCodeForAttribution: 'PARTNER',
    })
  })
})


describe('VK public trend link navigation', () => {
  it('preserves the prompt ID and referral attribution beside signed VK launch params', () => {
    const search = '?vk_app_id=123&vk_user_id=2001&vk_ts=1000&sign=signed'
    const target = startParamFromLocation(search, '#prompt_42_ref_PARTNER')
    expect(target).toBe('prompt_42_ref_PARTNER')
    expect(parseMiniAppStartParam(target)).toEqual({
      kind: 'prompt', promptId: 42, referralCodeForAttribution: 'PARTNER',
    })
  })

  it('rejects malformed links and never treats VK actor IDs as a trend target', () => {
    expect(startParamFromLocation('?vk_app_id=123&vk_user_id=2001&sign=signed', '')).toBe('')
    expect(startParamFromLocation('?vk_app_id=123&vk_user_id=2001&sign=signed', '#prompt_-5')).toBe('')
    expect(startParamFromLocation('?vk_app_id=123&vk_user_id=2001&sign=signed', '#prompt_not-a-number')).toBe('')
  })
})
