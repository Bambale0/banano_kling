import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { SharedAccountLinkPreview } from '../shared-account-link-preview'
import { acceptAccountLink, createAccountLink, updateAccountLink } from '@/lib/shared-account-api'
import { incomingAccountLink } from '@/lib/account-platform'

jest.mock('@/lib/shared-account-api', () => ({ acceptAccountLink: jest.fn(), createAccountLink: jest.fn(), updateAccountLink: jest.fn() }))
jest.mock('@/lib/account-platform', () => ({
  accountLaunch: () => ({ platform: 'telegram' }),
  accountLinkUrl: (_platform: string, token: string) => 'https://vk.com/app123#link_' + token,
  incomingAccountLink: jest.fn(),
}))

const invitation = { id: 'invite1', state: 'awaiting_confirmation' as const, revision: 1, expires_at_epoch: 9999999999, source_confirmed: false, target_confirmed: false }
beforeEach(() => {
  jest.resetAllMocks()
  jest.mocked(incomingAccountLink).mockReturnValue('')
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
  expect(updateAccountLink).toHaveBeenCalledWith(invitation, 'confirm', expect.any(AbortSignal))
})

test('sender can copy the destination URL while waiting for acceptance', async () => {
  jest.mocked(createAccountLink).mockResolvedValue({ ...invitation, state: 'pending', revision: 0, token: 'a'.repeat(43) })
  render(<SharedAccountLinkPreview vkAppId={123} />)
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
