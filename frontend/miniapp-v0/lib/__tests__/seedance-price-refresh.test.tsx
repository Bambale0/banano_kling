import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { AppProvider, useApp } from '../app-context'
import { bootstrapApp } from '../api'
import { VideoGeneratorForm } from '@/components/forms/video-generator-form'

jest.mock('../api', () => ({
  bootstrapApp: jest.fn(), fetchFeedItem: jest.fn(), fetchPromptDetail: jest.fn(), fetchTaskDetail: jest.fn(),
  getInitData: jest.fn(() => 'fixture'), getStartParamFallback: jest.fn(() => ''),
  hasTelegramInitData: jest.fn(() => true), waitForTelegramInitData: jest.fn(async () => true),
}))
jest.mock('../genjutsu-api', () => ({ genjutsuCall: jest.fn(), openGenjutsu: jest.fn() }))
jest.mock('@/components/forms/scenario-select', () => ({ ScenarioSelect: () => null }))
const bootstrap = bootstrapApp as jest.Mock
const payload = (cost: number) => ({
  telegram_id: 1, credits: 55, telegram_chat_available: true, image_models: [], recent_tasks: [], saved_references: [],
  video_models: [{ id: 'seedance_2', label: 'Seedance 2.0', description: 'Synthetic configured 720p tariff',
    durations: [5, 10], ratios: ['16:9'], supports: ['text', 'imgtxt', 'video'],
    costs: { '5': cost, '10': cost * 2 }, quality_costs: { '720p': cost / 5 }, max_video_references: 3 }],
})

function Harness() {
  const app = useApp()
  return app.state.isLoading ? null : <VideoGeneratorForm models={app.state.videoModels}
    credits={app.state.user.credits} isSubmitting={false} onSubmit={jest.fn()} />
}

beforeEach(() => {
  jest.clearAllMocks()
  window.history.replaceState({}, '', '/mini-app/')
  bootstrap.mockResolvedValue(payload(25))
})
afterEach(() => jest.useRealTimers())

async function mount() {
  render(<AppProvider><Harness /></AppProvider>)
  const input = await screen.findByRole('textbox')
  fireEvent.change(input, { target: { value: 'Synthetic saved draft' } })
  fireEvent.click(screen.getByRole('button', { name: /10с/ }))
  const summary = screen.getByText('Стоимость').parentElement!.parentElement!
  expect(within(summary).getByText('50', { exact: true })).toBeInTheDocument()
  return { input, summary }
}

test('focus refresh applies edited ordinary prices and affordability without resetting draft or duration', async () => {
  const { input, summary } = await mount()
  bootstrap.mockResolvedValue(payload(30))
  fireEvent.focus(window)
  await waitFor(() => expect(within(summary).getByText('60', { exact: true })).toBeInTheDocument())
  expect(screen.getByRole('textbox')).toBe(input)
  expect(input).toHaveValue('Synthetic saved draft')
  expect(screen.getByRole('button', { name: /Запустить видео/ })).toBeDisabled()
  bootstrap.mockRejectedValue(new Error('Synthetic refresh timeout'))
  fireEvent.focus(window)
  await waitFor(() => expect(bootstrap).toHaveBeenCalledTimes(3))
  expect(within(summary).getByText('60', { exact: true })).toBeInTheDocument()
})

test('visible five-second refresh picks up new ordinary prices', async () => {
  jest.useFakeTimers()
  const { summary } = await mount()
  bootstrap.mockResolvedValue(payload(30))
  await act(async () => jest.advanceTimersByTime(5_000))
  expect(within(summary).getByText('60', { exact: true })).toBeInTheDocument()
})
