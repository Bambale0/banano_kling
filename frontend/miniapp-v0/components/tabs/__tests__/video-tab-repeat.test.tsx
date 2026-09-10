import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'

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
  VideoGeneratorForm: ({
    models,
    onModelSelected,
    promptPreset,
    onPromptPresetConsumed,
  }: {
    models: Array<{ id: string }>
    onModelSelected?: (modelId: string) => void
    promptPreset?: Record<string, unknown> | null
    onPromptPresetConsumed?: () => void
  }) => {
    const React = jest.requireActual<typeof import('react')>('react')
    React.useEffect(() => {
      if (promptPreset) onPromptPresetConsumed?.()
    }, [onPromptPresetConsumed, promptPreset])

    return (
      <div data-testid="regular-video-form">
        {models.map((model) => (
          <button key={model.id} type="button" onClick={() => onModelSelected?.(model.id)}>
            select-{model.id}
          </button>
        ))}
      </div>
    )
  },
}))

jest.mock('@/components/forms/seedance25-public-form', () => ({
  Seedance25PublicForm: () => <div data-testid="seedance25-form">seedance form</div>,
}))

jest.mock('@/components/result-card', () => ({
  ResultCard: () => <div data-testid="result-card">result</div>,
}))

const mockedUseApp = useApp as jest.MockedFunction<typeof useApp>

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

function mockApp(initialVideoPromptPreset: Record<string, unknown> | null) {
  mockedUseApp.mockImplementation(() => {
    const React = jest.requireActual<typeof import('react')>('react')
    const [videoPromptPreset, setVideoPromptPreset] = React.useState(initialVideoPromptPreset)

    return {
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
      setVideoPromptPreset,
      refreshTasks: jest.fn(),
    } as unknown as ReturnType<typeof useApp>
  })
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

  it('does not leave the catalog when Seedance 2.5 is selected inside the generic model picker', () => {
    mockApp({
      title: 'Обычное видео',
      prompt: 'prompt',
      model: 'seedance_2',
    })

    render(<VideoTab />)

    const seedanceCatalogOption = screen.getByRole('button', { name: 'select-seedance_2_5' })
    fireEvent.click(seedanceCatalogOption)

    expect(screen.getByTestId('regular-video-form')).toBeInTheDocument()
    expect(screen.queryByTestId('seedance25-form')).not.toBeInTheDocument()
  })

  it('keeps a Seedance 2.5 repeat in the source-aware form after the preset is consumed', () => {
    mockApp({
      title: 'Повторить Seedance 2.5',
      prompt: '',
      model: 'seedance_2_5',
      sourceFeedGenId: 42,
      promptHidden: true,
    })

    render(<VideoTab />)

    expect(screen.getByTestId('regular-video-form')).toBeInTheDocument()
    expect(screen.queryByTestId('seedance25-form')).not.toBeInTheDocument()

    const seedanceButton = screen.getByRole('button', { name: /NEW Seedance 2\.5/i })
    const catalogButton = screen.getByRole('button', { name: /Каталог Другие модели/i })
    expect(seedanceButton.className).toContain('border-gold/45')
    expect(catalogButton.className).not.toContain('border-border bg-secondary')

    fireEvent.click(seedanceButton)
    expect(screen.getByTestId('regular-video-form')).toBeInTheDocument()
    expect(screen.queryByTestId('seedance25-form')).not.toBeInTheDocument()
  })

  it('opens a fresh dedicated Seedance form only after the user explicitly leaves repeat mode', () => {
    mockApp({
      title: 'Повторить Seedance 2.5',
      prompt: '',
      model: 'seedance_2_5',
      sourceFeedGenId: 42,
      promptHidden: true,
    })

    render(<VideoTab />)

    fireEvent.click(screen.getByRole('button', { name: /Каталог Другие модели/i }))
    expect(screen.getByTestId('regular-video-form')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /NEW Seedance 2\.5/i }))
    expect(screen.getByTestId('seedance25-form')).toBeInTheDocument()
    expect(screen.queryByTestId('regular-video-form')).not.toBeInTheDocument()
  })
})
