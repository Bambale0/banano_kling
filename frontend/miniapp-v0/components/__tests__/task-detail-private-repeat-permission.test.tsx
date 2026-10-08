import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { TaskDetailPanel } from '@/components/task-detail-panel'
import { publishGeneration, unpublishGeneration } from '@/lib/api'
import { useApp } from '@/lib/app-context'
import type { FeedItem, TaskDetail } from '@/lib/types'

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
const mockedUnpublish = unpublishGeneration as jest.MockedFunction<typeof unpublishGeneration>
const updateTask = jest.fn()

function imageTask(overrides: Partial<TaskDetail> = {}): TaskDetail {
  return {
    task_id: 'image-task',
    type: 'image',
    model: 'banana_pro',
    model_label: 'Nano Banana Pro',
    aspect_ratio: '1:1',
    status: 'completed',
    result_url: 'https://example.test/result.jpg',
    created_at: '2026-10-03T00:00:00Z',
    prompt_preview: 'portrait',
    prompt: 'portrait',
    cost: 1,
    publication_reference_images: [
      'https://example.test/face.jpg',
      'https://example.test/outfit.jpg',
    ],
    publication_reference_image_indices: [1, 4],
    ...overrides,
  }
}

function videoTask(overrides: Partial<TaskDetail> = {}): TaskDetail {
  return {
    task_id: 'video-task',
    type: 'video',
    model: 'seedance_2_5',
    model_label: 'Seedance 2.5',
    aspect_ratio: '9:16',
    duration: 10,
    status: 'completed',
    result_url: 'https://example.test/result.mp4',
    created_at: '2026-10-08T00:00:00Z',
    prompt_preview: 'video',
    prompt: 'video',
    cost: 10,
    publication_reference_images: [
      'https://example.test/person.jpg',
    ],
    publication_reference_videos: [
      'https://example.test/motion.mp4',
    ],
    publication_reference_image_indices: [2],
    publication_reference_video_indices: [5],
    ...overrides,
  }
}

function useTask(taskDetail: TaskDetail, isTaskDetailOpen = true) {
  mockedUseApp.mockReturnValue({
    state: { user: { isAdmin: false } },
    taskDetail,
    isTaskDetailOpen,
    closeTaskDetail: jest.fn(),
    updateTask,
  } as unknown as ReturnType<typeof useApp>)
}

function openPublicationEditor() {
  fireEvent.click(screen.getByRole('button', { name: /^(Опубликовать|Настроить публикацию)$/ }))
}

function savePublication() {
  fireEvent.click(screen.getAllByRole('button', { name: /^(Опубликовать|Сохранить публикацию)$/ })[0])
}

