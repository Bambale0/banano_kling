import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { SharedAccountLinkPreview } from '../shared-account-link-preview'
import { acceptAccountLink, createAccountLink, fetchAccountPreviewAccess, updateAccountLink } from '@/lib/shared-account-api'
import { accountLinkUrl, currentAccountPlatform, incomingAccountLink } from '@/lib/account-platform'
import { buildTelegramMiniAppUrl } from '@/lib/api'

jest.mock('@/lib/api', () => ({ buildTelegramMiniAppUrl: jest.fn(() => 'https://t.me/configured_bot?startapp') }))

jest.mock('@/lib/shared-account-api', () => ({ acceptAccountLink: jest.fn(), createAccountLink: jest.fn(), updateAccountLink: jest.fn(), fetchAccountPreviewAccess: jest.fn() }))
jest.mock('@/lib/account-platform', () => ({
  accountLaunch: () => ({ platform: 'telegram' }),
  currentAccountPlatform: jest.fn(),
  accountLinkUrl: jest.fn(),
  incomingAccountLink: jest.fn(),
}))

const invitation = { id: 'invite1', state: 'awaiting_confirmation' as const, revision: 1, expires_at_epoch: 9999999999, source_confirmed: false, target_confirmed: false }
beforeEach(() => {
  jest.resetAllMocks()
  jest.mocked(incomingAccountLink).mockReturnValue('')
  jest.mocked(currentAccountPlatform).mockReturnValue('telegram')
  jest.mocked(buildTelegramMiniAppUrl).mockReturnValue('https://t.me/configured_bot?startapp')
  jest.mocked(accountLinkUrl).mockImplementation((_platform, token) => 'https://vk.com/app123#link_' + token)
  jest.mocked(fetchAccountPreviewAccess).mockResolvedValue({ revision: 1, vk_app_id: 123, telegram_bot_username: 'test_bot', telegram_linked: false, linked_platforms: ['telegram'] })
})

test('initial card shows real platform statuses and hides the technical form', async () => {
  render(<SharedAccountLinkPreview vkAppId={123} />)
  const card = screen.getByRole('region', { name: 'Связанные аккаунты' })
  expect(within(card).getByText('Telegram')).toBeInTheDocument()
  expect(await within(card).findByText('Не привязан')).toBeInTheDocument()
  expect(within(card).getByText('Привязан')).toBeInTheDocument()
  expect(screen.queryByLabelText('Код из ссылки')).not.toBeInTheDocument()
  expect(createAccountLink).not.toHaveBeenCalled()
  fireEvent.click(within(card).getByRole('button', { name: 'Привязать ВКонтакте' }))
  expect(screen.getByLabelText('Код из ссылки')).toBeInTheDocument()
  expect(createAccountLink).not.toHaveBeenCalled()
})

test('persisted link shows both check marks after reopening', async () => {
  jest.mocked(fetchAccountPreviewAccess).mockResolvedValue({ revision: 1, vk_app_id: 123, telegram_bot_username: 'test_bot', telegram_linked: true, linked_platforms: ['telegram', 'vk'] })
  render(<SharedAccountLinkPreview vkAppId={123} />)
  expect(await screen.findByLabelText('ВКонтакте привязан')).toBeInTheDocument()
  expect(screen.getByLabelText('Telegram привязан')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Привязать/ })).not.toBeInTheDocument()
})

test('VK entry offers to link Telegram', async () => {
  jest.mocked(currentAccountPlatform).mockReturnValue('vk')
  jest.mocked(fetchAccountPreviewAccess).mockResolvedValue({ revision: 1, vk_app_id: 123, telegram_bot_username: 'test_bot', telegram_linked: false, linked_platforms: ['vk'] })
  render(<SharedAccountLinkPreview vkAppId={123} />)
  expect(await screen.findByRole('button', { name: 'Привязать Telegram' })).toBeEnabled()
  expect(screen.getByLabelText('ВКонтакте привязан')).toBeInTheDocument()
})

