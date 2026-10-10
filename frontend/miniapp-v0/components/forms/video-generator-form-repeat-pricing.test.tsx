import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
jest.mock('@/components/forms/scenario-select', () => ({ ScenarioSelect: ({ value }: { value: string }) => <span>{value}</span> }))
import { VideoGeneratorForm } from './video-generator-form'
import type { VideoModel, VideoPromptPreset } from '@/lib/types'
import { quoteVideo, MiniAppApiError } from '@/lib/api'
jest.mock('@/lib/api', () => ({ ...jest.requireActual('@/lib/api'), quoteVideo: jest.fn() }))
beforeEach(() => {
  jest.clearAllMocks()
  ;(quoteVideo as jest.Mock).mockImplementation(async payload => ({ quote_id: 'a'.repeat(32), quote_hash: 'b'.repeat(64), cost: (7 + payload.duration) * 2, charge_cost: (7 + payload.duration) * 2, input_seconds: 7, selected_output_seconds: payload.duration }))
})

const model = (id: string): VideoModel => ({
  id, label: id, description: 'Synthetic pricing', durations: [5, 10], ratios: ['16:9'],
  supports: ['text', 'imgtxt', 'video'], costs: { '5': 3.5, '10': 6 },
  max_image_references: 8, max_video_references: 5,
})
const fixedPreset = (id: string, multiplier: unknown = 2): VideoPromptPreset => ({
  title: 'Повторить видео', prompt: '', promptHidden: true, model: id, scenario: 'video',
  ratio: '16:9', duration: 5, sourceFeedGenId: 42,
  repeatReferenceSlots: { version: 1, available: true, cost_multiplier: multiplier, ...(id === 'seedance_2_5' ? { duration_costs: { '5': 7, '10': 12 }, pricing_quality: '720p' } : {}),
    images: [], videos: [{ index: 0, role: 'reference', binding: 'fixed' }, { index: 1, role: 'reference', binding: 'fixed' }],
  },
} as VideoPromptPreset)

