import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SharedAccountPreview } from '../shared-account-preview'
import { createAccountLink, fetchAccountPreviewAccess, fetchAccountPreviewSettings, type AccountPreviewSettings } from '@/lib/shared-account-api'

jest.mock('../shared-wallet-preview', () => ({ SharedWalletPreview: () => null }))
jest.mock('../shared-commercial-preview', () => ({ SharedCommercialPreview: () => null }))
jest.mock('@/lib/shared-account-api', () => ({
  fetchAccountPreviewSettings: jest.fn(), fetchAccountPreviewAccess: jest.fn(),
  createAccountLink: jest.fn(), acceptAccountLink: jest.fn(), updateAccountLink: jest.fn(),
  saveAccountPreviewSettings: jest.fn(), checkAccountPreviewLogin: jest.fn(),
}))

test('late administrator settings cannot reset an invitation already created through the real linking component', async () => {
  const policy: AccountPreviewSettings = { enabled: true, revision: 1, vk_app_id: 123, vk_admin_ids: [], session_ttl_seconds: 3600, launch_max_age_seconds: 600 }
  let resolveSettings!: (value: AccountPreviewSettings) => void
  jest.mocked(fetchAccountPreviewSettings).mockReturnValue(new Promise(resolve => { resolveSettings = resolve }))
  jest.mocked(fetchAccountPreviewAccess).mockResolvedValue({ revision: 1, vk_app_id: 123, telegram_bot_username: 'test_bot', telegram_linked: true, linked_platforms: ['telegram'] })
  jest.mocked(createAccountLink).mockResolvedValue({ id: 'pending-invite', state: 'pending', revision: 0, expires_at_epoch: 9999999999, token: 'a'.repeat(43) })

  render(<SharedAccountPreview isAdmin />)
  fireEvent.click(await screen.findByRole('button', { name: 'Привязать ВКонтакте' }))
  fireEvent.click(screen.getByRole('button', { name: 'Создать ссылку' }))
  const expectedUrl = 'https://vk.com/app123#link_' + 'a'.repeat(43)
  expect(await screen.findByLabelText('Ссылка для другого аккаунта')).toHaveValue(expectedUrl)

  await act(async () => { resolveSettings(policy) })
  await waitFor(() => expect(fetchAccountPreviewAccess).toHaveBeenCalledTimes(2))
  expect(screen.getByLabelText('Ссылка для другого аккаунта')).toHaveValue(expectedUrl)
  expect(screen.getByRole('button', { name: 'Подтверждаю связь аккаунтов' })).toBeDisabled()
  expect(createAccountLink).toHaveBeenCalledTimes(1)
})
