import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
jest.mock('@/components/forms/scenario-select', () => ({ ScenarioSelect: ({ value }: { value: string }) => <span>{value}</span> }))
import { VideoGeneratorForm } from './video-generator-form'
import type { VideoModel, VideoPromptPreset } from '@/lib/types'

const model = (id: string): VideoModel => ({
  id, label: id, description: 'Synthetic pricing', durations: [5, 10], ratios: ['16:9'],
  supports: ['text', 'imgtxt', 'video'], costs: { '5': 3.5, '10': 6 },
  max_image_references: 8, max_video_references: 5,
})
const fixedPreset = (id: string, multiplier: unknown = 2): VideoPromptPreset => ({
  title: 'Повторить видео', prompt: '', promptHidden: true, model: id, scenario: 'video',
  ratio: '16:9', duration: 5, sourceFeedGenId: 42,
  repeatReferenceSlots: { version: 1, available: true, cost_multiplier: multiplier,
    images: [], videos: [{ index: 0, role: 'reference', binding: 'fixed' }, { index: 1, role: 'reference', binding: 'fixed' }],
  },
} as VideoPromptPreset)

describe('typed repeat authoritative pricing', () => {
  it.each(['seedance_2', 'seedance_2_5'])('includes retained videos once in %s price and blocks insufficient balance', async (id) => {
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    const preset = fixedPreset(id)
    const props = { models: [model(id)], onSubmit, promptPreset: preset, isSubmitting: false }
    const view = render(<VideoGeneratorForm {...props} credits={5} />)
    const launch = screen.getByRole('button', { name: /Запустить видео/i })
    expect(launch).toBeDisabled()
    expect(screen.getByText('Недостаточно бананов. Пополните баланс.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /5с.*1.4\/с/ })).toBeInTheDocument()
    expect(screen.getByText('5 сек. • 16:9 • 1.4🍌/с')).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Модель' })).toHaveTextContent('1.4')
    const cost = screen.getByText('Стоимость').parentElement!.parentElement!
    expect(within(cost).getByText('7', { exact: true })).toBeInTheDocument()
    view.rerender(<VideoGeneratorForm {...props} credits={7} />)
    expect(launch).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: /10с.*1.2\/с/ }))
    expect(launch).toBeDisabled()
    expect(within(cost).getByText('12', { exact: true })).toBeInTheDocument()
    expect(screen.getByText('10 сек. • 16:9 • 1.2🍌/с')).toBeInTheDocument()
    view.rerender(<VideoGeneratorForm {...props} credits={12} />)
    fireEvent.click(launch)
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ sourceFeedGenId: 42, duration: 10, videoReferences: [] })))
  })
  it.each(['seedance_2', 'seedance_2_5'])('uses one %s multiplier for mixed retained and replacement videos', async (id) => {
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    const preset = fixedPreset(id)
    preset.repeatReferenceSlots!.videos[1].binding = 'upload'
    const uploaded = { id: 'own-clip', name: 'own.mp4', url: 'https://example.test/own.mp4', type: 'video' as const, size: 10 }
    render(<VideoGeneratorForm models={[model(id)]} onSubmit={onSubmit} promptPreset={preset} isSubmitting={false} credits={7} savedVideoReferences={[uploaded]} />)
    const launch = screen.getByRole('button', { name: /Запустить видео/i })
    expect(launch).toBeDisabled()
    expect(screen.getByText('7', { exact: true })).toBeInTheDocument()
    fireEvent.click(within(screen.getByRole('group', { name: 'Видео 2' })).getByRole('button', { name: 'own.mp4' }))
    expect(launch).toBeEnabled()
    expect(screen.getByText('7', { exact: true })).toBeInTheDocument()
    fireEvent.click(launch)
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ videoReferences: [uploaded.url] })))
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty('cost_multiplier')
  })
  it('keeps a no-video recipe at the authoritative neutral multiplier', () => {
    const preset = fixedPreset('seedance_2_5', 1)
    preset.scenario = 'imgtxt'
    preset.repeatReferenceSlots!.videos = []
    preset.repeatReferenceSlots!.images = [{ index: 0, role: 'first_frame', binding: 'fixed' }]
    render(<VideoGeneratorForm models={[model('seedance_2_5')]} onSubmit={jest.fn()} promptPreset={preset} isSubmitting={false} credits={4} />)
    expect(screen.getByText('3.5', { exact: true })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Запустить видео/i })).toBeEnabled()
  })
  it('uses the supplied multiplier instead of a duplicated client tariff', () => {
    render(<VideoGeneratorForm models={[model('seedance_2_5')]} onSubmit={jest.fn()} promptPreset={fixedPreset('seedance_2_5', 3)} isSubmitting={false} credits={8} />)
    expect(screen.getByRole('button', { name: /Запустить видео/i })).toBeDisabled()
    expect(screen.getByText('10.5', { exact: true })).toBeInTheDocument()
  })
  it.each([undefined, 0, -1, Number.NaN, Number.POSITIVE_INFINITY, '2'])('blocks an invalid or missing multiplier %s', (multiplier) => {
    const preset = fixedPreset('seedance_2_5', multiplier)
    if (multiplier === undefined) delete (preset.repeatReferenceSlots as unknown as Record<string, unknown>).cost_multiplier
    render(<VideoGeneratorForm models={[model('seedance_2_5')]} onSubmit={jest.fn()} promptPreset={preset} isSubmitting={false} credits={100} />)
    expect(screen.getByRole('button', { name: /Запустить видео/i })).toBeDisabled()
    expect(screen.getByText('Стоимость недоступна')).toBeInTheDocument()
  })
})