describe('typed repeat authoritative pricing', () => {
  it.each(['seedance_2', 'seedance_2_5'])('uses measured retained inputs and selected output for %s affordability', async (id) => {
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    const props = { models: [model(id)], onSubmit, promptPreset: fixedPreset(id), isSubmitting: false }
    const view = render(<VideoGeneratorForm {...props} credits={23} />)
    const launch = screen.getByRole('button', { name: /Запустить видео/i })
    expect(launch).toBeDisabled()
    await screen.findByText('Вход 7 с + результат 5 с')
    expect(screen.getByText('Недостаточно бананов. Пополните баланс.')).toBeInTheDocument()
    expect(screen.getByText('24', { exact: true })).toBeInTheDocument()
    view.rerender(<VideoGeneratorForm {...props} credits={24} />)
    await waitFor(() => expect(launch).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: /10с/ }))
    expect(launch).toBeDisabled()
    await screen.findByText('34', { exact: true })
    view.rerender(<VideoGeneratorForm {...props} credits={34} />)
    await waitFor(() => expect(launch).toBeEnabled())
    fireEvent.click(launch)
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ sourceFeedGenId: 42, duration: 10, videoReferences: [], videoQuoteId: 'a'.repeat(32) })))
  })
  it.each(['seedance_2', 'seedance_2_5'])('quotes mixed retained and replacement videos only after upload for %s', async (id) => {
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    const preset = fixedPreset(id)
    preset.repeatReferenceSlots!.videos[1].binding = 'upload'
    const uploaded = { id: 'own-clip', name: 'own.mp4', url: 'https://example.test/own.mp4', type: 'video' as const, size: 10 }
    render(<VideoGeneratorForm models={[model(id)]} onSubmit={onSubmit} promptPreset={preset} isSubmitting={false} credits={24} savedVideoReferences={[uploaded]} />)
    const launch = screen.getByRole('button', { name: /Запустить видео/i })
    expect(launch).toBeDisabled()
    expect(quoteVideo).not.toHaveBeenCalled()
    fireEvent.click(within(screen.getByRole('group', { name: 'Видео 2' })).getByRole('button', { name: 'own.mp4' }))
    await waitFor(() => expect(launch).toBeEnabled())
    expect(screen.getByText('24', { exact: true })).toBeInTheDocument()
    expect(quoteVideo).toHaveBeenCalledWith(expect.objectContaining({ sourceFeedGenId:42, videoReferences:[uploaded.url] }))
    fireEvent.click(launch)
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ videoReferences: [uploaded.url] })))
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty('cost_multiplier')
  })
  it('refreshes a changed price without losing replacements or automatically launching', async () => {
    const onSubmit = jest.fn().mockRejectedValueOnce(new MiniAppApiError('Price changed','video_quote_changed')).mockResolvedValue(undefined)
    const preset = fixedPreset('seedance_2')
    preset.repeatReferenceSlots!.videos[1].binding = 'upload'
    const uploaded = { id:'own',name:'own.mp4',url:'https://example.test/own.mp4',type:'video' as const,size:10 }
    ;(quoteVideo as jest.Mock).mockResolvedValueOnce({ quote_id:'a'.repeat(32),quote_hash:'b'.repeat(64),cost:24,charge_cost:24,input_seconds:7,selected_output_seconds:5 })
      .mockResolvedValue({ quote_id:'c'.repeat(32),quote_hash:'d'.repeat(64),cost:36,charge_cost:36,input_seconds:7,selected_output_seconds:5 })
    render(<VideoGeneratorForm models={[model('seedance_2')]} onSubmit={onSubmit} promptPreset={preset} isSubmitting={false} credits={100} savedVideoReferences={[uploaded]} />)
    fireEvent.change(screen.getByRole('textbox'), { target:{value:'Keep my instruction'} })
    fireEvent.click(screen.getByRole('button',{name:'own.mp4'}))
    const launch = screen.getByRole('button',{name:/Запустить видео/})
    await waitFor(() => expect(launch).toBeEnabled())
    fireEvent.click(launch)
    await screen.findByText('36',{exact:true})
    expect(screen.getByRole('textbox')).toHaveValue('Keep my instruction')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(onSubmit).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(launch).toBeEnabled())
    fireEvent.click(launch)
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2))
    expect(onSubmit.mock.calls[1][0]).toEqual(expect.objectContaining({videoReferences:[uploaded.url],prompt:'Keep my instruction',videoQuoteId:'c'.repeat(32)}))
  })
  it('keeps a no-video recipe at the authoritative neutral multiplier', () => {
    const preset = fixedPreset('seedance_2_5', 1)
    preset.scenario = 'imgtxt'
    preset.repeatReferenceSlots!.duration_costs = { '5': 3.5, '10': 6 }
    preset.repeatReferenceSlots!.videos = []
    preset.repeatReferenceSlots!.images = [{ index: 0, role: 'first_frame', binding: 'fixed' }]
    render(<VideoGeneratorForm models={[model('seedance_2_5')]} onSubmit={jest.fn()} promptPreset={preset} isSubmitting={false} credits={4} />)
    expect(screen.getByText('3.5', { exact: true })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Запустить видео/i })).toBeEnabled()
  })
  it('ignores obsolete client multipliers in favor of the measured server quote', async () => {
    render(<VideoGeneratorForm models={[model('seedance_2')]} onSubmit={jest.fn()} promptPreset={fixedPreset('seedance_2', 3)} isSubmitting={false} credits={23} />)
    expect(await screen.findByText('24', { exact: true })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Запустить видео/i })).toBeDisabled()
  })
  it.each([undefined, 0, -1, Number.NaN, Number.POSITIVE_INFINITY, '2'])('blocks an invalid or missing multiplier %s', (multiplier) => {
    const preset = fixedPreset('seedance_2_5', multiplier)
    if (multiplier === undefined) delete (preset.repeatReferenceSlots as unknown as Record<string, unknown>).cost_multiplier
    render(<VideoGeneratorForm models={[model('seedance_2_5')]} onSubmit={jest.fn()} promptPreset={preset} isSubmitting={false} credits={100} />)
    expect(screen.getByRole('button', { name: /Запустить видео/i })).toBeDisabled()
    expect(screen.getByText('Стоимость недоступна')).toBeInTheDocument()
  })
})
