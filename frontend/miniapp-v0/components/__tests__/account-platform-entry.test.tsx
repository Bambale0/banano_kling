jest.mock('../shared-commercial-preview', () => ({ SharedCommercialPreview: () => null }))
import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import { AccountPlatformEntry } from '../account-platform-entry'
import { fetchAccountPreviewAccess } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({ fetchAccountPreviewAccess: jest.fn() }))
jest.mock('../shared-wallet-preview', () => ({ SharedWalletPreview: () => <p>Тестовый кошелёк</p> }))
jest.mock('../shared-account-link-preview', () => ({ SharedAccountLinkPreview: ({ telegramBotUsername }: { telegramBotUsername: string }) => <p>Связать аккаунты {telegramBotUsername}</p> }))
afterEach(() => { window.history.replaceState({}, '', '/'); delete process.env.NEXT_PUBLIC_MINIAPP_PLATFORM; jest.resetAllMocks() })

test('dedicated VK build opened directly never mounts Telegram or requests an unsigned session', () => {
  process.env.NEXT_PUBLIC_MINIAPP_PLATFORM = 'vk'
  render(<AccountPlatformEntry><p>Telegram bootstrap</p></AccountPlatformEntry>)
  expect(screen.getByText('Откройте приложение из ВКонтакте.')).toBeInTheDocument()
  expect(screen.queryByText('Telegram bootstrap')).not.toBeInTheDocument()
  expect(fetchAccountPreviewAccess).not.toHaveBeenCalled()
})

test('VK starts its signed preview without mounting Telegram bootstrap', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001&sign=example')
  jest.mocked(fetchAccountPreviewAccess).mockResolvedValue({ revision: 1, vk_app_id: 123, telegram_bot_username: 'Neuromixx_bot' })
  render(<AccountPlatformEntry><p>Telegram bootstrap</p></AccountPlatformEntry>)
  expect(await screen.findByRole('main', { name: 'Проверка аккаунта ВК' })).toBeInTheDocument()
  expect(screen.queryByText('Telegram bootstrap')).not.toBeInTheDocument()
  expect(screen.getByText('Связать аккаунты Neuromixx_bot')).toBeInTheDocument()
})

test('ordinary VK user is denied and sees no account or wallet controls', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=3001&sign=example')
  jest.mocked(fetchAccountPreviewAccess).mockRejectedValue(new Error('Требуется доступ администратора.'))
  render(<AccountPlatformEntry><p>Telegram bootstrap</p></AccountPlatformEntry>)
  expect(await screen.findByText('Требуется доступ администратора.')).toBeInTheDocument()
  expect(screen.queryByText(/Связать аккаунты/)).not.toBeInTheDocument()
  expect(screen.queryByText('Telegram bootstrap')).not.toBeInTheDocument()
})

test('Telegram entry retains the existing application', () => {
  render(<AccountPlatformEntry><p>Telegram bootstrap</p></AccountPlatformEntry>)
  expect(screen.getByText('Telegram bootstrap')).toBeInTheDocument()
  expect(fetchAccountPreviewAccess).not.toHaveBeenCalled()
})
