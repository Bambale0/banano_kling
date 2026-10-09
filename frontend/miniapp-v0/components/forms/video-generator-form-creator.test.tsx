import '@testing-library/jest-dom'
import { fireEvent, render, screen, within } from '@testing-library/react'
jest.mock('@/components/forms/scenario-select', () => ({ ScenarioSelect: ({ onChange }: { onChange: (scenario: string) => void }) => <button onClick={() => onChange('text')}>Текст → Видео</button> }))
import { VideoGeneratorForm } from './video-generator-form'
import type { VideoModel, VideoPromptPreset } from '@/lib/types'

const model: VideoModel = {
  id: 'seedance_2', label: 'Seedance 2.0', description: 'Synthetic creator pricing',
  durations: [5, 10], ratios: ['16:9'], supports: ['text', 'imgtxt', 'video'],
  costs: { '5': 6, '10': 12.5 }, max_video_references: 3,
}
const videos = ['one', 'two'].map((name) => ({ id: name, name: `${name}.mp4`,
  type: 'video' as const, url: `https://example.test/${name}.mp4`, size: 10 }))

test('Seedance 2 applies one reference multiplier to displayed creator totals and affordability', () => {
  const preset: VideoPromptPreset = { title: 'Synthetic creator test', model: 'seedance_2', scenario: 'video', prompt: 'Synthetic motion', duration: 5, ratio: '16:9' }
  render(<VideoGeneratorForm models={[model]} credits={11} isSubmitting={false} onSubmit={jest.fn()}
    promptPreset={preset} savedVideoReferences={videos} />)
  const summary = screen.getByText('Стоимость').parentElement!.parentElement!
  expect(within(summary).getByText('6', { exact: true })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'one.mp4' }))
  expect(within(summary).getByText('12', { exact: true })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Запустить видео/ })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'two.mp4' }))
  expect(within(summary).getByText('12', { exact: true })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Текст → Видео' }))
  expect(within(summary).getByText('12', { exact: true })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /10с/ }))
  expect(within(summary).getByText('25', { exact: true })).toBeInTheDocument()
})
