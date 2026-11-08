import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SharedAccountPreview } from '../shared-account-preview'
import { createAccountLink, fetchAccountPreviewAccess, fetchAccountPreviewSettings, type AccountPreviewSettings } from '@/lib/shared-account-api'

jest.mock('../shared-wallet-preview', () => ({ SharedWalletPreview: () => null }))
jest.mock('../shared-commercial-preview', () => ({ SharedCommercialPreview: () => null }))
jest.mock('@/lib/shared-account-api', () => ({
  fetchAccountPreviewSettings: jest.fn(), fetchAccountPreviewAccess: jest.fn(),
  createAccountLink: jest.fn(), acceptAccountLink: jest.fn(), previewAccountLink: jest.fn(), updateAccountLink: jest.fn(),
  saveAccountPreviewSettings: jest.fn(), checkAccountPreviewLogin: jest.fn(),
}))

test('late administrator settings cannot reset an invitation already created through the real linking component', async () => {
  const policy: AccountPreviewSettings = { enabled: true, revision: 1, vk_app_id: 123, vk_admin_ids: [], session_ttl_seconds: 3600, launch_max_age_seconds: 600 }
  let resolveSettings!: (value: AccountPreviewSettings) => void
  jest.mocked(fetchAccountPreviewSettings).mockReturnValue(new Promise(resolve => { resolveSettings = resolve }))
  jest.mocked(fetchAccountPreviewAccess).mockResolvedValue({ revision: 1, vk_app_id: 123, telegram_bot_username: 'test_bot', telegram_linked: true, linked_platforms: ['telegram'] })
  jest.mocked(createAccountLink).mockResolvedValue({ id: 'pending-invite', state: 'pending', revision: 0, expires_at_epoch: 9999999999, source_confirmed: true, token: 'a'.repeat(43) })

  const popup = {
    opener: window, closed: false, document: { title: '' },
    location: { replace: jest.fn() }, close: jest.fn(),
  }
  const open = jest.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
  try {
    render(<SharedAccountPreview isAdmin />)
    fireEvent.click(await screen.findByRole('button', { name: 'Привязать ВКонтакте' }))
    const expectedUrl = 'https://vk.com/app123#link_' + 'a'.repeat(43)
    await waitFor(() => expect(popup.location.replace).toHaveBeenCalledWith(expectedUrl))
    expect(screen.getByRole('region', { name: 'Ожидание привязки' })).toBeInTheDocument()

    await act(async () => { resolveSettings(policy) })
    await waitFor(() => expect(fetchAccountPreviewAccess).toHaveBeenCalledTimes(2))
    expect(screen.getByRole('region', { name: 'Ожидание привязки' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Код из ссылки')).not.toBeInTheDocument()
    expect(createAccountLink).toHaveBeenCalledWith('vk', expect.any(AbortSignal), true)
    expect(createAccountLink).toHaveBeenCalledTimes(1)
  } finally {
    open.mockRestore()
  }
})
