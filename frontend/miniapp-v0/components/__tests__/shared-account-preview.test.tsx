jest.mock('../shared-commercial-preview', () => ({ SharedCommercialPreview: () => null }))
import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SharedAccountPreview } from '../shared-account-preview'
import { fetchAccountPreviewSettings, saveAccountPreviewSettings, checkAccountPreviewLogin } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchAccountPreviewSettings: jest.fn(),
  saveAccountPreviewSettings: jest.fn(),
  checkAccountPreviewLogin: jest.fn(),
}))
jest.mock('../shared-wallet-preview', () => ({ SharedWalletPreview: () => null }))
jest.mock('../shared-account-link-preview', () => ({ SharedAccountLinkPreview: () => <section aria-label="Связанные аккаунты">Связанные аккаунты</section> }))

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

test('administrator edits VK delivery policy and copy through the audited settings API', async () => {
  const deliveryPolicy = { ...policy, vk_community_id: 456, vk_result_delivery_enabled: false,
    vk_delivery_max_attempts: 3, vk_delivery_retry_seconds: 30, vk_result_message_template: 'Ready {result_url}' }
  jest.mocked(fetchAccountPreviewSettings).mockResolvedValue(deliveryPolicy)
  jest.mocked(saveAccountPreviewSettings).mockResolvedValue({ ...deliveryPolicy, vk_result_delivery_enabled: true, revision: 1 })
  render(<SharedAccountPreview isAdmin />)
  fireEvent.click(screen.getByText('Настройки общих аккаунтов'))
  fireEvent.click(await screen.findByLabelText('Отправлять готовые фото в ВК'))
  fireEvent.change(screen.getByLabelText('Текст сообщения ВК'), { target: { value: 'Your result: {result_url}' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить доступ' }))
  await waitFor(() => expect(saveAccountPreviewSettings).toHaveBeenCalledWith(expect.objectContaining({
    vk_community_id: 456, vk_result_delivery_enabled: true, vk_result_message_template: 'Your result: {result_url}',
  }), 0, expect.any(AbortSignal)))
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

test('an expired settings login cannot hide the linked-account card or leave a loading message', async () => {
  jest.mocked(fetchAccountPreviewSettings).mockRejectedValue(new Error('Откройте приложение заново для подтверждения входа.'))
  render(<SharedAccountPreview isAdmin />)
  fireEvent.click(screen.getByText('Настройки общих аккаунтов'))
  await screen.findByText('Откройте приложение заново для подтверждения входа.')
  expect(screen.getByRole('region', { name: 'Связанные аккаунты' })).toBeInTheDocument()
  expect(screen.queryByText('Загрузка настроек…')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Повторить загрузку настроек' })).toBeEnabled()
})

test('settings can be retried after authorization becomes available', async () => {
  jest.mocked(fetchAccountPreviewSettings).mockRejectedValueOnce(new Error('Вход не подтверждён.')).mockResolvedValueOnce(policy)
  render(<SharedAccountPreview isAdmin />)
  fireEvent.click(screen.getByText('Настройки общих аккаунтов'))
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить загрузку настроек' }))
  expect(await screen.findByLabelText('Доступ администраторам')).toBeInTheDocument()
  expect(screen.queryByText('Вход не подтверждён.')).not.toBeInTheDocument()
})

test('stalled settings stop loading and offer retry after a finite deadline', async () => {
  jest.useFakeTimers()
  try {
    jest.mocked(fetchAccountPreviewSettings).mockReturnValue(new Promise(() => {}))
    render(<SharedAccountPreview isAdmin />)
    fireEvent.click(screen.getByText('Настройки общих аккаунтов'))
    await act(async () => { jest.advanceTimersByTime(15000) })
    expect(screen.queryByText('Загрузка настроек…')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Повторить загрузку настроек' })).toBeEnabled()
    expect(screen.getByRole('region', { name: 'Связанные аккаунты' })).toBeInTheDocument()
    expect(jest.mocked(fetchAccountPreviewSettings).mock.calls[0][0]?.aborted).toBe(true)
  } finally { jest.useRealTimers() }
})
