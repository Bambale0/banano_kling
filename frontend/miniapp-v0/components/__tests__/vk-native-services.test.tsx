import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VkNativeServices } from '../vk-native-services'
import { fetchVkNativeState, fetchVkPublicDiscovery } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchVkNativeState: jest.fn(),
  fetchVkPublicDiscovery: jest.fn(),
}))

beforeEach(() => {
  jest.clearAllMocks()
  jest.mocked(fetchVkNativeState).mockResolvedValue({
    ok: true, registered: true, is_blocked: false,
    balance: 15, tasks: [], video_generation_enabled: false,
  })
  jest.mocked(fetchVkPublicDiscovery).mockResolvedValue({
    ok: true, can_generate_in_app: true, categories: [],
  })
})

test('VK uses the same service cards but enables only actual native capabilities', async () => {
  const navigate = jest.fn()
  render(<VkNativeServices onTabChange={navigate} communityId={239915802} />)
  const pinterest = screen.getByRole('button', { name: /Pinterest AI/i })
  const promptTool = screen.getByRole('button', { name: /Промпт по фото/i })
  const avatar = screen.getByRole('button', { name: /Avatar/i })
  expect(pinterest).toBeDisabled()
  expect(promptTool).toBeDisabled()
  expect(avatar).toBeDisabled()
  const editPhoto = screen.getByRole('button', { name: /Изменить фото/i })
  await waitFor(() => expect(editPhoto).toBeEnabled())
  fireEvent.click(editPhoto)
  expect(navigate).toHaveBeenCalledWith(1)
  expect(screen.getByRole('button', { name: /Оживить фото/i })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /Партнёрам/i }))
  expect(navigate).toHaveBeenCalledWith(7)
  expect(screen.queryByText('Привяжите Telegram')).not.toBeInTheDocument()
})

test('native video service becomes available only on a signed VK video-write gate', async () => {
  jest.mocked(fetchVkNativeState).mockResolvedValue({
    ok: true, registered: true, is_blocked: false,
    balance: 15, tasks: [], video_generation_enabled: true,
  })
  const navigate = jest.fn()
  render(<VkNativeServices onTabChange={navigate} communityId={239915802} />)
  const animate = screen.getByRole('button', { name: /Оживить фото/i })
  await waitFor(() => expect(animate).toBeEnabled())
  fireEvent.click(animate)
  expect(navigate).toHaveBeenCalledWith(2)
})

test('blocked or linked Telegram VK identity cannot access native paid service routes', async () => {
  jest.mocked(fetchVkNativeState).mockResolvedValue({
    ok: true, registered: true, is_blocked: true,
    balance: 0, tasks: [], video_generation_enabled: true,
  })
  render(<VkNativeServices onTabChange={jest.fn()} communityId={239915802} />)
  await waitFor(() => expect(screen.queryByText('Проверяем доступные сервисы ВКонтакте…')).not.toBeInTheDocument())
  expect(screen.getByRole('button', { name: /Изменить фото/i })).toBeDisabled()
  expect(screen.getByRole('button', { name: /Оживить фото/i })).toBeDisabled()
})

test('linked actor never probes native paid generation capability or uses TG balance', () => {
  render(<VkNativeServices onTabChange={jest.fn()} linkedTelegram communityId={239915802} />)
  expect(fetchVkNativeState).not.toHaveBeenCalled()
  expect(fetchVkPublicDiscovery).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: /Изменить фото/i })).toBeDisabled()
  expect(screen.getByRole('button', { name: /Оживить фото/i })).toBeDisabled()
})

test('offline native capability cannot leave paid service controls active', async () => {
  jest.mocked(fetchVkNativeState).mockRejectedValue(new Error('API down'))
  render(<VkNativeServices onTabChange={jest.fn()} communityId={239915802} />)
  await waitFor(() => expect(screen.queryByText('Проверяем доступные сервисы ВКонтакте…')).not.toBeInTheDocument())
  expect(screen.getByRole('button', { name: /Изменить фото/i })).toBeDisabled()
  expect(screen.getByRole('button', { name: /Оживить фото/i })).toBeDisabled()
})

test('VK support URL uses only verified community ID with safe rel', async () => {
  const navigate = jest.fn()
  render(<VkNativeServices onTabChange={navigate} communityId={239915802} />)
  fireEvent.click(screen.getByRole('button', { name: /Поддержка/i }))
  expect(screen.getByRole('link', { name: 'Написать в поддержку сообщества' }))
    .toHaveAttribute('href', 'https://vk.com/im?sel=-239915802')
  expect(screen.getByRole('link', { name: 'Написать в поддержку сообщества' }))
    .toHaveAttribute('rel', 'noopener noreferrer')
  expect(navigate).not.toHaveBeenCalled()
})

test('unconfigured community never fabricates a chat URL', () => {
  render(<VkNativeServices onTabChange={jest.fn()} communityId={null} />)
  expect(screen.getByRole('button', { name: /Поддержка/i })).toBeDisabled()
  expect(screen.queryByRole('link', { name: 'Написать в поддержку сообщества' })).not.toBeInTheDocument()
})
