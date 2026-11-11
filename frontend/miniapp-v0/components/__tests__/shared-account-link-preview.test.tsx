import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { SharedAccountLinkPreview } from '../shared-account-link-preview'
import {
  acceptAccountLink, createAccountLink, fetchAccountPreviewAccess, previewAccountLink, updateAccountLink,
} from '@/lib/shared-account-api'
import { accountLinkUrl, currentAccountPlatform, incomingAccountLink, nativeTelegramMiniAppUrl } from '@/lib/account-platform'
import { buildTelegramMiniAppUrl } from '@/lib/api'

jest.mock('@/lib/api', () => ({ buildTelegramMiniAppUrl: jest.fn(() => 'https://t.me/configured_bot?startapp') }))
jest.mock('@/lib/shared-account-api', () => ({
  acceptAccountLink: jest.fn(), createAccountLink: jest.fn(),
  previewAccountLink: jest.fn(), updateAccountLink: jest.fn(),
  fetchAccountPreviewAccess: jest.fn(),
}))
jest.mock('@/lib/account-platform', () => ({
  ...jest.requireActual('@/lib/account-platform'),
  currentAccountPlatform: jest.fn(), accountLinkUrl: jest.fn(), incomingAccountLink: jest.fn(),
}))

const inviteToken = 'a'.repeat(43)
const pending = {
  id: 'invite1', state: 'pending' as const, revision: 0, expires_at_epoch: 9999999999,
  source_platform: 'vk' as const, target_platform: 'telegram' as const,
  source_confirmed: true, target_confirmed: false, token: inviteToken,
}
const offered = {
  ...pending,
  source_identity: { platform: 'vk' as const, external_id: '381643597' },
  target_identity: null,
}
let popup: {
  opener: Window | null, document: { title: string }, location: { replace: jest.Mock },
  closed: boolean, close: jest.Mock,
}

beforeEach(() => {
  jest.resetAllMocks()
  jest.mocked(incomingAccountLink).mockReturnValue('')
  jest.mocked(currentAccountPlatform).mockReturnValue('vk')
  jest.mocked(buildTelegramMiniAppUrl).mockReturnValue('https://t.me/configured_bot?startapp')
  jest.mocked(accountLinkUrl).mockImplementation((platform, token) =>
    platform === 'telegram'
      ? 'https://t.me/test_bot?startapp=link_' + token
      : 'https://vk.com/app123#link_' + token)
  jest.mocked(fetchAccountPreviewAccess).mockResolvedValue({
    revision: 1, vk_app_id: 123, telegram_bot_username: 'test_bot',
    telegram_linked: false, linked_platforms: ['vk'],
  })
  popup = {
    opener: window, document: { title: '' }, location: { replace: jest.fn() },
    closed: false, close: jest.fn(),
  }
  jest.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
})
afterEach(() => {
  jest.restoreAllMocks()
  jest.useRealTimers()
})

test('Telegram invitation uses the native Mini App URI supported by installed clients', () => {
  expect(nativeTelegramMiniAppUrl(`https://t.me/Neuromixx_bot?startapp=link_${inviteToken}`))
    .toBe(`tg://resolve?domain=Neuromixx_bot&startapp=link_${inviteToken}`)
})

test.each([
  `https://t.me.evil.example/Neuromixx_bot?startapp=link_${inviteToken}`,
  `https://evil.example/Neuromixx_bot?startapp=link_${inviteToken}`,
  `http://t.me/Neuromixx_bot?startapp=link_${inviteToken}`,
  'https://t.me/Neuromixx_bot?startapp=link_bad',
  `https://t.me/Neuromixx_bot?startapp=link_${inviteToken}&extra=1`,
  `https://t.me/Neuromixx_bot/extra?startapp=link_${inviteToken}`,
])('native Telegram navigation rejects unsafe or malformed invitations: %s', url => {
  expect(() => nativeTelegramMiniAppUrl(url)).toThrow('Некорректная ссылка.')
})

