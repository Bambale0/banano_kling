import '@testing-library/jest-dom'
import { fireEvent, render, screen, within } from '@testing-library/react'
jest.mock('@/components/forms/scenario-select', () => ({
  ScenarioSelect: ({ onChange }: { onChange: (scenario: string) => void }) =>
    <button onClick={() => onChange('text')}>Текст → Видео</button>,
}))
import { VideoGeneratorForm } from './video-generator-form'
import type { VideoModel, VideoPromptPreset } from '@/lib/types'

const model: VideoModel = {
  id: 'seedance_2', label: 'Seedance 2.0', description: 'Synthetic creator pricing',
  durations: [5, 10], ratios: ['16:9'], supports: ['text', 'imgtxt', 'video'],
  costs: { '5': 6, '10': 12.5 }, max_video_references: 3,
}
const videos = ['one', 'two'].map((name) => ({
  id: name, name: `${name}.mp4`, type: 'video' as const,
  url: `https://example.test/${name}.mp4`, size: 10,
}))
const preset: VideoPromptPreset = {
  title: 'Synthetic creator test', model: 'seedance_2',
  scenario: 'video', prompt: 'Synthetic motion', duration: 5, ratio: '16:9',
}

test('Seedance creator quote adds measured reference seconds once and requires approval', async () => {
  const onSubmit = jest.fn()
  const onQuote = jest.fn().mockResolvedValue({
    cost: 18, quote_hash: 'approved-creator-quote',
    source_video_seconds: 10, output_seconds: 5,
    billable_seconds: 15, admin_free: false,
  })
  const view = render(<VideoGeneratorForm models={[model]} credits={11}
    isSubmitting={false} onSubmit={onSubmit} onQuote={onQuote}
    promptPreset={preset} savedVideoReferences={videos} />)
  const summary = screen.getByText('Стоимость').parentElement!.parentElement!
  expect(within(summary).getByText('6', { exact: true })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'one.mp4' }))
  expect(screen.queryByText('12', { exact: true })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'two.mp4' }))
  const launch = screen.getByRole('button', { name: /Рассчитать точную стоимость/ })
  fireEvent.click(launch)
  await screen.findByText(/Видеореференсы: 10 с \+ генерация: 5 с = 15 с/)
  expect(onQuote).toHaveBeenCalledTimes(1)
  expect(onSubmit).not.toHaveBeenCalled()
  expect(within(screen.getByText('Стоимость').parentElement!.parentElement!).getByText('18', { exact: true })).toBeInTheDocument()
  expect(launch).toBeDisabled()
  view.rerender(<VideoGeneratorForm models={[model]} credits={20}
    isSubmitting={false} onSubmit={onSubmit} onQuote={onQuote}
    promptPreset={preset} savedVideoReferences={videos} />)
  fireEvent.click(screen.getByRole('button', { name: /Подтвердить цену и запустить/ }))
  await screen.findByText(/К оплате: 18🍌/)
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
    pricingQuoteHash: 'approved-creator-quote',
    videoReferences: videos.map(item => item.url),
  }))
})
