jest.mock('../shared-commercial-preview', () => ({ SharedCommercialPreview: () => null }))
import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { renderToString } from 'react-dom/server'
import { AccountPlatformEntry } from '../account-platform-entry'
import { fetchVkPublicDiscovery, fetchVkNativeState, startAccountAppSession, stopAccountAppSession } from '@/lib/shared-account-api'
import { incomingAccountLink } from '@/lib/account-platform'

jest.mock('@/lib/shared-account-api', () => ({
  startAccountAppSession: jest.fn(),
  stopAccountAppSession: jest.fn(),
  fetchVkPublicDiscovery: jest.fn(),
  fetchVkPublicCategory: jest.fn(),
  fetchVkNativeState: jest.fn(),
}))
jest.mock('@/lib/account-platform', () => ({ incomingAccountLink: jest.fn(() => '') }))
jest.mock('../shared-account-link-preview', () => ({ SharedAccountLinkPreview: ({ telegramBotUsername, onCommitted }: { telegramBotUsername: string; onCommitted?: () => void }) =>
  <><p>Связать аккаунты {telegramBotUsername}</p>{onCommitted ? <button onClick={onCommitted}>Привязка подтверждена</button> : null}</> }))

beforeEach(() => {
  jest.mocked(fetchVkNativeState).mockResolvedValue({
    ok: true, registered: false, balance: null, is_blocked: false, tasks: [],
  })
  jest.mocked(fetchVkPublicDiscovery).mockResolvedValue({ ok: true, categories: [], can_generate_in_app: false })
})

afterEach(() => {
  window.history.replaceState({}, '', '/')
  delete process.env.NEXT_PUBLIC_MINIAPP_PLATFORM
  jest.resetAllMocks()
})

