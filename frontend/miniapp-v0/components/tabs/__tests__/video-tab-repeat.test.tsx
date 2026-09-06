import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { VideoTab } from '@/components/tabs/video-tab'
import { useApp } from '@/lib/app-context'
import { repeatSeedance25 } from '@/lib/seedance25-api'

jest.mock('@/lib/app-context', () => ({
  useApp: jest.fn(),
}))

jest.mock('@/lib/api', () => ({
  generateVideo: jest.fn(),
  uploadFile: jest.fn(),
}))

jest.mock('@/lib/seedance25-api', () => ({
  repeatSeedance25: jest.fn(),
}))

jest.mock('@/components/forms/video-generator-form', () => ({
  VideoGeneratorForm: () => <div data-testid="regular-video-form">regular form</div>,
}))

jest.mock('@/components/forms/seedance25-public-form', () => ({
  Seedance25PublicForm: () => <div data-testid="seedance25-form">seedance form</div>,
}))

jest.mock('@/components/result-card', () => ({
  ResultCard: () => <div data-testid="result-card">result</div>,
}))

const mockedUseApp = useApp as jest.MockedFunction<typeof useApp>
const mockedRepeatSeedance25 = repeatSeedance25 as jest.MockedFunction<typeof repeatSeedance25>

const videoModels = [
  {
    id: 'seedance_2_5',
    label: 'Seedance 2.5',
    description: 'new',
    durations: [5],
    ratios: ['16:9'],
    supports: ['text'],
    costs: { '5': 5 },
  },
  {
    id: 'seedance_2',
    label: 'Bytedance Seedance 2.0',
    description: 'regular',
    durations: [5],
    ratios: ['16:9'],
    supports: ['text'],
    costs: { '5': 4 },
  },
]

function mockApp(videoPromptPreset: Record<string, unknown>) {
  mockedUseApp.mockReturnValue({
    state: {
      mode: 'live',
      user: { credits: 100, isAdmin: false },
      videoModels,
      savedReferences: [],
    },
    addTask: jest.fn(),
    setCredits: jest.fn(),
    setTaskDetail: jest.fn(),
    selectTask: jest.fn(),
    addSavedReference: jest.fn(),
    videoPromptPreset,
    setVideoPromptPreset: jest.fn(),
    refreshTasks: jest.fn(),
  } as ReturnType<typeof useApp>)
}

describe('VideoTab repeat mode selection', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('opens regular catalog form for repeat presets targeting non-Seedance models', () => {
    mockApp({
      title: 'Повторить видео',
      prompt: 'prompt',
      model: 'seedance_2',
    })

    render(<VideoTab />)

    expect(screen.getByTestId('regular-video-form')).toBeInTheDocument()
    expect(screen.queryByTestId('seedance25-form')).not.toBeInTheDocument()
  })

  it('opens a one-click Seedance 2.5 repeat card instead of the full settings form', async () => {
    mockApp({
      title: 'Повторить Seedance 2.5',
      prompt: '',
      model: 'seedance_2_5',
      duration: 10,
      ratio: '9:16',
      sourceFeedGenId: 42,
      promptHidden: true,
    })
    mockedRepeatSeedance25.mockResolvedValue({
      ok: true,
      status: 'queued',
      task_id: 'repeat-task',
      credits: 88,
      cost: 12,
      model_label: 'Seedance 2.5',
      admin_free: false,
      resolution: '720p',
      duration: 10,
      aspect_ratio: '9:16',
      scenario: 'multimodal',
    })

    render(<VideoTab />)

    expect(screen.getByTestId('seedance25-repeat-card')).toBeInTheDocument()
    expect(screen.queryByTestId('regular-video-form')).not.toBeInTheDocument()
    expect(screen.queryByTestId('seedance25-form')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Другие модели/i })).not.toBeInTheDocument()
    expect(screen.getByText('10 сек')).toBeInTheDocument()
    expect(screen.getByText('9:16')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /^Повторить видео$/i }))
    await waitFor(() => expect(mockedRepeatSeedance25).toHaveBeenCalledWith(42))
    expect(await screen.findByText(/Повтор запущен/i)).toBeInTheDocument()
  })
})
