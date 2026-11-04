import '@testing-library/jest-dom'
import { useState } from 'react'
import type { TaskDetail } from '@/lib/types'
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

  it('normalizes local upload refs to the Mini App origin for WebView previews', () => {
    mockedUseApp.mockReturnValue({
      state: { user: { isAdmin: false } },
      taskDetail: {
        task_id: 'seedance-task',
        type: 'video',
        model: 'seedance_2',
        model_label: 'Seedance 2',
        aspect_ratio: '16:9',
        status: 'completed',
        result_url: 'https://example.test/result.mp4',
        created_at: '2026-10-04T11:49:55Z',
        prompt_preview: 'look',
        prompt: 'look',
        cost: 0,
        publication_reference_images: [
          'https://tanyapi.chillcreative.ru/uploads/refs/image/8166443943/202610/ref.png',
        ],
        publication_reference_videos: [
          'https://tanyapi.chillcreative.ru/uploads/refs/video/8166443943/202610/ref.mp4',
        ],
      },
      isTaskDetailOpen: true,
      closeTaskDetail: jest.fn(),
      updateTask: jest.fn(),
    } as unknown as ReturnType<typeof useApp>)

    render(<TaskDetailPanel />)

    const expectedImage = `${window.location.origin}/uploads/refs/image/8166443943/202610/ref.png`
    const expectedVideo = `${window.location.origin}/uploads/refs/video/8166443943/202610/ref.mp4`
    const imageLink = screen.getByRole('link', { name: 'Открыть фото-референс 1' })
    expect(imageLink).toHaveAttribute('href', expectedImage)
    expect(imageLink.querySelector('img')).toHaveAttribute('src', expectedImage)
    expect(screen.getByRole('link', { name: 'Открыть видео-референс 1' })).toHaveAttribute('href', expectedVideo)
    expect(screen.getByLabelText('Видео-референс 1')).toHaveAttribute('src', expect.stringContaining(expectedVideo))
  })

  it('shows the server-authorized editor and publishes exact repeat field bindings', async () => {
    const context = mockedUseApp.getMockImplementation()!()
    mockedUseApp.mockReturnValue({ ...context, taskDetail: {
      ...context.taskDetail!,
      repeat_personalization_editor_enabled: true,
      repeat_user_fields: [{
        key: 'clothes', label: 'Одежда', original_value: 'blue coat',
        type: 'text', required: true, max_length: 160, choices: ['red dress', 'black suit'],
      }],
    } } as ReturnType<typeof useApp>)

    render(<TaskDetailPanel />)
    fireEvent.click(screen.getByRole('button', { name: /^Опубликовать$/i }))
    expect(screen.getByText('Что можно изменить при повторе')).toBeInTheDocument()
    expect(screen.getByLabelText('Название параметра 1')).toHaveValue('Одежда')
    expect(screen.getByLabelText('Исходный фрагмент 1')).toHaveValue('blue coat')
    expect(screen.getByLabelText('Варианты параметра 1')).toHaveValue('red dress, black suit')
    fireEvent.click(screen.getAllByRole('button', { name: /^Опубликовать$/i })[0])

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledWith('seedance-task', expect.objectContaining({
      repeatUserFields: [expect.objectContaining({
        key: 'clothes', label: 'Одежда', original_value: 'blue coat',
        choices: ['red dress', 'black suit'],
      })],
    })))
  })

  it('publishes image-backed repeat groups by name without an original prompt fragment', async () => {
    const context = mockedUseApp.getMockImplementation()!()
    mockedUseApp.mockReturnValue({ ...context, taskDetail: {
      ...context.taskDetail!,
      repeat_personalization_editor_enabled: true,
      repeat_image_choices_supported: true,
      repeat_user_fields: [{
        key: 'outfit', label: 'Образ', original_value: 'not found in hidden prompt',
        type: 'text', required: true, max_length: 160,
        image_choices: [{
          id: 'dress', label: 'Платье',
          image_url: 'https://neuromixbot.com/uploads/repeat-choices/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg',
        }],
      }],
    } } as ReturnType<typeof useApp>)

    render(<TaskDetailPanel />)
    fireEvent.click(screen.getByRole('button', { name: /^Опубликовать$/i }))
    expect(screen.getByLabelText('Название параметра 1')).toHaveValue('Образ')
    expect(screen.queryByLabelText('Исходный фрагмент 1')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Варианты параметра 1')).not.toBeInTheDocument()
    expect(screen.getByText('Варианты с изображениями')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: /^Опубликовать$/i })[0])

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledWith('seedance-task', expect.objectContaining({
      repeatUserFields: [expect.objectContaining({
        key: 'outfit', label: 'Образ', original_value: '',
        image_choices: [expect.objectContaining({ id: 'dress' })],
      })],
    })))
  })

  it.each(['image', 'video'])('lets a non-admin publish a private %s result without exporting its recipe', async (type) => {
    const context = mockedUseApp.getMockImplementation()!()
    mockedUseApp.mockReturnValue({ ...context, taskDetail: {
      ...context.taskDetail!, type, prompt: '', prompt_hidden: true,
      prompt_actions_allowed: false, publication_reference_images: [],
      publication_reference_videos: [], request_data: {},
    } } as ReturnType<typeof useApp>)
    render(<TaskDetailPanel />)
    expect(screen.getByText('Описание автора скрыто. Работу можно опубликовать и повторить.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^Опубликовать$/i }))
    fireEvent.click(screen.getAllByRole('button', { name: /^Опубликовать$/i })[0])
    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
    expect(mockedPublish).toHaveBeenCalledWith('seedance-task', expect.objectContaining({ promptVisible: false }))
  })

  it('keeps saved personalization after closing and reopening the editor', async () => {
    const context = mockedUseApp.getMockImplementation()!()
    function Harness() {
      const [detail, setDetail] = useState<TaskDetail>({ ...context.taskDetail!,
        repeat_personalization_editor_enabled: true,
        repeat_user_fields: [{ key: 'clothes', label: 'Одежда', original_value: 'blue coat',
          type: 'text' as const, required: true, max_length: 160, choices: ['red dress'] }],
      })
      mockedUseApp.mockReturnValue({ ...context, taskDetail: detail,
        updateTask: (_id, patch) => setDetail(old => ({ ...old, ...patch })),
      } as ReturnType<typeof useApp>)
      return <TaskDetailPanel />
    }
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: /^Опубликовать$/i }))
    fireEvent.change(screen.getByLabelText('Варианты параметра 1'), { target: { value: 'black suit' } })
    fireEvent.click(screen.getAllByRole('button', { name: /^Опубликовать$/i })[0])
    await waitFor(() => expect(screen.queryByLabelText('Варианты параметра 1')).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Настроить публикацию' }))
    expect(screen.getByLabelText('Варианты параметра 1')).toHaveValue('black suit')
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить публикацию' }))
    await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(2))
    expect(mockedPublish.mock.calls[1][1]?.repeatUserFields?.[0].choices).toEqual(['black suit'])
    await waitFor(() => expect(screen.queryByLabelText('Варианты параметра 1')).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Настроить публикацию' }))
    fireEvent.click(screen.getByRole('button', { name: 'Убрать публикацию' }))
    await waitFor(() => expect(screen.queryByLabelText('Варианты параметра 1')).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /^Опубликовать$/i }))
    expect(screen.queryByLabelText('Варианты параметра 1')).not.toBeInTheDocument()

  })


  it('saves real source image ordinal when catalog photo options have gaps', async () => {
    const context = mockedUseApp.getMockImplementation()!()
    mockedUseApp.mockReturnValue({ ...context, taskDetail: {
      ...context.taskDetail!,
      publication_reference_images: [
        'https://example.test/source-one.jpg',
        'https://example.test/source-four.jpg',
      ],
      publication_reference_image_indices: [1, 4],
      repeat_personalization_editor_enabled: true,
      repeat_image_choices_supported: true,
      repeat_user_fields: [{
        key: 'car', label: 'Машина', type: 'text', required: true,
        image_choices: [{
          id: 'car', label: 'Машина',
          image_url: 'https://neuromixbot.com/uploads/repeat-choices/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg',
        }],
      }],
    } } as ReturnType<typeof useApp>)

    render(<TaskDetailPanel />)
    fireEvent.click(screen.getByRole('button', { name: /^Опубликовать$/i }))
    const sourceSelector = screen.getByRole('combobox', { name: 'Фото для варианта Машина' })
    const options = Array.from(sourceSelector.querySelectorAll('option')).map(option => option.value)
    expect(options).toEqual(['', '1', '4'])
    fireEvent.change(sourceSelector, { target: { value: '4' } })
    fireEvent.click(screen.getAllByRole('button', { name: /^Опубликовать$/i })[0])

    await waitFor(() => expect(mockedPublish).toHaveBeenCalledWith('seedance-task', expect.objectContaining({
      repeatUserFields: [expect.objectContaining({ key: 'car', image_slot_index: 4 })],
    })))
  })

  it('makes a catalog replacement exclusive with retained originals and other groups', async () => {
    const context = mockedUseApp.getMockImplementation()!()
    mockedUseApp.mockReturnValue({ ...context, taskDetail: {
      ...context.taskDetail!,
      publication_reference_images: ['https://example.test/face.jpg', 'https://example.test/car.jpg', 'https://example.test/outfit.jpg'],
      publication_reference_image_indices: [0, 1, 2],
      feed_repeat_reference_selection: { images: [1], videos: [] },
      repeat_personalization_editor_enabled: true,
      repeat_image_choices_supported: true,
      repeat_user_fields: [
        { key: 'car', label: 'Машина', type: 'text', required: true,
          image_choices: [{ id: 'car', label: 'Машина', image_url: 'https://example.test/car-choice.jpg' }] },
        { key: 'outfit', label: 'Одежда', type: 'text', required: true, image_slot_index: 2,
          image_choices: [{ id: 'outfit', label: 'Одежда', image_url: 'https://example.test/outfit-choice.jpg' }] },
      ],
    } } as ReturnType<typeof useApp>)
    render(<TaskDetailPanel />)
    fireEvent.click(screen.getByRole('button', { name: /^Опубликовать$/i }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Фото для варианта Машина' }), { target: { value: '1' } })
    const outfit = screen.getByRole('combobox', { name: 'Фото для варианта Одежда' })
    expect(outfit.querySelector('option[value="1"]')).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' })).not.toBeDisabled()
    fireEvent.click(screen.getAllByRole('button', { name: /^Опубликовать$/i })[0])
    await waitFor(() => expect(mockedPublish).toHaveBeenCalledWith('seedance-task', expect.objectContaining({
      repeatReferenceImageIndices: [],
      repeatUserFields: [
        expect.objectContaining({ key: 'car', image_slot_index: 1 }),
        expect.objectContaining({ key: 'outfit', image_slot_index: 2 }),
      ],
    })))
  })

})