test('VK WebView must not open about:blank before an asynchronous Telegram invitation', async () => {
  jest.mocked(createAccountLink).mockResolvedValue(pending)
  render(<SharedAccountLinkPreview vkAppId={123} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Привязать Telegram' }))
  await screen.findByRole('region', { name: 'Ожидание привязки' })
  expect(window.open).not.toHaveBeenCalled()
  expect(popup.location.replace).not.toHaveBeenCalled()
  expect(screen.getByRole('link', { name: 'Открыть приложение Telegram' }))
    .toHaveAttribute('href', 'tg://resolve?domain=test_bot&startapp=link_' + inviteToken)
})

test('VK connect prepares Telegram link and waits for a user gesture', async () => {
  jest.mocked(createAccountLink).mockResolvedValue(pending)
  render(<SharedAccountLinkPreview vkAppId={null} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Привязать Telegram' }))
  await waitFor(() => expect(createAccountLink).toHaveBeenCalledWith('telegram', expect.any(AbortSignal), true))
  expect(await screen.findByRole('link', { name: 'Открыть приложение Telegram' })).toHaveAttribute('href', 'tg://resolve?domain=test_bot&startapp=link_' + inviteToken)
  expect(screen.getByRole('link', { name: 'Открыть через браузер' })).toHaveAttribute('href', 'https://t.me/test_bot?startapp=link_' + inviteToken)
  expect(screen.getByLabelText('Если VK не запускает Telegram, скопируйте ссылку и откройте её в Telegram.'))
    .toHaveValue('https://t.me/test_bot?startapp=link_' + inviteToken)
  expect(screen.getByRole('button', { name: 'Скопировать ссылку' })).toBeEnabled()
  expect(window.open).not.toHaveBeenCalled()
  expect(popup.location.replace).not.toHaveBeenCalled()
  expect(screen.getByRole('link', { name: 'Открыть приложение Telegram' })).toHaveAttribute('target', '_self')
  expect(accountLinkUrl).toHaveBeenLastCalledWith('telegram', inviteToken, 123, 'test_bot')
  expect(screen.getByRole('region', { name: 'Ожидание привязки' })).toBeInTheDocument()
  expect(screen.queryByLabelText('Код из ссылки')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Создать ссылку' })).not.toBeInTheDocument()
  expect(acceptAccountLink).not.toHaveBeenCalled()
})

test('existing linked account displays both verified badges and no connect button', async () => {
  jest.mocked(fetchAccountPreviewAccess).mockResolvedValue({
    revision: 1, vk_app_id: 123, telegram_bot_username: 'test_bot',
    telegram_linked: true, linked_platforms: ['telegram', 'vk'],
  })
  render(<SharedAccountLinkPreview vkAppId={123} />)
  expect(await screen.findByLabelText('ВКонтакте привязан')).toBeInTheDocument()
  expect(screen.getByLabelText('Telegram привязан')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Привязать/ })).not.toBeInTheDocument()
  expect(createAccountLink).not.toHaveBeenCalled()
})

test('Telegram source opens signed VK app with backend-configured app ID', async () => {
  jest.mocked(currentAccountPlatform).mockReturnValue('telegram')
  jest.mocked(fetchAccountPreviewAccess).mockResolvedValue({
    revision: 1, vk_app_id: 123, telegram_bot_username: 'test_bot',
    telegram_linked: true, linked_platforms: ['telegram'],
  })
  jest.mocked(createAccountLink).mockResolvedValue({
    ...pending, source_platform: 'telegram', target_platform: 'vk',
  })
  render(<SharedAccountLinkPreview vkAppId={null} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Привязать ВКонтакте' }))
  await waitFor(() => expect(createAccountLink).toHaveBeenCalledWith('vk', expect.any(AbortSignal), true))
  expect(await screen.findByRole('link', { name: 'Открыть ВКонтакте ещё раз' }))
    .toHaveAttribute('href', 'https://vk.com/app123#link_' + inviteToken)
  expect(window.open).not.toHaveBeenCalled()
})

test('incoming deep link previews source but does not link a visitor without consent', async () => {
  jest.mocked(currentAccountPlatform).mockReturnValue('telegram')
  jest.mocked(incomingAccountLink).mockReturnValue(inviteToken)
  jest.mocked(fetchAccountPreviewAccess).mockResolvedValue({
    revision: 1, vk_app_id: 123, telegram_bot_username: 'test_bot',
    telegram_linked: true, linked_platforms: ['telegram'],
  })
  jest.mocked(previewAccountLink).mockResolvedValue(offered)
  render(<SharedAccountLinkPreview vkAppId={null} />)
  expect(await screen.findByText(/ВКонтакте №381643597/)).toBeInTheDocument()
  expect(screen.getByText(/Средства старого VK-бота пока остаются отдельно/)).toBeInTheDocument()
  expect(previewAccountLink).toHaveBeenCalledWith(inviteToken, expect.any(AbortSignal))
  expect(acceptAccountLink).not.toHaveBeenCalled()
  expect(updateAccountLink).not.toHaveBeenCalled()
  expect(screen.queryByLabelText('Код из ссылки')).not.toBeInTheDocument()
})

test('recipient confirms once and backend merges both verified identities atomically', async () => {
  jest.mocked(currentAccountPlatform).mockReturnValue('telegram')
  jest.mocked(incomingAccountLink).mockReturnValue(inviteToken)
  jest.mocked(fetchAccountPreviewAccess).mockResolvedValue({
    revision: 1, vk_app_id: 123, telegram_bot_username: 'test_bot',
    telegram_linked: true, linked_platforms: ['telegram'],
  })
  jest.mocked(previewAccountLink).mockResolvedValue(offered)
  jest.mocked(acceptAccountLink).mockResolvedValue({
    ...offered, state: 'committed', revision: 2, target_confirmed: true,
  })
  const onCommitted = jest.fn()
  render(<SharedAccountLinkPreview vkAppId={123} onCommitted={onCommitted} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Подтвердить привязку' }))
  await waitFor(() => expect(acceptAccountLink).toHaveBeenCalledWith(inviteToken, expect.any(AbortSignal), true))
  await waitFor(() => expect(onCommitted).toHaveBeenCalledTimes(1))
  expect(await screen.findByLabelText('Telegram привязан')).toBeInTheDocument()
  expect(screen.getByLabelText('ВКонтакте привязан')).toBeInTheDocument()
})

test('link preview failure does not silently merge and exposes a safe retry', async () => {
  jest.mocked(incomingAccountLink).mockReturnValue(inviteToken)
  jest.mocked(previewAccountLink).mockRejectedValueOnce(new Error('Ссылка истекла или отменена. Создайте новую.'))
    .mockResolvedValue(offered)
  render(<SharedAccountLinkPreview vkAppId={123} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить проверку приглашения' }))
  expect(await screen.findByRole('button', { name: 'Подтвердить привязку' })).toBeEnabled()
  expect(acceptAccountLink).not.toHaveBeenCalled()
  expect(previewAccountLink).toHaveBeenCalledTimes(2)
})

test('source cannot create an invitation without configured destination', async () => {
  jest.mocked(fetchAccountPreviewAccess).mockResolvedValue({
    revision: 1, vk_app_id: null, telegram_bot_username: '', telegram_linked: false,
    linked_platforms: ['telegram'],
  })
  jest.mocked(currentAccountPlatform).mockReturnValue('telegram')
  jest.mocked(accountLinkUrl).mockImplementation(() => { throw new Error('Сначала укажите ID приложения ВК.') })
  render(<SharedAccountLinkPreview vkAppId={null} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Привязать ВКонтакте' }))
  expect(screen.getByText('Сначала укажите ID приложения ВК.')).toBeInTheDocument()
  expect(createAccountLink).not.toHaveBeenCalled()
  expect(window.open).not.toHaveBeenCalled()
})

test('failed status check supports retry without inventing a disconnected account', async () => {
  jest.mocked(fetchAccountPreviewAccess)
    .mockRejectedValueOnce(new Error('Не удалось выполнить запрос. Попробуйте ещё раз.'))
  render(<SharedAccountLinkPreview vkAppId={123} />)
  const card = screen.getByRole('region', { name: 'Связанные аккаунты' })
  const retry = await screen.findByRole('button', { name: 'Повторить проверку' })
  expect(within(card).getAllByText('Статус недоступен')).toHaveLength(2)
  fireEvent.click(retry)
  expect(await screen.findByRole('button', { name: 'Привязать Telegram' })).toBeEnabled()
  expect(fetchAccountPreviewAccess).toHaveBeenCalledTimes(2)
})

test('expired Telegram login keeps recovery link without claiming account is disconnected', async () => {
  jest.mocked(buildTelegramMiniAppUrl).mockReturnValue('')
  jest.mocked(currentAccountPlatform).mockReturnValue('telegram')
  jest.mocked(fetchAccountPreviewAccess).mockRejectedValue(new Error('Откройте приложение заново для подтверждения входа.'))
  render(<SharedAccountLinkPreview vkAppId={null} telegramBotUsername="@configured_bot" />)
  const reopen = await screen.findByRole('link', { name: 'Открыть приложение заново' })
  expect(reopen).toHaveAttribute('href', 'https://t.me/configured_bot?startapp')
  expect(screen.getByRole('region', { name: 'Связанные аккаунты' })).toBeInTheDocument()
  expect(screen.queryByText('Не привязан')).not.toBeInTheDocument()
})

test('stalled account status has a deadline and retry without silently linking', async () => {
  jest.useFakeTimers()
  jest.mocked(fetchAccountPreviewAccess).mockReturnValue(new Promise(() => {}))
  render(<SharedAccountLinkPreview vkAppId={123} />)
  await act(async () => { jest.advanceTimersByTime(15000) })
  expect(screen.getByText('Проверка заняла слишком много времени. Попробуйте ещё раз.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Повторить проверку' })).toBeEnabled()
  expect(jest.mocked(fetchAccountPreviewAccess).mock.calls[0][0]?.aborted).toBe(true)
  expect(createAccountLink).not.toHaveBeenCalled()
})

test('two immediate VK clicks create a single invitation without any popup', async () => {
  let resolveInvitation!: (value: typeof pending) => void
  jest.mocked(createAccountLink).mockReturnValue(new Promise(resolve => { resolveInvitation = resolve }))
  render(<SharedAccountLinkPreview vkAppId={123} />)
  const connect = await screen.findByRole('button', { name: 'Привязать Telegram' })
  fireEvent.click(connect)
  fireEvent.click(connect)
  expect(window.open).not.toHaveBeenCalled()
  expect(createAccountLink).toHaveBeenCalledTimes(1)
  await act(async () => resolveInvitation(pending))
  expect(popup.location.replace).not.toHaveBeenCalled()
  expect(screen.getAllByRole('link', { name: 'Открыть приложение Telegram' })).toHaveLength(1)
})

test('expired pending invitation restores the connect button instead of trapping the user', async () => {
  jest.mocked(createAccountLink).mockResolvedValue(pending)
  jest.mocked(updateAccountLink).mockRejectedValue(new Error('Ссылка истекла или отменена. Создайте новую.'))
  const intervals = jest.spyOn(window, 'setInterval')
  render(<SharedAccountLinkPreview vkAppId={123} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Привязать Telegram' }))
  expect(await screen.findByRole('region', { name: 'Ожидание привязки' })).toBeInTheDocument()
  const poll = intervals.mock.calls.find(([, ms]) => ms === 4000)?.[0]
  expect(poll).toBeDefined()
  await act(async () => { (poll as () => void)(); await Promise.resolve(); await Promise.resolve() })
  expect(screen.getByText('Ссылка истекла. Нажмите «Привязать» ещё раз.')).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Ожидание привязки' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Привязать Telegram' })).toBeEnabled()
})

test('backend without source-consent support fails closed instead of creating a stalled link', async () => {
  jest.mocked(createAccountLink).mockResolvedValue({ ...pending, source_confirmed: false })
  render(<SharedAccountLinkPreview vkAppId={123} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Привязать Telegram' }))
  expect(await screen.findByText('Сервер привязки требует обновления. Попробуйте позже.')).toBeInTheDocument()
  expect(window.open).not.toHaveBeenCalled()
  expect(popup.location.replace).not.toHaveBeenCalled()
  expect(screen.queryByRole('link', { name: 'Открыть приложение Telegram' })).not.toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Ожидание привязки' })).not.toBeInTheDocument()
})