describe('TaskDetailPanel private image-repeat permission', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockedUnpublish.mockReset().mockResolvedValue(undefined)
    jest.spyOn(window, 'confirm').mockReturnValue(true)
    mockedPublish.mockReset().mockResolvedValue({
      task_id: 'image-task',
      publication_scope: 'feed',
      feed_references_visible: false,
      feed_interactions_enabled: true,
    } as FeedItem)
    useTask(imageTask())
  })

  afterEach(() => jest.restoreAllMocks())

  it('lets a video owner privately authorize image and video references for repeats', async () => {
    mockedPublish.mockResolvedValueOnce({
      task_id: 'video-task',
      publication_scope: 'feed',
      feed_references_visible: false,
      feed_interactions_enabled: true,
    } as FeedItem)
    useTask(videoTask())
    render(<TaskDetailPanel />)
    openPublicationEditor()

    const repeatGroup = screen.getByRole('group', { name: 'Референсы для повторов' })
    expect(repeatGroup.textContent).toContain('фото и видео')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Видео-референс 1 для повторов' }))
    savePublication()

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('video-task', expect.objectContaining({
      referencesVisible: false,
      repeatReferenceImageIndices: [2],
      repeatReferenceVideoIndices: [5],
    }))
    expect(updateTask).toHaveBeenCalledWith('video-task', expect.objectContaining({
      feed_repeat_reference_selection: { images: [2], videos: [5] },
    }))
  })

  it('removes revoked video consent during refresh and resets drafts on task navigation', () => {
    const task = videoTask({ feed_repeat_reference_selection: { images: [2], videos: [5] } })
    useTask(task)
    const view = render(<TaskDetailPanel />)
    openPublicationEditor()
    expect(screen.getByRole('checkbox', { name: 'Видео-референс 1 для повторов' })).toHaveAttribute('aria-checked', 'true')
    useTask({ ...task, feed_repeat_reference_selection: { images: [2], videos: [] } })
    view.rerender(<TaskDetailPanel />)
    expect(screen.getByRole('checkbox', { name: 'Видео-референс 1 для повторов' })).toHaveAttribute('aria-checked', 'false')
    useTask(videoTask({ task_id: 'another-video' }))
    view.rerender(<TaskDetailPanel />)
    openPublicationEditor()
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' })).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByRole('checkbox', { name: 'Видео-референс 1 для повторов' })).toHaveAttribute('aria-checked', 'false')
  })

  it('defaults legacy tasks to no repeat permission even when references are public', async () => {
    useTask(imageTask({
      feed_references_visible: true,
      feed_reference_selection: { images: [1, 4], videos: [] },
    }))
    render(<TaskDetailPanel />)
    openPublicationEditor()

    expect(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }).getAttribute('aria-checked')).toBe('false')
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }).getAttribute('aria-checked')).toBe('false')
    savePublication()

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('image-task', expect.objectContaining({
      referencesVisible: true,
      referenceImageIndices: [1, 4],
      repeatReferenceImageIndices: [],
    }))
  })

  it('allows private repeats with selected source indices while public reference display stays off', async () => {
    render(<TaskDetailPanel />)
    openPublicationEditor()

    expect(screen.getByRole('heading', { name: 'Что показать в публикации' })).toBeTruthy()
    expect(screen.getByRole('group', { name: 'Референсы для повторов' }).textContent).toContain('их превью и ссылки не передаются')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }))
    savePublication()

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('image-task', expect.objectContaining({
      referencesVisible: false,
      referenceImageIndices: [1, 4],
      repeatReferenceImageIndices: [4],
    }))
    expect(updateTask).toHaveBeenCalledWith('image-task', expect.objectContaining({
      feed_references_visible: false,
      feed_repeat_reference_selection: { images: [4] },
    }))
  })

  it('keeps public display and repeat source selections independent', async () => {
    render(<TaskDetailPanel />)
    openPublicationEditor()
    fireEvent.click(screen.getByRole('button', { name: 'Рефы (2)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Исключить фото-референс 1' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }))
    savePublication()

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('image-task', expect.objectContaining({
      referencesVisible: true,
      referenceImageIndices: [4],
      repeatReferenceImageIndices: [1],
    }))
  })

  it('restores explicit owner consent and revokes it by saving an empty selection', async () => {
    useTask(imageTask({
      is_profile_visible: true,
      feed_repeat_reference_selection: { images: [4] },
      feed_reference_selection: { images: [1], videos: [] },
    }))
    render(<TaskDetailPanel />)
    openPublicationEditor()

    expect(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }).getAttribute('aria-checked')).toBe('false')
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }).getAttribute('aria-checked')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: 'Снять выбор' }))
    savePublication()

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('image-task', expect.objectContaining({
      referenceImageIndices: [1],
      repeatReferenceImageIndices: [],
    }))
    expect(updateTask).toHaveBeenCalledWith('image-task', expect.objectContaining({
      feed_repeat_reference_selection: { images: [] },
    }))
  })

  it('never shifts an unavailable saved source index onto another reference', async () => {
    useTask(imageTask({ feed_repeat_reference_selection: { images: [0, 4] } }))
    render(<TaskDetailPanel />)
    openPublicationEditor()

    expect(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }).getAttribute('aria-checked')).toBe('false')
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }).getAttribute('aria-checked')).toBe('true')
    savePublication()

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('image-task', expect.objectContaining({
      repeatReferenceImageIndices: [4],
    }))
  })

  it('does not carry draft permission into another task or a reopened panel', () => {
    const task = imageTask()
    useTask(task)
    const { rerender } = render(<TaskDetailPanel />)
    openPublicationEditor()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }))

    useTask(task, false)
    rerender(<TaskDetailPanel />)
    useTask(task)
    rerender(<TaskDetailPanel />)
    expect(screen.queryByRole('group', { name: 'Референсы для повторов' })).toBeNull()
    openPublicationEditor()
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }).getAttribute('aria-checked')).toBe('false')

    fireEvent.click(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }))
    useTask(imageTask({ task_id: 'another-image-task' }))
    rerender(<TaskDetailPanel />)
    openPublicationEditor()
    expect(screen.getAllByRole('checkbox').every((checkbox) => checkbox.getAttribute('aria-checked') === 'false')).toBe(true)
    expect(mockedPublish).not.toHaveBeenCalled()
  })

  it('does not publish or update consent after cancelled confirmation', () => {
    jest.spyOn(window, 'confirm').mockReturnValue(false)
    render(<TaskDetailPanel />)
    openPublicationEditor()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }))
    savePublication()

    expect(mockedPublish).not.toHaveBeenCalled()
    expect(updateTask).not.toHaveBeenCalled()
  })

  it('preserves the draft after a failed save and allows retry without changing consent', async () => {
    mockedPublish.mockRejectedValueOnce(new Error('Network error'))
    render(<TaskDetailPanel />)
    openPublicationEditor()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }))
    savePublication()

    await waitFor(() => expect((screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }) as HTMLButtonElement).disabled).toBe(false))
    expect(updateTask).not.toHaveBeenCalled()
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }).getAttribute('aria-checked')).toBe('true')
    savePublication()

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(2))
    expect(mockedPublish).toHaveBeenNthCalledWith(2, 'image-task', expect.objectContaining({
      repeatReferenceImageIndices: [4],
    }))
  })

  it('locks repeat selection and prevents duplicate submissions while saving', async () => {
    let resolvePublish: ((result: FeedItem) => void) | undefined
    mockedPublish.mockImplementationOnce(() => new Promise((resolve) => { resolvePublish = resolve }))
    render(<TaskDetailPanel />)
    openPublicationEditor()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }))
    savePublication()

    expect((screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Снять выбор' }) as HTMLButtonElement).disabled).toBe(true)
    savePublication()
    expect(mockedPublish).toHaveBeenCalledTimes(1)

    resolvePublish?.({ publication_scope: 'feed' } as FeedItem)
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1))
  })

  it('shows an empty state and sends no implicit permission when references are unavailable', async () => {
    useTask(imageTask({
      publication_reference_images: [],
      publication_reference_image_indices: [],
      feed_repeat_reference_selection: { images: [4] },
    }))
    render(<TaskDetailPanel />)
    openPublicationEditor()

    expect(screen.getByText('Нет доступных фото-референсов.')).toBeTruthy()
    expect(screen.queryByRole('checkbox')).toBeNull()
    savePublication()
    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('image-task', expect.objectContaining({
      repeatReferenceImageIndices: [],
    }))
  })

  it('does not treat legacy public video references as private repeat consent', async () => {
    useTask(videoTask({
      feed_references_visible: true,
      feed_reference_selection: { images: [2], videos: [5] },
    }))
    render(<TaskDetailPanel />)
    openPublicationEditor()

    expect(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }).getAttribute('aria-checked')).toBe('false')
    expect(screen.getByRole('checkbox', { name: 'Видео-референс 1 для повторов' }).getAttribute('aria-checked')).toBe('false')
    savePublication()
    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('video-task', expect.objectContaining({
      repeatReferenceImageIndices: [],
      repeatReferenceVideoIndices: [],
    }))
  })

  it('clears saved and draft consent on unpublish so republishing requires explicit reselection', async () => {
    const publishedTask = imageTask({
      is_public_feed: true,
      is_profile_visible: true,
      feed_repeat_reference_selection: { images: [4] },
    })
    useTask(publishedTask)
    const { rerender } = render(<TaskDetailPanel />)
    openPublicationEditor()
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }).getAttribute('aria-checked')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: 'Убрать публикацию' }))

    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1))
    expect(updateTask).toHaveBeenCalledWith('image-task', expect.objectContaining({
      is_public_feed: false,
      feed_repeat_reference_selection: { images: [] },
    }))
    useTask({ ...publishedTask, ...updateTask.mock.calls[0][1] })
    rerender(<TaskDetailPanel />)
    openPublicationEditor()
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }).getAttribute('aria-checked')).toBe('false')
    savePublication()

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('image-task', expect.objectContaining({
      repeatReferenceImageIndices: [],
    }))
  })

  it('keeps consent unchanged if unpublish fails', async () => {
    mockedUnpublish.mockRejectedValueOnce(new Error('Network error'))
    useTask(imageTask({
      is_profile_visible: true,
      feed_repeat_reference_selection: { images: [4] },
    }))
    render(<TaskDetailPanel />)
    openPublicationEditor()
    fireEvent.click(screen.getByRole('button', { name: 'Убрать публикацию' }))

    await waitFor(() => expect((screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }) as HTMLButtonElement).disabled).toBe(false))
    expect(updateTask).not.toHaveBeenCalled()
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }).getAttribute('aria-checked')).toBe('true')
  })

  it('keeps the open draft across equivalent same-task polling snapshots', async () => {
    const task = imageTask({
      feed_reference_selection: { images: [1, 4], videos: [] },
      feed_repeat_reference_selection: { images: [] },
    })
    useTask(task)
    const { rerender } = render(<TaskDetailPanel />)
    openPublicationEditor()
    fireEvent.click(screen.getByRole('button', { name: 'Prompt' }))
    fireEvent.click(screen.getByRole('button', { name: 'Рефы (2)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Исключить фото-референс 1' }))
    fireEvent.click(screen.getByRole('button', { name: 'Blur' }))
    fireEvent.click(screen.getByRole('button', { name: 'Только профиль' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }))

    useTask(JSON.parse(JSON.stringify(task)) as TaskDetail)
    rerender(<TaskDetailPanel />)
    expect(screen.getByRole('group', { name: 'Референсы для повторов' })).toBeTruthy()
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }).getAttribute('aria-checked')).toBe('true')
    savePublication()

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('image-task', expect.objectContaining({
      promptVisible: true,
      referencesVisible: true,
      referenceImageIndices: [4],
      repeatReferenceImageIndices: [4],
      blurred: true,
      publicationScope: 'profile',
    }))
  })

  it('preserves explicit choices when more source details arrive and never preselects newly available refs', async () => {
    useTask(imageTask({
      publication_reference_images: ['https://example.test/face.jpg'],
      publication_reference_image_indices: [1],
    }))
    const { rerender } = render(<TaskDetailPanel />)
    openPublicationEditor()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }))

    useTask(imageTask())
    rerender(<TaskDetailPanel />)
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }).getAttribute('aria-checked')).toBe('true')
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }).getAttribute('aria-checked')).toBe('false')
    savePublication()

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('image-task', expect.objectContaining({ repeatReferenceImageIndices: [1] }))
  })

  it('drops unavailable selected refs from an open draft without closing it', async () => {
    useTask(imageTask())
    const { rerender } = render(<TaskDetailPanel />)
    openPublicationEditor()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }))

    useTask(imageTask({
      publication_reference_images: ['https://example.test/outfit.jpg'],
      publication_reference_image_indices: [4],
    }))
    rerender(<TaskDetailPanel />)
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }).getAttribute('aria-checked')).toBe('false')
    savePublication()

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('image-task', expect.objectContaining({ repeatReferenceImageIndices: [] }))
  })

  it('honors server-side revocation without losing other explicit draft choices', async () => {
    useTask(imageTask({ feed_repeat_reference_selection: { images: [1] } }))
    const { rerender } = render(<TaskDetailPanel />)
    openPublicationEditor()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }))

    useTask(imageTask({ feed_repeat_reference_selection: { images: [] } }))
    rerender(<TaskDetailPanel />)
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }).getAttribute('aria-checked')).toBe('false')
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' }).getAttribute('aria-checked')).toBe('true')
    savePublication()

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('image-task', expect.objectContaining({ repeatReferenceImageIndices: [4] }))
  })
})
