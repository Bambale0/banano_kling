import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'

import { VideoTab } from '@/components/tabs/video-tab'
import { useApp } from '@/lib/app-context'

jest.mock('@/lib/app-context', () => ({
  useApp: jest.fn(),
}))

jest.mock('@/lib/api', () => ({
  generateVideo: jest.fn(),
  uploadFile: jest.fn(),
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

describe('VideoTab repeat mode selection', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('opens regular catalog form for repeat presets targeting non-Seedance models', () => {
    mockedUseApp.mockReturnValue({
      state: {
        mode: 'live',
        user: { credits: 100, isAdmin: false },
        videoModels: [
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
        ],
        savedReferences: [],
      },
      addTask: jest.fn(),
      setCredits: jest.fn(),
      setTaskDetail: jest.fn(),
      selectTask: jest.fn(),
      addSavedReference: jest.fn(),
      videoPromptPreset: {
        title: 'Повторить видео',
        prompt: 'prompt',
        model: 'seedance_2',
      },
      setVideoPromptPreset: jest.fn(),
      refreshTasks: jest.fn(),
    } as ReturnType<typeof useApp>)

    render(<VideoTab />)

    expect(screen.getByTestId('regular-video-form')).toBeInTheDocument()
    expect(screen.queryByTestId('seedance25-form')).not.toBeInTheDocument()
  })
})
