import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VkNativeCommentComposer } from '../vk-native-comment-composer'
import { postVkPublicFeedComment } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  postVkPublicFeedComment: jest.fn(),
}))

beforeEach(() => {
  jest.resetAllMocks()
})

test('VK-only participant can write under shared public feed without Telegram account', async () => {
  const onPosted = jest.fn()
  jest.mocked(postVkPublicFeedComment).mockResolvedValue({
    ok: true,
    comments_count: 3,
    comment: {
      id: 'vk:11', gen_id: 41, author: 'Участник ВКонтакте',
      text: 'Из ВК', created_at: '2026-11-14', is_mine: true,
    },
  })
  render(<VkNativeCommentComposer feedGenId={41} onPosted={onPosted} />)
  fireEvent.change(screen.getByRole('textbox', { name: 'Новый комментарий' }), { target: { value: 'Из ВК' } })
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать комментарий' }))
  await waitFor(() => expect(onPosted).toHaveBeenCalledTimes(1))
  expect(jest.mocked(postVkPublicFeedComment)).toHaveBeenCalledTimes(1)
  const [feedGenId, comment, key] = jest.mocked(postVkPublicFeedComment).mock.calls[0]
  expect(feedGenId).toBe(41)
  expect(comment).toBe('Из ВК')
  expect(key).toMatch(/^vk_comment_[0-9a-f]{32}$/)
  expect(screen.getByRole('textbox', { name: 'Новый комментарий' })).toHaveValue('')
})

test('ambiguous VK POST preserves idempotency key and comment across manual retries', async () => {
  const onPosted = jest.fn()
  jest.mocked(postVkPublicFeedComment).mockRejectedValueOnce(new Error('Сеть недоступна'))
    .mockResolvedValueOnce({
      ok: true, comments_count: 1,
      comment: { id: 'vk:12', gen_id: 41, author: 'Участник ВКонтакте',
        text: 'Без дублей', created_at: '2026-11-14', is_mine: true },
    })
  render(<VkNativeCommentComposer feedGenId={41} onPosted={onPosted} />)
  fireEvent.change(screen.getByRole('textbox', { name: 'Новый комментарий' }), { target: { value: 'Без дублей' } })
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать комментарий' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Сеть недоступна')
  expect(screen.getByRole('textbox', { name: 'Новый комментарий' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Проверить и повторить тот же комментарий' }))
  await waitFor(() => expect(onPosted).toHaveBeenCalledTimes(1))
  const calls = jest.mocked(postVkPublicFeedComment).mock.calls
  expect(calls).toHaveLength(2)
  expect(calls[1].slice(0, 3)).toEqual(calls[0].slice(0, 3))
})

test('empty or oversized comment is never sent and never consumes a native request key', async () => {
  render(<VkNativeCommentComposer feedGenId={41} onPosted={jest.fn()} />)
  const textarea = screen.getByRole('textbox', { name: 'Новый комментарий' })
  expect(screen.getByRole('button', { name: 'Опубликовать комментарий' })).toBeDisabled()
  fireEvent.change(textarea, { target: { value: 'X'.repeat(501) } })
  expect(screen.getByRole('button', { name: 'Опубликовать комментарий' })).toBeDisabled()
  expect(postVkPublicFeedComment).not.toHaveBeenCalled()
})

test('unmounted composer does not report late write confirmation to a different post', async () => {
  let finish: ((value: any) => void) | undefined
  jest.mocked(postVkPublicFeedComment).mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const onPosted = jest.fn()
  const { unmount } = render(<VkNativeCommentComposer feedGenId={41} onPosted={onPosted} />)
  fireEvent.change(screen.getByRole('textbox', { name: 'Новый комментарий' }), { target: { value: 'Текст' } })
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать комментарий' }))
  unmount()
  await act(async () => finish?.({
    ok: true, comments_count: 1,
    comment: { id: 'vk:1', gen_id: 41, author: 'Участник ВКонтакте',
      text: 'Текст', created_at: '2026-11-14', is_mine: true },
  }))
  expect(onPosted).not.toHaveBeenCalled()
})
