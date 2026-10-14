import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
jest.mock('@/components/forms/scenario-select', () => ({
  ScenarioSelect: ({ value }: { value: string }) => <span>{value}</span>,
}))
import { VideoGeneratorForm } from './video-generator-form'
import type { VideoModel, VideoPromptPreset } from '@/lib/types'

const model = (id: string): VideoModel => ({
  id, label: id, description: 'Synthetic pricing', durations: [5, 10],
  ratios: ['16:9'], supports: ['text', 'imgtxt', 'video'],
  costs: { '5': 3.5, '10': 6 }, max_image_references: 8,
  max_video_references: 5,
})
const fixedPreset = (id: string, multiplier: unknown = 1): VideoPromptPreset => ({
  title: 'Повторить видео', prompt: '', promptHidden: true, model: id,
  scenario: 'video', ratio: '16:9', duration: 5, sourceFeedGenId: 42,
  repeatReferenceSlots: {
    version: 1, available: true, cost_multiplier: multiplier,
    ...(id === 'seedance_2_5' ? {
      duration_costs: { '5': 7, '10': 12 }, pricing_quality: '720p',
    } : {}),
    images: [], videos: [
      { index: 0, role: 'reference', binding: 'fixed' },
      { index: 1, role: 'reference', binding: 'fixed' },
    ],
  },
} as VideoPromptPreset)

const quote = {
  cost: 21, quote_hash: 'server-measured-hash',
  source_video_seconds: 10, output_seconds: 5,
  billable_seconds: 15, admin_free: false,
}
const launchButton = () => screen.getByRole('button', {
  name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/,
})

describe('typed repeat price requires server measurement before debit', () => {
  it.each(['seedance_2', 'seedance_2_5'])(
    '%s waits for source+output quote and checks final affordability', async (id) => {
      const onSubmit = jest.fn().mockResolvedValue(undefined)
      const onQuote = jest.fn().mockResolvedValue(quote)
      const props = { models: [model(id)], onSubmit, onQuote,
        promptPreset: fixedPreset(id), isSubmitting: false }
      const view = render(<VideoGeneratorForm {...props} credits={5} />)
      const launch = launchButton()
      expect(launch).toBeEnabled()
      expect(onSubmit).not.toHaveBeenCalled()
      fireEvent.click(launch)
      await screen.findByText(/Видеореференсы: 10 с \+ генерация: 5 с = 15 с/)
      expect(onQuote).toHaveBeenCalledTimes(1)
      expect(onSubmit).not.toHaveBeenCalled()
      expect(screen.getByText('Недостаточно бананов. Пополните баланс.')).toBeInTheDocument()
      expect(launch).toBeDisabled()
      view.rerender(<VideoGeneratorForm {...props} credits={21} />)
      expect(launch).toBeEnabled()
      fireEvent.click(launch)
      await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
        duration: 5, videoReferences: [], sourceFeedGenId: 42,
        pricingQuoteHash: quote.quote_hash,
      })))
    },
  )

  it.each(['seedance_2', 'seedance_2_5'])(
    '%s prices fixed plus uploaded clips but sends only user-uploaded references', async (id) => {
      const onSubmit = jest.fn().mockResolvedValue(undefined)
      const onQuote = jest.fn().mockResolvedValue(quote)
      const preset = fixedPreset(id)
      preset.repeatReferenceSlots!.videos[1].binding = 'upload'
      const uploaded = { id: 'clip', name: 'own.mp4', url: 'https://example.test/own.mp4',
        type: 'video' as const, size: 10 }
      render(<VideoGeneratorForm models={[model(id)]} onSubmit={onSubmit} onQuote={onQuote}
        promptPreset={preset} isSubmitting={false} credits={25}
        savedVideoReferences={[uploaded]} />)
      expect(launchButton()).toBeDisabled()
      fireEvent.click(within(screen.getByRole('group', { name: 'Видео 2' }))
        .getByRole('button', { name: 'own.mp4' }))
      expect(launchButton()).toBeEnabled()
      fireEvent.click(launchButton())
      await screen.findByText(/Видеореференсы: 10 с/)
      expect(onSubmit).not.toHaveBeenCalled()
      fireEvent.click(launchButton())
      await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
        sourceFeedGenId: 42, videoReferences: [uploaded.url],
        pricingQuoteHash: quote.quote_hash,
      })))
      expect(onSubmit.mock.calls[0][0]).not.toHaveProperty('cost_multiplier')
    },
  )

  it('does not invent a multiplier for a no-video recipe', () => {
    const preset = fixedPreset('seedance_2_5', 1)
    preset.scenario = 'imgtxt'
    preset.repeatReferenceSlots!.duration_costs = { '5': 3.5 }
    preset.repeatReferenceSlots!.videos = []
    preset.repeatReferenceSlots!.images = [{ index: 0, role: 'first_frame', binding: 'fixed' }]
    render(<VideoGeneratorForm models={[model('seedance_2_5')]} onSubmit={jest.fn()}
      promptPreset={preset} isSubmitting={false} credits={4} />)
    expect(screen.getByText('3.5', { exact: true })).toBeInTheDocument()
    expect(launchButton()).toBeEnabled()
  })

  it('never charges using an untrusted saved multiplier', async () => {
    const onSubmit = jest.fn()
    const onQuote = jest.fn().mockResolvedValue(quote)
    render(<VideoGeneratorForm models={[model('seedance_2')]} onSubmit={onSubmit}
      onQuote={onQuote} promptPreset={fixedPreset('seedance_2', 3)}
      isSubmitting={false} credits={8} />)
    fireEvent.click(launchButton())
    await screen.findByText(/Видеореференсы: 10 с/)
    expect(launchButton()).toBeDisabled()
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.queryByText('10.5', { exact: true })).not.toBeInTheDocument()
  })

  it.each([undefined, 0, -1, Number.NaN, Number.POSITIVE_INFINITY, '2'])(
    'rejects malformed reference descriptors %s', (multiplier) => {
      const preset = fixedPreset('seedance_2_5', multiplier)
      if (multiplier === undefined) {
        delete (preset.repeatReferenceSlots as unknown as Record<string, unknown>).cost_multiplier
      }
      render(<VideoGeneratorForm models={[model('seedance_2_5')]} onSubmit={jest.fn()}
        promptPreset={preset} isSubmitting={false} credits={100} />)
      expect(launchButton()).toBeDisabled()
      expect(screen.getByText('Стоимость недоступна')).toBeInTheDocument()
    },
  )
})
