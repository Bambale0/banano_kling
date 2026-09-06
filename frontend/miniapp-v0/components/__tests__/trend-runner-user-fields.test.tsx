import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { TrendRunnerDialog } from '@/components/trend-runner-dialog'
import { useApp } from '@/lib/app-context'
import { uploadFile } from '@/lib/api'
import { runTrend } from '@/lib/trend-api'
import type { PromptItem } from '@/lib/types'

jest.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}))

jest.mock('@/lib/app-context', () => ({
  useApp: jest.fn(),
}))

jest.mock('@/lib/api', () => ({
  uploadFile: jest.fn(),
}))

jest.mock('@/lib/trend-api', () => ({
  runTrend: jest.fn(),
  runPinterestRepeatTrend: jest.fn(),
}))

const mockedUseApp = useApp as jest.MockedFunction<typeof useApp>
const mockedUploadFile = uploadFile as jest.MockedFunction<typeof uploadFile>
const mockedRunTrend = runTrend as jest.MockedFunction<typeof runTrend>

const trend: PromptItem = {
  id: 42,
  title: 'День рождения',
  description: 'Персональный birthday-ролик',
  prompt_text: '',
  category: 'video',
  tags: ['trend', 'trend-video'],
  uses_count: 0,
  likes: 0,
  preview_url: null,
  model: 'seedance_2',
  author_id: 1,
  status: 'approved',
  generation_settings: {
    kind: 'video',
    user_input: 'photo',
    model: 'seedance_2',
    ratio: '9:16',
    scenario: 'imgtxt',
    duration: 5,
    reference_count: 1,
    user_fields: [
      {
        key: 'Возраст',
        label: 'Возраст',
        type: 'number',
        required: true,
        min: 1,
        max: 120,
        placeholder: '28',
      },
    ],
  },
}

describe('TrendRunnerDialog user fields', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: jest.fn(() => 'blob:preview'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: jest.fn(),
    })
    mockedUseApp.mockReturnValue({
      addTask: jest.fn(),
      setCredits: jest.fn(),
      setTaskDetail: jest.fn(),
      selectTask: jest.fn(),
      addSavedReference: jest.fn(),
    } as unknown as ReturnType<typeof useApp>)
    mockedUploadFile.mockResolvedValue({
      id: 'ref-1',
      name: 'portrait.jpg',
      url: 'https://example.test/portrait.jpg',
      type: 'image',
      size: 123,
    })
    mockedRunTrend.mockResolvedValue({
      task: {
        task_id: 'trend-task-1',
        type: 'video',
        model: 'seedance_2',
        model_label: 'Seedance 2.0',
        aspect_ratio: '9:16',
        status: 'pending',
        created_at: new Date(0).toISOString(),
        prompt_preview: '',
        cost: 4,
        duration: 5,
        prompt_hidden: true,
        prompt_actions_allowed: false,
      },
      credits: 96,
    })
  })

  it('collects a configured age without revealing the hidden prompt', async () => {
    const { container } = render(
      <TrendRunnerDialog trend={trend} open onOpenChange={jest.fn()} />,
    )

    const ageInput = screen.getByPlaceholderText('28')
    expect(screen.getByText('Возраст *')).toBeInTheDocument()
    expect(screen.getByText(/Скрытый prompt останется скрытым/)).toBeInTheDocument()

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(fileInput, {
      target: { files: [new File(['image'], 'portrait.jpg', { type: 'image/jpeg' })] },
    })
    await waitFor(() => expect(mockedUploadFile).toHaveBeenCalledTimes(1))

    fireEvent.change(ageInput, { target: { value: '28' } })
    const generateButton = screen.getByRole('button', { name: /Сгенерировать/ })
    await waitFor(() => expect(generateButton).toBeEnabled())
    fireEvent.click(generateButton)

    await waitFor(() =>
      expect(mockedRunTrend).toHaveBeenCalledWith(
        42,
        ['https://example.test/portrait.jpg'],
        { Возраст: '28' },
      ),
    )
    expect(screen.queryByText(/Birthday scene|Happy birthday/)).not.toBeInTheDocument()
  })
})
