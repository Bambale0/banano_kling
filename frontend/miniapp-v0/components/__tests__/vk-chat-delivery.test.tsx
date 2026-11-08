import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VkChatDelivery } from '../vk-chat-delivery'
import { fetchVkChatDelivery, requestVkChatDelivery } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({ fetchVkChatDelivery: jest.fn(), requestVkChatDelivery: jest.fn() }))

beforeEach(() => {
  jest.resetAllMocks()
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001&sign=fixture')
})
afterEach(() => { window.history.replaceState({}, '', '/') })

test('Telegram result makes no VK delivery request', () => {
  window.history.replaceState({}, '', '/')
  const { container } = render(<VkChatDelivery taskId="task-one" />)
  expect(container).toBeEmptyDOMElement()
  expect(fetchVkChatDelivery).not.toHaveBeenCalled()
})

test('missing permission offers the configured VK chat and explicit retry only', async () => {
  jest.mocked(fetchVkChatDelivery).mockResolvedValue({ state: 'permission_required', community_id: 456, can_request: true })
  jest.mocked(requestVkChatDelivery).mockResolvedValue({ state: 'delivered', community_id: 456, can_request: false })
  render(<VkChatDelivery taskId="task-one" />)
  expect(await screen.findByRole('link', { name: 'Открыть чат ВК' })).toHaveAttribute('href', 'https://vk.com/write-456')
  expect(requestVkChatDelivery).not.toHaveBeenCalled()
  const native = jest.fn()
  Object.defineProperty(window, 'AndroidBridge', { configurable: true, value: { VKWebAppAllowMessagesFromGroup: native } })
  fireEvent.click(screen.getByRole('button', { name: 'Разрешить сообщения ВК' }))
  expect(native).toHaveBeenCalledWith(JSON.stringify({ group_id: 456 }))
  expect(requestVkChatDelivery).not.toHaveBeenCalled()
  expect(screen.queryByText('Отправлено в чат ВК.')).not.toBeInTheDocument()
  Object.defineProperty(window, 'AndroidBridge', { configurable: true, value: undefined })
  fireEvent.click(screen.getByRole('button', { name: 'Проверить и отправить' }))
  expect(await screen.findByText('Отправлено в чат ВК.')).toBeInTheDocument()
  expect(requestVkChatDelivery).toHaveBeenCalledTimes(1)
})

test('uncertain send asks to check the chat and never offers another send', async () => {
  jest.mocked(fetchVkChatDelivery).mockResolvedValue({ state: 'uncertain', community_id: 456, can_request: false })
  render(<VkChatDelivery taskId="task-one" />)
  expect(await screen.findByText(/ВК не подтвердил отправку/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /отправить/i })).not.toBeInTheDocument()
  expect(requestVkChatDelivery).not.toHaveBeenCalled()
})

test('opening an old result only checks status; sending needs its own action', async () => {
  jest.mocked(fetchVkChatDelivery).mockResolvedValue({ state: 'not_requested', community_id: 456, can_request: true })
  render(<VkChatDelivery taskId="old-task" />)
  expect(await screen.findByRole('button', { name: 'Отправить в чат ВК' })).toBeEnabled()
  expect(requestVkChatDelivery).not.toHaveBeenCalled()
})

test('stalled status ends after a deadline and late response cannot claim delivery', async () => {
  jest.useFakeTimers()
  try {
    let resolve!: (value: { state: 'delivered'; community_id: number; can_request: boolean }) => void
    jest.mocked(fetchVkChatDelivery).mockReturnValue(new Promise(done => { resolve = done }))
    render(<VkChatDelivery taskId="task-one" />)
    await act(async () => { jest.advanceTimersByTime(15000) })
    expect(screen.getByRole('alert')).toHaveTextContent('Проверка заняла слишком много времени')
    expect(screen.queryByText('Проверяем доставку в чат ВК…')).not.toBeInTheDocument()
    expect(jest.mocked(fetchVkChatDelivery).mock.calls[0][1]?.aborted).toBe(true)
    await act(async () => { resolve({ state: 'delivered', community_id: 456, can_request: false }) })
    expect(screen.queryByText('Отправлено в чат ВК.')).not.toBeInTheDocument()
  } finally { jest.useRealTimers() }
})

test('pending result is polled without posting a second delivery', async () => {
  jest.useFakeTimers()
  try {
    jest.mocked(fetchVkChatDelivery).mockResolvedValueOnce({ state: 'pending', community_id: 456, can_request: false })
      .mockResolvedValueOnce({ state: 'delivered', community_id: 456, can_request: false })
    render(<VkChatDelivery taskId="task-one" />)
    await act(async () => { await Promise.resolve() })
    await act(async () => { jest.advanceTimersByTime(3000) })
    await waitFor(() => expect(screen.getByText('Отправлено в чат ВК.')).toBeInTheDocument())
    expect(requestVkChatDelivery).not.toHaveBeenCalled()
  } finally { jest.useRealTimers() }
})
