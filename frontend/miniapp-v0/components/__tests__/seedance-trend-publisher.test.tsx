import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { SeedanceTrendPublisher } from '@/components/seedance-trend-publisher'
import {
  fetchSeedanceTrendSource,
  publishSeedanceTrend,
} from '@/lib/seedance-trend-admin-api'
import type { TaskDetail } from '@/lib/types'

jest.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}))

jest.mock('@/lib/seedance-trend-admin-api', () => ({
  fetchSeedanceTrendSource: jest.fn(),
  publishSeedanceTrend: jest.fn(),
}))

const mockedFetchSource = fetchSeedanceTrendSource as jest.MockedFunction<typeof fetchSeedanceTrendSource>
const mockedPublish = publishSeedanceTrend as jest.MockedFunction<typeof publishSeedanceTrend>

const task: TaskDetail = {
  task_id: 'seedance-source-task',
  type: 'video',
  model: 'seedance_2_5',
  model_label: 'Seedance 2.5',
  aspect_ratio: 'adaptive',
  status: 'completed',
  result_url: 'https://example.test/result.mp4',
  created_at: new Date(0).toISOString(),
  prompt_preview: 'private prompt',
  prompt: '@Image1 wears @Image2 and follows @Video1',
  cost: 20,
  duration: 12,
}

describe('SeedanceTrendPublisher', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockedFetchSource.mockResolvedValue({
      task_id: task.task_id,
      generation_id: 501,
      model: 'seedance_2_5',
      duration: 12,
      aspect_ratio: 'adaptive',
      prompt: task.prompt,
      result_url: task.result_url as string,
      references: {
        images: [
          { index: 1, preview_url: 'https://example.test/creator.jpg', default_action: 'replace_with_user' },
          { index: 2, preview_url: 'https://example.test/dress.jpg', default_action: 'keep_hidden' },
        ],
        videos: [
          { index: 1, preview_url: 'https://example.test/motion.mp4', default_action: 'keep_hidden' },
        ],
        audios: [],
      },
    })
    mockedPublish.mockResolvedValue({
      id: 77,
      title: 'Published trend',
      description: '',
      prompt_text: '',
      category: 'video',
      tags: ['trend', 'trend-video'],
      uses_count: 0,
      likes: 0,
      model: null,
      author_id: 1,
      status: 'approved',
      generation_settings: {
        kind: 'video',
        user_input: 'photo',
        model: '',
        ratio: 'adaptive',
        reference_count: 1,
        reference_labels: ['ВАШЕ ЛИЦО'],
        automatic_hidden_references: true,
      },
    })
  })

  it('excludes creator identity and lets the user replace a video reference', async () => {
    render(<SeedanceTrendPublisher task={task} />)

    fireEvent.click(screen.getByRole('button', { name: /Сделать Seedance-трендом/i }))
    await waitFor(() => expect(mockedFetchSource).toHaveBeenCalledWith(task.task_id))
    expect(await screen.findByText('Исходный @Image1')).toBeInTheDocument()
    expect(screen.getByText('Исходный @Image2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /@Video1 · скрыт, без замены/i })).toBeInTheDocument()
    expect(screen.getByText(/Оригиналы не показываются при повторе/)).toBeInTheDocument()
    const replaceButtons = screen.getAllByRole('button', { name: /разрешить замену/i })
    fireEvent.click(replaceButtons[replaceButtons.length - 1])
    expect(screen.getByRole('button', { name: /^Скрыт, пользователь заменяет$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /@Video1 · закрепить без замены/i })).toBeInTheDocument()

    const publishButton = screen.getByRole('button', { name: /^Опубликовать тренд$/i })
    await waitFor(() => expect(publishButton).toBeEnabled())
    fireEvent.click(publishButton)

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith(expect.objectContaining({
      taskId: task.task_id,
      identityImageIndex: 1,
      fixedImageIndices: [2],
      fixedVideoIndices: [],
      fixedAudioIndices: [],
      replaceableImageIndices: [],
      replaceableVideoIndices: [1],
      replaceableAudioIndices: [],
    }))
    expect(JSON.stringify(mockedPublish.mock.calls[0][0])).not.toContain('creator.jpg')
    expect(JSON.stringify(mockedPublish.mock.calls[0][0])).not.toContain('dress.jpg')
    expect(JSON.stringify(mockedPublish.mock.calls[0][0])).not.toContain('motion.mp4')
  })

  it('keeps fixed refs private when replacement is not enabled', async () => {
    render(<SeedanceTrendPublisher task={task} />)
    fireEvent.click(screen.getByRole('button', { name: /Сделать Seedance-трендом/i }))
    await screen.findByText('Исходный @Image2')
    const publishButton = screen.getByRole('button', { name: /^Опубликовать тренд$/i })
    await waitFor(() => expect(publishButton).toBeEnabled())
    fireEvent.click(publishButton)
    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith(expect.objectContaining({
      fixedImageIndices: [2], fixedVideoIndices: [1],
      replaceableImageIndices: [], replaceableVideoIndices: [],
    }))
  })

  it('switches a hidden image between replaceable and fixed without overlapping slots', async () => {
    render(<SeedanceTrendPublisher task={task} />)
    fireEvent.click(screen.getByRole('button', { name: /Сделать Seedance-трендом/i }))
    await screen.findByText('Исходный @Image2')
    const controls = screen.getAllByRole('button', { name: /скрыть и разрешить замену/i })
    fireEvent.click(controls.find(button => !button.hasAttribute('disabled'))!)
    expect(screen.getByRole('button', { name: /^Скрыт, пользователь заменяет$/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^Закрепить без замены$/i }))
    const publishButton = screen.getByRole('button', { name: /^Опубликовать тренд$/i })
    fireEvent.click(publishButton)
    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith(expect.objectContaining({
      fixedImageIndices: [2], replaceableImageIndices: [],
    }))
  })
})
