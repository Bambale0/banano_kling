import '@testing-library/jest-dom'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { VideoGeneratorForm } from '@/components/forms/video-generator-form'
import type { VideoModel, VideoPromptPreset } from '@/lib/types'

jest.mock('@/lib/repeat-prompt', () => ({ normalizeRepeatPrompt: (preset: VideoPromptPreset) => ({ prompt: preset.prompt || '' }) }))
jest.mock('@/lib/video-repeat-references', () => ({ normalizeVideoRepeatSlots: (slots: unknown) => slots }))
jest.mock('@/lib/video-repeat-pending', () => ({ getPendingVideoRepeat: () => null, isVideoStatusPending: () => false, VIDEO_REPEAT_PENDING_CHANGED: 'pending-video-changed' }))
jest.mock('@/hooks/browser-storage', () => ({ getStorageItem: () => null, removeStorageItem: jest.fn() }))
jest.mock('@/components/forms/ratio-select', () => ({ RatioSelect: () => null }))
jest.mock('@/components/forms/upload-area', () => ({ UploadArea: () => null }))
jest.mock('@/components/forms/scenario-select', () => ({ ScenarioSelect: () => null }))
jest.mock('@/components/forms/duration-select', () => ({ DurationSelect: () => null }))
jest.mock('@/components/forms/wan3-prime-form', () => ({
  Wan3PrimeForm: (props: any) => <div data-testid="wan-form" data-model={props.model} data-owner={props.ownerTaskId || ''} data-recipe-model={props.initialRecipe?.model || ''} data-source={props.publicationSourceId || ''}>{props.modelSelector}</div>,
}))

const models: VideoModel[] = [
  { id: 'wan_3_prime', label: 'Wan 3.0 Video Prime' },
  { id: 'wan_3', label: 'Wan 3.0 Video' },
  ...['seedance_2_5', 'gemini_omni', 'grok', 'kling_v1', 'kling_v2', 'v3', 'v26', 'veo3', 'veo3_fast', 'seedance_2'].map(id => ({ id, label: id })),
].map(item => ({ ...item, description: 'Видео', supports: ['text', 'imgtxt'], ratios: ['16:9'], durations: [5], costs: { '5': 1 } }))

function choose(model: 'wan_3' | 'wan_3_prime') {
  fireEvent.click(screen.getByRole('button', { expanded: false }))
  const menu = within(screen.getByTestId('model-select-menu'))
  fireEvent.click(menu.getByRole('button', { name: model === 'wan_3' ? /^Wan 3\.0 Video Видео/ : /^Wan 3\.0 Video Prime/ }))
}

test('Create Video routes both first-page choices to the correct WAN composer key', () => {
  const onModelSelected = jest.fn()
  const onSubmit = jest.fn()
  render(<VideoGeneratorForm models={models} credits={100} isSubmitting={false} onSubmit={onSubmit} onModelSelected={onModelSelected} />)
  expect(screen.getByTestId('wan-form')).toHaveAttribute('data-model', 'wan_3_prime')
  choose('wan_3')
  expect(screen.getByTestId('wan-form')).toHaveAttribute('data-model', 'wan_3')
  expect(onModelSelected).toHaveBeenLastCalledWith('wan_3')
  choose('wan_3_prime')
  expect(screen.getByTestId('wan-form')).toHaveAttribute('data-model', 'wan_3_prime')
  expect(onModelSelected).toHaveBeenLastCalledWith('wan_3_prime')
  expect(onSubmit).not.toHaveBeenCalled()
})

test.each(['wan_3', 'wan_3_prime'] as const)('switching away from %s clears stale owner, recipe and publication bindings', initialModel => {
  const preset: VideoPromptPreset = {
    title: 'Own repeat', model: initialModel, prompt: 'Private author instructions', scenario: 'text',
    wan3OwnerTaskId: 'owned-task', sourceFeedGenId: 47,
    wan3Recipe: { model: initialModel, prompt: 'Private author instructions', scenario: 'text', resolution: '720P', aspect_ratio: '16:9', duration: 5, audio: false, nsfw_checker: true },
  }
  const onSubmit = jest.fn()
  const props = { models, credits: 100, isSubmitting: false, onSubmit, promptPreset: preset }
  const { rerender } = render(<VideoGeneratorForm {...props} />)
  expect(screen.getByTestId('wan-form')).toHaveAttribute('data-model', initialModel)
  expect(screen.getByTestId('wan-form')).toHaveAttribute('data-owner', 'owned-task')
  expect(screen.getByTestId('wan-form')).toHaveAttribute('data-recipe-model', initialModel)
  const nextModel = initialModel === 'wan_3' ? 'wan_3_prime' : 'wan_3'
  choose(nextModel)
  rerender(<VideoGeneratorForm {...props} />)
  expect(screen.getByTestId('wan-form')).toHaveAttribute('data-model', nextModel)
  expect(screen.getByTestId('wan-form')).toHaveAttribute('data-owner', '')
  expect(screen.getByTestId('wan-form')).toHaveAttribute('data-recipe-model', '')
  expect(screen.getByTestId('wan-form')).toHaveAttribute('data-source', '')
  expect(onSubmit).not.toHaveBeenCalled()
})
