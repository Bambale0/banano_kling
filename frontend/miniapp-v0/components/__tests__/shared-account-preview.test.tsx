jest.mock('../shared-commercial-preview', () => ({ SharedCommercialPreview: () => null }))
import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SharedAccountPreview } from '../shared-account-preview'
import { fetchAccountPreviewSettings, saveAccountPreviewSettings, checkAccountPreviewLogin } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchAccountPreviewSettings: jest.fn(),
  saveAccountPreviewSettings: jest.fn(),
  checkAccountPreviewLogin: jest.fn(),
}))
jest.mock('../shared-wallet-preview', () => ({ SharedWalletPreview: () => null }))
jest.mock('../shared-account-link-preview', () => ({ SharedAccountLinkPreview: () => null }))

const policy = { enabled: false, revision: 0, vk_app_id: null, vk_admin_ids: [], session_ttl_seconds: 3600, launch_max_age_seconds: 600 }

beforeEach(() => {
  jest.resetAllMocks()
  jest.mocked(fetchAccountPreviewSettings).mockResolvedValue(policy)
})

test('ordinary user sees no preview controls and makes no preview request', () => {
  const { container } = render(<SharedAccountPreview isAdmin={false} />)
  expect(container).toBeEmptyDOMElement()
  expect(fetchAccountPreviewSettings).not.toHaveBeenCalled()
})

test('administrator can enable access only for administrators', async () => {
  jest.mocked(saveAccountPreviewSettings).mockResolvedValue({ ...policy, enabled: true, revision: 1 })
  render(<SharedAccountPreview isAdmin />)
  fireEvent.click(screen.getByText('Настройки общих аккаунтов'))
  const toggle = await screen.findByLabelText('Доступ администраторам')
  fireEvent.click(toggle)
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить доступ' }))
  await waitFor(() => expect(saveAccountPreviewSettings).toHaveBeenCalledWith(expect.objectContaining({ enabled: true }), 0, expect.any(AbortSignal)))
  expect(await screen.findByText('Настройки сохранены.')).toBeInTheDocument()
})

test('administrator can check login without exposing session credentials', async () => {
  jest.mocked(fetchAccountPreviewSettings).mockResolvedValue({ ...policy, enabled: true })
  jest.mocked(checkAccountPreviewLogin).mockResolvedValue(undefined)
  render(<SharedAccountPreview isAdmin />)
  fireEvent.click(screen.getByText('Настройки общих аккаунтов'))
  fireEvent.click(await screen.findByRole('button', { name: 'Проверить вход' }))
  expect(await screen.findByText('Вход подтверждён.')).toBeInTheDocument()
  expect(checkAccountPreviewLogin).toHaveBeenCalledTimes(1)
})

test('a stale configuration asks the administrator to reload', async () => {
  jest.mocked(saveAccountPreviewSettings).mockRejectedValue(new Error('Настройки изменились. Обновите страницу.'))
  render(<SharedAccountPreview isAdmin />)
  fireEvent.click(screen.getByText('Настройки общих аккаунтов'))
  await screen.findByLabelText('Доступ администраторам')
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить доступ' }))
  expect(await screen.findByText('Настройки изменились. Обновите страницу.')).toBeInTheDocument()
})
