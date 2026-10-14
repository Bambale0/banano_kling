import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VideoGeneratorForm } from './video-generator-form'
import type { VideoModel, VideoPromptPreset } from '@/lib/types'

jest.mock('./scenario-select', () => ({
  ScenarioSelect: ({ value }: { value: string }) => <span>{value}</span>,
}))

const videoModel: VideoModel = {
  id: 'seedance_2', label: 'Seedance 2', description: 'Verified source prices',
  durations: [5, 10], ratios: ['16:9'], supports: ['text', 'video'],
  costs: { '5': 20, '10': 40 }, max_video_references: 5, max_image_references: 2,
}

const reference = {
  id: 'ref-1', name: 'source.mp4', url: 'https://owned.test/uploads/source.mp4',
  type: 'video' as const, size: 400,
}
const preset: VideoPromptPreset = {
  title: 'Source pricing', prompt: 'Make a video', model: 'seedance_2',
  scenario: 'video', ratio: '16:9', duration: 5, initialVideoReferences: [reference],
}

test('video reference must be quoted as input + output seconds and explicitly confirmed before debit', async () => {
  const onSubmit = jest.fn().mockResolvedValue(undefined)
  const onQuote = jest.fn().mockResolvedValue({
    quote_hash: 'signed-price-48', cost: 48,
    source_video_seconds: 7, output_seconds: 5, billable_seconds: 12, admin_free: false,
  })
  render(<VideoGeneratorForm models={[videoModel]} onSubmit={onSubmit} onQuote={onQuote}
    promptPreset={preset} isSubmitting={false} credits={60} />)
  const quoteButton = await screen.findByRole('button', { name: 'Рассчитать точную стоимость' })
  expect(screen.queryByText('Стоимость: 40🍌')).not.toBeInTheDocument()
  fireEvent.click(quoteButton)
  await waitFor(() => expect(onQuote).toHaveBeenCalledTimes(1))
  await screen.findByText(/Видеореференсы: 7 с \+ генерация: 5 с = 12 с/)
  // 48 / (7 + 5) is 4 credits per billable second, not a fake 9.6x output rate.
  expect(screen.getByText(/12 сек\. \(вход \+ результат\).*4🍌\/с/)).toBeInTheDocument()
  expect(onSubmit).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить цену и запустить' }))
  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
    model: 'seedance_2', duration: 5, videoReferences: [reference.url],
    pricingQuoteHash: 'signed-price-48',
  })))
})

test('changing output duration invalidates reference quote before charge', async () => {
  const onSubmit = jest.fn().mockResolvedValue(undefined)
  const onQuote = jest.fn().mockResolvedValue({
    quote_hash: 'five-seconds', cost: 48,
    source_video_seconds: 7, output_seconds: 5, billable_seconds: 12, admin_free: false,
  })
  render(<VideoGeneratorForm models={[videoModel]} onSubmit={onSubmit} onQuote={onQuote}
    promptPreset={preset} isSubmitting={false} credits={100} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Рассчитать точную стоимость' }))
  await screen.findByText(/Видеореференсы: 7 с/)
  fireEvent.click(screen.getByRole('button', { name: /10с/ }))
  expect(screen.getByRole('button', { name: 'Рассчитать точную стоимость' })).toBeEnabled()
  expect(onSubmit).not.toHaveBeenCalled()
})
