import '@testing-library/jest-dom'
import { act, render, screen } from '@testing-library/react'
import { SharedAccountPreview } from '../shared-account-preview'
import { fetchAccountPreviewSettings, type AccountPreviewSettings } from '@/lib/shared-account-api'
import { getInitData } from '@/lib/api'

jest.mock('../shared-wallet-preview', () => ({ SharedWalletPreview: () => null }))
jest.mock('../shared-commercial-preview', () => ({ SharedCommercialPreview: () => null }))
jest.mock('@/lib/api', () => ({ getInitData: jest.fn() }))
jest.mock('@/lib/shared-account-api', () => ({
  fetchAccountPreviewSettings: jest.fn(),
  saveAccountPreviewSettings: jest.fn(), checkAccountPreviewLogin: jest.fn(),
}))

test('late admin settings cannot replace verified web identities with obsolete VK linking', async () => {
  const policy: AccountPreviewSettings = {
    enabled: true, revision: 1, vk_app_id: 123, vk_admin_ids: [],
    session_ttl_seconds: 3600, launch_max_age_seconds: 600,
  }
  let resolveSettings!: (value: AccountPreviewSettings) => void
  jest.mocked(fetchAccountPreviewSettings).mockReturnValue(
    new Promise(resolve => { resolveSettings = resolve }),
  )
  jest.mocked(getInitData).mockReturnValue('')
  const fetchOwner = jest.fn().mockResolvedValue({
    ok: true, status: 200, json: async () => ({
      ok: true, authenticated: true, connected: ['telegram', 'yandex'],
      providers: { yandex: true, google: false, email: false },
    }),
  })
  const priorFetch = global.fetch
  global.fetch = fetchOwner as typeof fetch
  try {
    render(<SharedAccountPreview isAdmin />)
    expect(await screen.findByLabelText('Яндекс ID привязан')).toBeInTheDocument()
    expect(screen.queryByText('ВКонтакте')).not.toBeInTheDocument()
    await act(async () => { resolveSettings(policy) })
    expect(screen.getByLabelText('Яндекс ID привязан')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Привязать ВКонтакте' })).not.toBeInTheDocument()
    expect(fetchOwner).toHaveBeenCalledTimes(1)
  } finally {
    global.fetch = priorFetch
  }
})
