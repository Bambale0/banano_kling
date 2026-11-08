jest.mock('../shared-commercial-preview', () => ({ SharedCommercialPreview: () => null }))
import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import { AccountPlatformEntry } from '../account-platform-entry'
import { startAccountAppSession, stopAccountAppSession } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  startAccountAppSession: jest.fn(),
  stopAccountAppSession: jest.fn(),
}))
jest.mock('../shared-account-link-preview', () => ({ SharedAccountLinkPreview: ({ telegramBotUsername }: { telegramBotUsername: string }) => <p>Связать аккаунты {telegramBotUsername}</p> }))

afterEach(() => {
  window.history.replaceState({}, '', '/')
  delete process.env.NEXT_PUBLIC_MINIAPP_PLATFORM
  jest.resetAllMocks()
})

test('dedicated VK build opened directly never mounts application or requests an unsigned session', () => {
  process.env.NEXT_PUBLIC_MINIAPP_PLATFORM = 'vk'
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(screen.getByText('Откройте приложение из ВКонтакте.')).toBeInTheDocument()
  expect(screen.queryByText('Общая студия')).not.toBeInTheDocument()
  expect(startAccountAppSession).not.toHaveBeenCalled()
})

test('linked VK account mounts the same application', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001&sign=example')
  jest.mocked(startAccountAppSession).mockResolvedValue({
    revision: 1,
    vk_app_id: 123,
    telegram_bot_username: 'Neuromixx_bot',
    telegram_linked: true,
  })
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(await screen.findByText('Общая студия')).toBeInTheDocument()
  expect(screen.queryByText(/Связать аккаунты/)).not.toBeInTheDocument()
})

test('unlinked VK account sees only the mandatory link gate', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001&sign=example')
  jest.mocked(startAccountAppSession).mockResolvedValue({
    revision: 1,
    vk_app_id: 123,
    telegram_bot_username: 'Neuromixx_bot',
    telegram_linked: false,
  })
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(await screen.findByText('Связать аккаунты Neuromixx_bot')).toBeInTheDocument()
  expect(screen.queryByText('Общая студия')).not.toBeInTheDocument()
})

test('ordinary unlinked VK user is admitted to the mandatory link gate', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=3001&sign=example')
  jest.mocked(startAccountAppSession).mockResolvedValue({
    revision: 1,
    vk_app_id: 123,
    telegram_bot_username: 'Neuromixx_bot',
    telegram_linked: false,
  })
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(await screen.findByText('Связать аккаунты Neuromixx_bot')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Свяжите аккаунты ТГ и ВК' })).toBeInTheDocument()
  expect(screen.queryByText('Общая студия')).not.toBeInTheDocument()
})

test('Telegram entry retains the existing application', () => {
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(screen.getByText('Общая студия')).toBeInTheDocument()
  expect(startAccountAppSession).not.toHaveBeenCalled()
  expect(stopAccountAppSession).not.toHaveBeenCalled()
})
