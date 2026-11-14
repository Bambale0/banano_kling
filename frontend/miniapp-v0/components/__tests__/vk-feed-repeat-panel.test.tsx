import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VkFeedRepeatPanel } from '../vk-feed-repeat-panel'
import { fetchVkGenerationClaim, repeatVkFeed, uploadVkImage } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchVkGenerationClaim: jest.fn(),
  repeatVkFeed: jest.fn(),
  uploadVkImage: jest.fn(),
}))

beforeEach(() => {
  jest.clearAllMocks()
  jest.mocked(repeatVkFeed).mockResolvedValue({
    ok: true, task_id: 78, cost: 3,
  })
  jest.mocked(fetchVkGenerationClaim).mockResolvedValue({ ok: true, found: false })
  jest.mocked(uploadVkImage).mockResolvedValue('https://example.test/owned-vk.jpg')
})

test('VK photo feed repeat has its own quote and paid claim, never a trend ID or Telegram field', async () => {
  render(<VkFeedRepeatPanel feedId={61} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText(/Подтверждённая стоимость: 3/)).toBeInTheDocument()
  expect(repeatVkFeed).toHaveBeenCalledWith({
    feed_gen_id: 61, reference_urls: [], quote_only: true,
  })
  fireEvent.click(screen.getByRole('button', { name: 'Создать с VK-баланса' }))
  expect(await screen.findByText(/Задача #78 создана/)).toBeInTheDocument()
  const paid = jest.mocked(repeatVkFeed).mock.calls[1][0]
  expect(paid).toEqual(expect.objectContaining({
    feed_gen_id: 61, reference_urls: [], quote_only: false,
    client_request_id: expect.stringMatching(/^vk_[a-f0-9]{32}$/), expected_cost: 3,
  }))
  expect(paid).not.toHaveProperty('trend_id')
  expect(paid).not.toHaveProperty('telegram_id')
  expect(fetchVkGenerationClaim).not.toHaveBeenCalled()
})

test('VK public feed upload sends only newly selected VK-owner references', async () => {
  render(<VkFeedRepeatPanel feedId={62} onClose={() => {}} />)
  fireEvent.change(screen.getByLabelText('Фото для повтора публикации'), {
    target: { files: [new File(['private-new-bytes'], 'new.jpg', { type: 'image/jpeg' })] },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(uploadVkImage).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(repeatVkFeed).toHaveBeenCalledWith({
    feed_gen_id: 62, quote_only: true,
    reference_urls: ['https://example.test/owned-vk.jpg'],
  }))
})

test('ambiguous charged POST verifies same native photo claim instead of retrying', async () => {
  jest.mocked(repeatVkFeed).mockResolvedValueOnce({
    ok: true, task_id: 0, cost: 3,
  }).mockRejectedValueOnce(new Error('Provider timeout'))
  jest.mocked(fetchVkGenerationClaim).mockResolvedValue({
    ok: true, found: true, task_id: 89, task_type: 'photo',
    status: 'processing', cost: 3,
  })
  render(<VkFeedRepeatPanel feedId={63} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await screen.findByText(/Подтверждённая стоимость/)
  fireEvent.click(screen.getByRole('button', { name: 'Создать с VK-баланса' }))
  expect(await screen.findByText(/Задача #89 создана/)).toBeInTheDocument()
  expect(fetchVkGenerationClaim).toHaveBeenCalledTimes(1)
  const paid = jest.mocked(repeatVkFeed).mock.calls[1][0]
  expect(fetchVkGenerationClaim).toHaveBeenCalledWith(paid.client_request_id)
  expect(repeatVkFeed).toHaveBeenCalledTimes(2)
})

test('unknown VK status preserves the paid claim across a manual retry', async () => {
  jest.mocked(repeatVkFeed).mockResolvedValueOnce({
    ok: true, task_id: 0, cost: 3,
  }).mockRejectedValueOnce(new Error('Provider timeout')).mockResolvedValueOnce({
    ok: true, task_id: 96, cost: 3,
  })
  render(<VkFeedRepeatPanel feedId={64} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await screen.findByText(/Подтверждённая стоимость/)
  fireEvent.click(screen.getByRole('button', { name: 'Создать с VK-баланса' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Статус операции неизвестен')
  const first = jest.mocked(repeatVkFeed).mock.calls[1][0]
  expect(first.client_request_id).toMatch(/^vk_[a-f0-9]{32}$/)
  fireEvent.click(screen.getByRole('button', { name: 'Создать с VK-баланса' }))
  expect(await screen.findByText(/Задача #96 создана/)).toBeInTheDocument()
  const second = jest.mocked(repeatVkFeed).mock.calls[2][0]
  expect(second.client_request_id).toBe(first.client_request_id)
  expect(second.expected_cost).toBe(first.expected_cost)
})

test('a mismatched video task claim never confirms a paid image feed repeat', async () => {
  jest.mocked(repeatVkFeed).mockResolvedValueOnce({
    ok: true, task_id: 0, cost: 3,
  }).mockRejectedValueOnce(new Error('unknown'))
  jest.mocked(fetchVkGenerationClaim).mockResolvedValue({
    ok: true, found: true, task_id: 90, task_type: 'video',
    status: 'processing', cost: 3,
  })
  render(<VkFeedRepeatPanel feedId={65} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await screen.findByText(/Подтверждённая стоимость/)
  fireEvent.click(screen.getByRole('button', { name: 'Создать с VK-баланса' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Статус операции неизвестен')
  expect(screen.queryByText(/Задача #90 создана/)).not.toBeInTheDocument()
})