test('failed status read offers retry without inventing a disconnected account', async () => {
  jest.mocked(fetchAccountPreviewAccess).mockRejectedValueOnce(new Error('Не удалось выполнить запрос. Попробуйте ещё раз.'))
  render(<SharedAccountLinkPreview vkAppId={123} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить проверку' }))
  expect(await screen.findByRole('button', { name: 'Привязать ВКонтакте' })).toBeEnabled()
  expect(fetchAccountPreviewAccess).toHaveBeenCalledTimes(2)
})

test('expired login keeps the card visible and offers the configured Telegram relaunch', async () => {
  jest.mocked(buildTelegramMiniAppUrl).mockReturnValue('')
  jest.mocked(fetchAccountPreviewAccess).mockRejectedValue(new Error('Откройте приложение заново для подтверждения входа.'))
  render(<SharedAccountLinkPreview vkAppId={null} telegramBotUsername="@configured_bot" />)
  const reopen = await screen.findByRole('link', { name: 'Открыть приложение заново' })
  expect(reopen).toHaveAttribute('href', 'https://t.me/configured_bot?startapp')
  expect(screen.getByRole('region', { name: 'Связанные аккаунты' })).toBeInTheDocument()
  expect(screen.queryByText('Не привязан')).not.toBeInTheDocument()
  expect(createAccountLink).not.toHaveBeenCalled()
})

test('linking uses authenticated metadata even when administrator settings are unavailable', async () => {
  jest.mocked(createAccountLink).mockResolvedValue({ ...invitation, state: 'pending', revision: 0, token: 'a'.repeat(43) })
  render(<SharedAccountLinkPreview vkAppId={null} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Привязать ВКонтакте' }))
  fireEvent.click(screen.getByRole('button', { name: 'Создать ссылку' }))
  await screen.findByLabelText('Ссылка для другого аккаунта')
  expect(accountLinkUrl).toHaveBeenLastCalledWith('vk', 'a'.repeat(43), 123, 'test_bot')
})

test('stalled status read has a deadline and a retry action', async () => {
  jest.useFakeTimers()
  try {
    jest.mocked(fetchAccountPreviewAccess).mockReturnValue(new Promise(() => {}))
    render(<SharedAccountLinkPreview vkAppId={123} />)
    await act(async () => { jest.advanceTimersByTime(15000) })
    expect(screen.getByText('Проверка заняла слишком много времени. Попробуйте ещё раз.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Повторить проверку' })).toBeEnabled()
    expect(jest.mocked(fetchAccountPreviewAccess).mock.calls[0][0]?.aborted).toBe(true)
    expect(screen.queryByText('Не привязан')).not.toBeInTheDocument()
  } finally {
    jest.useRealTimers()
  }
})

test('successful explicit linking clears an earlier status error', async () => {
  jest.mocked(incomingAccountLink).mockReturnValue('a'.repeat(43))
  jest.mocked(fetchAccountPreviewAccess).mockRejectedValue(new Error('Статус временно недоступен.'))
  jest.mocked(acceptAccountLink).mockResolvedValue(invitation)
  jest.mocked(updateAccountLink).mockResolvedValue({ ...invitation, state: 'committed', source_confirmed: true, target_confirmed: true })
  const onCommitted = jest.fn()
  render(<SharedAccountLinkPreview vkAppId={123} onCommitted={onCommitted} />)
  await screen.findByText('Статус временно недоступен.')
  fireEvent.click(screen.getByRole('button', { name: 'Принять приглашение' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Подтверждаю связь аккаунтов' }))
  expect(await screen.findByText('Аккаунты связаны.')).toBeInTheDocument()
  expect(screen.getByLabelText('ВКонтакте привязан')).toBeInTheDocument()
  expect(screen.queryByText('Статус временно недоступен.')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Повторить проверку' })).not.toBeInTheDocument()
  expect(onCommitted).toHaveBeenCalledTimes(1)
})

test('opening a link never accepts or confirms without a click', () => {
  jest.mocked(incomingAccountLink).mockReturnValue('a'.repeat(43))
  render(<SharedAccountLinkPreview vkAppId={123} />)
  expect(screen.getByLabelText('Код из ссылки')).toHaveValue('a'.repeat(43))
  expect(acceptAccountLink).not.toHaveBeenCalled()
  expect(updateAccountLink).not.toHaveBeenCalled()
})

test('acceptance displays a separate explicit confirmation with the current revision', async () => {
  jest.mocked(incomingAccountLink).mockReturnValue('a'.repeat(43))
  jest.mocked(acceptAccountLink).mockResolvedValue(invitation)
  jest.mocked(updateAccountLink).mockResolvedValue({ ...invitation, revision: 2, target_confirmed: true })
  render(<SharedAccountLinkPreview vkAppId={123} />)
  fireEvent.click(screen.getByRole('button', { name: 'Принять приглашение' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Подтверждаю связь аккаунтов' }))
  expect(await screen.findByText(/Подтверждение получателя: да/)).toBeInTheDocument()
  expect(screen.queryByLabelText('ВКонтакте привязан')).not.toBeInTheDocument()
  expect(updateAccountLink).toHaveBeenCalledWith(invitation, 'confirm', expect.any(AbortSignal))
})

test('sender can copy the destination URL while waiting for acceptance', async () => {
  jest.mocked(createAccountLink).mockResolvedValue({ ...invitation, state: 'pending', revision: 0, token: 'a'.repeat(43) })
  render(<SharedAccountLinkPreview vkAppId={123} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Привязать ВКонтакте' }))
  fireEvent.click(screen.getByRole('button', { name: 'Создать ссылку' }))
  expect(await screen.findByLabelText('Ссылка для другого аккаунта')).toHaveValue('https://vk.com/app123#link_' + 'a'.repeat(43))
  expect(screen.getByRole('button', { name: 'Подтверждаю связь аккаунтов' })).toBeDisabled()
})

test('expired invitation can be discarded so a new invitation can be created', async () => {
  jest.mocked(incomingAccountLink).mockReturnValue('a'.repeat(43))
  jest.mocked(acceptAccountLink).mockResolvedValue(invitation)
  jest.mocked(updateAccountLink).mockRejectedValue(new Error('Ссылка истекла или отменена. Создайте новую.'))
  render(<SharedAccountLinkPreview vkAppId={123} />)
  fireEvent.click(screen.getByRole('button', { name: 'Принять приглашение' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Обновить статус' }))
  await screen.findByText('Ссылка истекла или отменена. Создайте новую.')
  fireEvent.click(screen.getByRole('button', { name: 'Начать заново' }))
  expect(screen.getByRole('button', { name: 'Создать ссылку' })).toBeEnabled()
  expect(screen.getByLabelText('Код из ссылки')).toHaveValue('')
})
