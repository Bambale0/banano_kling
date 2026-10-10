import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VideoGeneratorForm } from './video-generator-form'
import { quoteWan3Prime, uploadWan3PrimeReference, generateWan3Prime } from '@/lib/wan3-prime-api'
import type { VideoModel } from '@/lib/types'

jest.mock('@/components/forms/model-select', () => ({
  ModelSelect: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => (
    <select aria-label="WAN model" value={value} onChange={event => onChange(event.target.value)}>
      <option value="wan_3_prime">Prime</option><option value="wan_3">Ordinary</option>
    </select>
  ),
}))
jest.mock('@/lib/wan3-prime-api', () => ({
  quoteWan3Prime: jest.fn(), generateWan3Prime: jest.fn(), uploadWan3PrimeReference: jest.fn(),
  importWan3PrimeReference: jest.fn(), fetchWan3PrimeOwnerRecipe: jest.fn(),
  fetchWan3PrimeRepeatPlan: jest.fn(), fetchWan3PrimeTrendPlan: jest.fn(),
}))
const models: VideoModel[] = ['wan_3_prime', 'wan_3'].map(id => ({
  id, label: id, description: id, durations: [5, 6], ratios: ['adaptive'],
  supports: ['text', 'imgtxt', 'first_last', 'video', 'edit', 'file', 'link'],
  costs: {}, quality_costs: { '720p': 4 }, requires_quality_pricing: true,
}))

test('switch Prime to ordinary while upload is pending discards old media and quote identity', async () => {
  let finish!: (value: unknown) => void
  ;(uploadWan3PrimeReference as jest.Mock).mockReturnValue(new Promise(resolve => { finish = resolve }))
  ;(quoteWan3Prime as jest.Mock).mockResolvedValue({
    ok: true, quote_hash: 'ordinary-quote', reserve_cost: 20, auto_duration: false,
    source_video_duration_seconds: 0, billing_duration_seconds: 5,
  })
  render(<VideoGeneratorForm models={models} onSubmit={jest.fn()} isSubmitting={false} credits={1000} />)
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  fireEvent.change(screen.getByLabelText('Загрузить видео-референсы'), {
    target: { files: [new File(['old'], 'prime-old.mp4', { type: 'video/mp4' })] },
  })
  await waitFor(() => expect(uploadWan3PrimeReference).toHaveBeenCalledTimes(1))
  fireEvent.change(screen.getByLabelText('WAN model'), { target: { value: 'wan_3' } })
  expect(screen.getByText('Wan 3.0 Video')).toBeInTheDocument()
  await act(async () => finish({ id: 'old', name: 'prime-old.mp4', url: 'https://owned.test/old.mp4', type: 'video', size: 3 }))
  expect(screen.queryByText('prime-old.mp4')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'ordinary text' } })
  await waitFor(() => expect(quoteWan3Prime).toHaveBeenCalled())
  expect((quoteWan3Prime as jest.Mock).mock.calls.at(-1)[0].recipe).toMatchObject({
    model: 'wan_3', prompt: 'ordinary text', reference_video_urls: [],
  })
  expect(generateWan3Prime).not.toHaveBeenCalled()
})
