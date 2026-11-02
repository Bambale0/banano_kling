import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VideoGeneratorForm } from './video-generator-form'
import { useOptionalApp } from '@/lib/app-context'
import type { VideoModel, VideoPromptPreset } from '@/lib/types'

jest.mock('@/lib/app-context', () => ({ useOptionalApp: jest.fn() }))
jest.mock('@/components/forms/scenario-select', () => ({
  ScenarioSelect: ({ value }: { value: string }) => <span>{value}</span>,
}))

const openBalance = jest.fn()
const model: VideoModel = {
  id: 'seedance_2', label: 'Seedance 2', description: 'Repeat test model',
  ratios: ['16:9'], durations: [5], supports: ['video', 'text'],
  costs: { '5': 5 }, max_image_references: 8, max_video_references: 1,
}
const preset: VideoPromptPreset = {
  title: 'Повторить чужое видео', model: 'seedance_2', prompt: '',
  promptHidden: true, sourceFeedGenId: 42, scenario: 'video', ratio: '16:9',
  duration: 5, repeatReferenceSlots: {
    version: 1, available: true, images: [], videos: [
      { index: 0, role: 'reference', binding: 'fixed' },
    ],
  },
} as VideoPromptPreset
const quote = {
  cost: 21, quote_hash: 'server-confirmed-quote', source_video_seconds: 10,
  output_seconds: 5, billable_seconds: 15, admin_free: false,
}

it('offers a configured package only after server verifies the private video repeat cost', async () => {
  ;(useOptionalApp as jest.Mock).mockReturnValue({
    state: {
      mode: 'live', user: { credits: 5, isAdmin: false },
      paymentPackages: [
        { id: 'mini', name: 'Мини', credits: 15, price_rub: 150 },
        { id: 'start', name: 'Старт', credits: 25, price_rub: 250 },
      ],
    },
    openBalance,
  })
  const onQuote = jest.fn().mockResolvedValue(quote)
  const onSubmit = jest.fn().mockResolvedValue(undefined)
  render(<VideoGeneratorForm models={[model]} credits={5} isSubmitting={false}
    promptPreset={preset} onSubmit={onSubmit} onQuote={onQuote} />)

  expect(screen.queryByRole('region', { name: 'Пополнение для генерации' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать точную стоимость' }))
  await screen.findByRole('region', { name: 'Пополнение для генерации' })
  expect(screen.getByText('Не хватает 16🍌')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Купить 25🍌 за 250 ₽/ }))
  expect(openBalance).toHaveBeenCalledWith({ packageId: 'start', requiredCredits: 21 })
  expect(onSubmit).not.toHaveBeenCalled()
  await waitFor(() => expect(onQuote).toHaveBeenCalledTimes(1))
})
