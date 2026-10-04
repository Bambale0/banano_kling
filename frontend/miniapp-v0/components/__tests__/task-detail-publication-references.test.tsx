import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { TaskDetailPanel } from '@/components/task-detail-panel'
import { publishGeneration } from '@/lib/api'
import { useApp } from '@/lib/app-context'

jest.mock('@/lib/api', () => ({
  publishGeneration: jest.fn(),
  removeGenerationPrompt: jest.fn(),
  saveGenerationPrompt: jest.fn(),
  unpublishGeneration: jest.fn(),
}))

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/feed-events', () => ({ notifyFeedChanged: jest.fn() }))
jest.mock('@/components/seedance-trend-publisher', () => ({ SeedanceTrendPublisher: () => null }))

const mockedUseApp = useApp as jest.MockedFunction<typeof useApp>
const mockedPublish = publishGeneration as jest.MockedFunction<typeof publishGeneration>

describe('TaskDetailPanel publication references', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    jest.spyOn(window, 'confirm').mockReturnValue(true)
    mockedPublish.mockResolvedValue({
      id: 1,
      task_id: 'seedance-task',
      model: 'seedance_2_5',
      gen_type: 'video',
      result_url: 'https://example.test/result.mp4',
      preview_url: 'https://example.test/result.mp4',
      result_urls: ['https://example.test/result.mp4'],
      prompt: '',
      likes_count: 0,
      shares_count: 0,
      aspect_ratio: '16:9',
      references_count: 2,
      author: 'Test',
      is_mine: true,
      remixes: 0,
      score: 0,
      created_at: '2026-10-03T00:00:00Z',
      prompt_hidden: true,
      publication_scope: 'feed',
      feed_interactions_enabled: true,
    })
    mockedUseApp.mockReturnValue({
      state: { user: { isAdmin: false } },
      taskDetail: {
        task_id: 'seedance-task',
        type: 'video',
        model: 'seedance_2_5',
        model_label: 'Seedance 2.5',
        aspect_ratio: '16:9',
        status: 'completed',
        result_url: 'https://example.test/result.mp4',
        created_at: '2026-10-03T00:00:00Z',
        prompt_preview: 'look',
        prompt: 'look',
        cost: 0,
        request_data: {
          reference_images: [
            'https://example.test/face.jpg',
            'https://example.test/outfit.jpg',
          ],
          v_reference_videos: ['https://example.test/motion.mp4'],
        },
      },
      isTaskDetailOpen: true,
      closeTaskDetail: jest.fn(),
      updateTask: jest.fn(),
    } as unknown as ReturnType<typeof useApp>)
  })

  it('lets a Seedance author inspect refs, then exclude their face from publication', async () => {
    render(<TaskDetailPanel />)

    expect(screen.getByRole('link', { name: 'Открыть фото-референс 1' })).toHaveAttribute('href', 'https://example.test/face.jpg')
    expect(screen.getByLabelText('Видео-референс 1')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Открыть видео-референс 1' })).toHaveAttribute('href', 'https://example.test/motion.mp4')

    fireEvent.click(screen.getByRole('button', { name: /^Опубликовать$/i }))
    fireEvent.click(screen.getByRole('button', { name: /Рефы \(3\)/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Исключить фото-референс 1' }))
    fireEvent.click(screen.getAllByRole('button', { name: /^Опубликовать$/i })[0])

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('seedance-task', expect.objectContaining({
      referencesVisible: true,
      referenceImageIndices: [1],
      referenceVideoIndices: [0],
    }))
  })
})
