import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VkNativeServices } from '../vk-native-services'
import { fetchVkNativeState, fetchVkPublicDiscovery } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchVkNativeState: jest.fn(),
  fetchVkPublicDiscovery: jest.fn(),
}))

beforeEach(() => {
  jest.resetAllMocks()
  jest.mocked(fetchVkNativeState).mockResolvedValue({
    ok: true, registered: true, is_blocked: false, balance: 15,
    video_generation_enabled: true, tasks: [],
  })
  jest.mocked(fetchVkPublicDiscovery).mockResolvedValue({
    ok: true, categories: [], can_generate_in_app: true,
  })
})

test('VK Services reuses the same service-grid cards but routes only genuinely native capabilities', async () => {
  const onNavigate = jest.fn()
  render(<VkNativeServices onNavigate={onNavigate} verifiedVkCommunityId={239915802} />)
  await waitFor(() => expect(screen.getByRole('button', { name: /Изменить фото/ })).toBeEnabled())
  expect(fetchVkNativeState).toHaveBeenCalledWith(expect.any(AbortSignal))
  expect(fetchVkPublicDiscovery).toHaveBeenCalledWith('trends', expect.any(AbortSignal))
  expect(screen.getByRole('button', { name: /Оживить фото/ })).toBeEnabled()
  expect(screen.getByRole('button', { name: /Промпт по фото/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: /Avatar/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: /Pinterest AI/ })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /Изменить фото/ }))
  expect(onNavigate).toHaveBeenLastCalledWith(1)
  fireEvent.click(screen.getByRole('button', { name: /Оживить фото/ }))
  expect(onNavigate).toHaveBeenLastCalledWith(2)
  fireEvent.click(screen.getByRole('button', { name: /Партнёрам/ }))
  expect(onNavigate).toHaveBeenLastCalledWith(7)
  expect(onNavigate).toHaveBeenCalledTimes(3)
})

test('support opens only a verified community chat and never a user-supplied URL', async () => {
  render(<VkNativeServices onNavigate={jest.fn()} verifiedVkCommunityId={239915802} />)
  await waitFor(() => expect(screen.getByRole('button', { name: /Поддержка/ })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: /Поддержка/ }))
  expect(screen.getByRole('link', { name: 'Открыть диалог с поддержкой ВКонтакте' }))
    .toHaveAttribute('href', 'https://vk.com/im?sel=-239915802')
})

test('missing or invalid VK community id does not fabricate a support link', async () => {
  const onNavigate = jest.fn()
  render(<VkNativeServices onNavigate={onNavigate} verifiedVkCommunityId={-99} />)
  await waitFor(() => expect(fetchVkNativeState).toHaveBeenCalled())
  expect(screen.getByRole('button', { name: /Поддержка/ })).toBeDisabled()
  expect(screen.queryByRole('link', { name: 'Открыть диалог с поддержкой ВКонтакте' })).not.toBeInTheDocument()
  expect(onNavigate).not.toHaveBeenCalled()
})

test('blocked VK actor fails closed for chargeable photo and video services', async () => {
  jest.mocked(fetchVkNativeState).mockResolvedValue({
    ok: true, registered: true, is_blocked: true, balance: 200,
    video_generation_enabled: true, tasks: [],
  })
  const onNavigate = jest.fn()
  render(<VkNativeServices onNavigate={onNavigate} />)
  await waitFor(() => expect(fetchVkPublicDiscovery).toHaveBeenCalled())
  expect(screen.getByRole('button', { name: /Изменить фото/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: /Оживить фото/ })).toBeDisabled()
  expect(onNavigate).not.toHaveBeenCalled()
})

test('VK capability failure never enables Telegram-only services as a fallback', async () => {
  jest.mocked(fetchVkNativeState).mockRejectedValue(new Error('native unavailable'))
  render(<VkNativeServices onNavigate={jest.fn()} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Доступность сервисов ВКонтакте не подтверждена')
  expect(screen.getByRole('button', { name: /Промпт по фото/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: /Avatar/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: /Изменить фото/ })).toBeDisabled()
})

test('existing Telegram ServiceGrid remains unrestricted without actor-specific gates', () => {
  const { ServiceGrid } = jest.requireActual('../service-grid') as typeof import('../service-grid')
  const click = jest.fn()
  render(<ServiceGrid activeServiceId="pinterest-ai" onServiceClick={click} />)
  const normalButton = screen.getByRole('button', { name: /Промпт по фото/ })
  expect(normalButton).toBeEnabled()
  fireEvent.click(normalButton)
  expect(click).toHaveBeenCalledWith('prompt-by-photo')
})
