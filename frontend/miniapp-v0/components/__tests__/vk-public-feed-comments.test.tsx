import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VkPublicFeedComments } from '../vk-public-feed-comments'
import { fetchVkPublicFeedComments } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchVkPublicFeedComments: jest.fn(),
}))

beforeEach(() => {
  jest.resetAllMocks()
})

test('VK-only viewer reads comments from the shared public feed, without a Telegram link', async () => {
  jest.mocked(fetchVkPublicFeedComments).mockResolvedValue({
    ok: true, comments_count: 2,
    comments: [
      { id: 1, author: 'Анна', text: 'Супер!', created_at: '2026-11-14T12:00:00' },
      { id: 2, author: 'VK user', text: 'Класс', created_at: '2026-11-14T12:01:00' },
    ],
  })
  render(<VkPublicFeedComments feedGenId={41} />)
  expect(await screen.findByText('Супер!')).toBeInTheDocument()
  expect(screen.getByText('Класс')).toBeInTheDocument()
  expect(screen.getByText('Анна')).toBeInTheDocument()
  expect(fetchVkPublicFeedComments).toHaveBeenCalledWith(41, expect.anything())
  expect(screen.queryByText(/привяжите Telegram/i)).not.toBeInTheDocument()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument() // read only, no fake VK writer
})

test('failed public comment fetch explains failure and allows owner-safe retry', async () => {
  jest.mocked(fetchVkPublicFeedComments).mockRejectedValueOnce(new Error('Сеть недоступна'))
    .mockResolvedValueOnce({ ok: true, comments_count: 0, comments: [] })
  render(<VkPublicFeedComments feedGenId={55} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Сеть недоступна')
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку комментариев' }))
  await waitFor(() => expect(fetchVkPublicFeedComments).toHaveBeenCalledTimes(2))
  expect(await screen.findByText('Комментариев пока нет.')).toBeInTheDocument()
})

test('reopening a different public item aborts old comments and never shows stale author data', async () => {
  let finishOld: ((value: any) => void) | undefined
  jest.mocked(fetchVkPublicFeedComments).mockImplementationOnce(() => new Promise(resolve => {
    finishOld = resolve
  })).mockResolvedValueOnce({
    ok: true, comments_count: 1,
    comments: [{ id: 10, author: 'Новый автор', text: 'Публикация 2', created_at: '2026-11-14' }],
  })
  const { rerender } = render(<VkPublicFeedComments key="1" feedGenId={1} />)
  rerender(<VkPublicFeedComments key="2" feedGenId={2} />)
  expect(await screen.findByText('Публикация 2')).toBeInTheDocument()
  finishOld?.({
    ok: true, comments_count: 1,
    comments: [{ id: 11, author: 'Чужой автор', text: 'Публикация 1', created_at: '2026-11-14' }],
  })
  await waitFor(() => expect(screen.queryByText('Публикация 1')).not.toBeInTheDocument())
})