test('VK server first paint is readable without JavaScript instead of blank', () => {
  process.env.NEXT_PUBLIC_MINIAPP_PLATFORM = 'vk'
  const markup = renderToString(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(markup).toContain('Открываем приложение ВКонтакте')
  expect(markup).toContain('/mini-app/api/account-preview/vk-login')
  expect(markup).not.toContain('Общая студия')
})

test('direct VK link offers official VK sign-in instead of a dead end', () => {
  process.env.NEXT_PUBLIC_MINIAPP_PLATFORM = 'vk'
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(screen.getByRole('link', { name: 'Войти через ВКонтакте' }))
    .toHaveAttribute('href', '/mini-app/api/account-preview/vk-login')
  expect(screen.queryByText('Общая студия')).not.toBeInTheDocument()
  expect(startAccountAppSession).not.toHaveBeenCalled()
})

test('dedicated VK build opened directly never mounts application or requests an unsigned session', () => {
  process.env.NEXT_PUBLIC_MINIAPP_PLATFORM = 'vk'
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(screen.getByRole('heading', { name: 'Вход в NEUROMIX' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Войти через ВКонтакте' })).toBeInTheDocument()
  expect(screen.queryByText('Общая студия')).not.toBeInTheDocument()
  expect(startAccountAppSession).not.toHaveBeenCalled()
})

test('expired signed VK launch offers fresh sign-in without mounting the app', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001&sign=old')
  jest.mocked(startAccountAppSession).mockRejectedValue(new Error('Проверка входа истекла'))
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(await screen.findByText('Проверка входа истекла')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Войти через ВКонтакте' }))
    .toHaveAttribute('href', '/mini-app/api/account-preview/vk-login')
  expect(screen.queryByText('Общая студия')).not.toBeInTheDocument()
})

test('VK-only full-capability session mounts same shared shell without Telegram link', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001&sign=valid')
  jest.mocked(startAccountAppSession).mockResolvedValue({
    revision: 1,
    vk_app_id: 123,
    telegram_bot_username: 'Neuromixx_bot',
    telegram_linked: false,
    full_app_ready: true,
  })
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(await screen.findByText('Общая студия')).toBeInTheDocument()
  expect(screen.queryByText('Создавайте в ВКонтакте')).not.toBeInTheDocument()
  expect(screen.queryByText('Связать аккаунты Neuromixx_bot')).not.toBeInTheDocument()
})

test('VK linked status is not sufficient to impersonate full app readiness when server denies it', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001&sign=valid')
  jest.mocked(startAccountAppSession).mockResolvedValue({
    revision: 1,
    vk_app_id: 123,
    telegram_bot_username: 'Neuromixx_bot',
    telegram_linked: true,
    full_app_ready: false,
  })
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(await screen.findByText('Создавайте в ВКонтакте')).toBeInTheDocument()
  expect(screen.queryByText('Общая студия')).not.toBeInTheDocument()
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

test('unlinked VK account offers optional Telegram linking', async () => {
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

test('verified VK-only account can return to its native bot without Telegram', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001&sign=example')
  jest.mocked(startAccountAppSession).mockResolvedValue({
    revision: 1,
    vk_app_id: 123,
    vk_community_id: 239915802,
    telegram_bot_username: 'Neuromixx_bot',
    telegram_linked: false,
  })
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  const chat = await screen.findByRole('link', { name: 'Генерировать в боте ВКонтакте' })
  expect(chat).toHaveAttribute('href', 'https://vk.com/im?sel=-239915802')
  expect(screen.getByText(/Telegram не обязателен/)).toBeInTheDocument()
  expect(screen.getByText(/Средства из прежнего VK-бота автоматически не переносятся/)).toBeInTheDocument()
  expect(screen.queryByText('Общая студия')).not.toBeInTheDocument()
})

test('VK-only entry refuses to invent a chat link when community is not configured', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=3001&sign=example')
  jest.mocked(startAccountAppSession).mockResolvedValue({
    revision: 1,
    vk_app_id: 123,
    vk_community_id: null,
    telegram_bot_username: 'Neuromixx_bot',
    telegram_linked: false,
  })
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(await screen.findByText(/Диалог с ботом сейчас недоступен по прямой ссылке/)).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Генерировать в боте ВКонтакте' })).not.toBeInTheDocument()
  expect(screen.getByText(/Telegram не обязателен/)).toBeInTheDocument()
})

test('signed VK invite keeps the two-sided confirmation visible immediately', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001&sign=example#link_' + 'a'.repeat(43))
  jest.mocked(incomingAccountLink).mockReturnValue('a'.repeat(43))
  jest.mocked(startAccountAppSession).mockResolvedValue({
    revision: 1,
    vk_app_id: 123,
    vk_community_id: 239915802,
    telegram_bot_username: 'Neuromixx_bot',
    telegram_linked: false,
  })
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  const summary = await screen.findByText('Связать Telegram (необязательно)')
  expect(summary.closest('details')).toHaveAttribute('open')
})

test('ordinary unlinked VK user can choose the Telegram link flow', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=3001&sign=example')
  jest.mocked(startAccountAppSession).mockResolvedValue({
    revision: 1,
    vk_app_id: 123,
    telegram_bot_username: 'Neuromixx_bot',
    telegram_linked: false,
  })
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(await screen.findByText('Связать аккаунты Neuromixx_bot')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Создавайте в ВКонтакте' })).toBeInTheDocument()
  expect(screen.getByText(/Средства из прежнего VK-бота автоматически не переносятся/)).toBeInTheDocument()
  expect(screen.queryByText(/в обеих апках были общий баланс/)).not.toBeInTheDocument()
  expect(screen.queryByText('Общая студия')).not.toBeInTheDocument()
})

test('Telegram entry retains the existing application', () => {
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(screen.getByText('Общая студия')).toBeInTheDocument()
  expect(startAccountAppSession).not.toHaveBeenCalled()
  expect(stopAccountAppSession).not.toHaveBeenCalled()
})

test('Telegram direct Mini App startapp invitation enters confirmation instead of the studio', async () => {
  jest.mocked(incomingAccountLink).mockReturnValue('a'.repeat(43))
  render(<AccountPlatformEntry><p>Общая студия</p></AccountPlatformEntry>)
  expect(await screen.findByRole('heading', { name: 'Привязка Telegram и ВКонтакте' })).toBeInTheDocument()
  expect(screen.queryByText('Общая студия')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Привязка подтверждена' }))
  expect(screen.getByText('Общая студия')).toBeInTheDocument()
  expect(startAccountAppSession).not.toHaveBeenCalled()
})
