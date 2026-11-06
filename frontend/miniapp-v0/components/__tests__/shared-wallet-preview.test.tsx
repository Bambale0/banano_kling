import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SharedWalletPreview } from '../shared-wallet-preview'
import { fetchAccountPreviewWallet, applyAccountPreviewWallet, reconcileAccountPreviewWallet } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({ fetchAccountPreviewWallet: jest.fn(), applyAccountPreviewWallet: jest.fn(), reconcileAccountPreviewWallet: jest.fn() }))
const empty = { scope: 'sandbox' as const, balance: { available: '0.0000', reserved: '0.0000', revision: 0 }, entries: [], receipt: null }

beforeEach(() => {
  jest.resetAllMocks()
  jest.mocked(fetchAccountPreviewWallet).mockResolvedValue(empty)
})

test('renders exact sandbox balances', async () => {
  render(<SharedWalletPreview />)
  expect(await screen.findByText('Доступно: 0.0000')).toBeInTheDocument()
  expect(screen.getByText('В резерве: 0.0000')).toBeInTheDocument()
})

test('preserves the same operation key after an uncertain response', async () => {
  jest.mocked(applyAccountPreviewWallet).mockRejectedValueOnce(new Error('Ответ не получен. Повторите проверку.'))
    .mockResolvedValueOnce({ ...empty, balance: { available: '0.1000', reserved: '0.0000', revision: 1 } })
  render(<SharedWalletPreview />)
  await screen.findByText('Доступно: 0.0000')
  fireEvent.change(screen.getByLabelText('Тестовая сумма'), { target: { value: '0.1000' } })
  fireEvent.click(screen.getByRole('button', { name: 'Выполнить проверку' }))
  await screen.findByText('Ответ не получен. Повторите проверку.')
  fireEvent.click(screen.getByRole('button', { name: 'Выполнить проверку' }))
  await screen.findByText('Доступно: 0.1000')
  const calls = jest.mocked(applyAccountPreviewWallet).mock.calls
  expect(calls).toHaveLength(2)
  expect(calls[0][0]).toEqual(expect.objectContaining({ action: 'credit', amount: '0.1000' }))
  expect(calls[0][0].idempotency_key).toBe(calls[1][0].idempotency_key)
})

test('settlement sends the selected reference without numeric rounding', async () => {
  jest.mocked(applyAccountPreviewWallet).mockResolvedValue(empty)
  render(<SharedWalletPreview />)
  await screen.findByText('Доступно: 0.0000')
  fireEvent.change(screen.getByLabelText('Операция кошелька'), { target: { value: 'capture' } })
  fireEvent.change(screen.getByLabelText('Тестовая сумма'), { target: { value: '1.2500' } })
  fireEvent.change(screen.getByLabelText('Ключ резерва или списания'), { target: { value: 'reserve-one' } })
  fireEvent.click(screen.getByRole('button', { name: 'Выполнить проверку' }))
  await waitFor(() => expect(applyAccountPreviewWallet).toHaveBeenCalledWith(expect.objectContaining({ action: 'capture', amount: '1.2500', reference_key: 'reserve-one' }), expect.any(AbortSignal)))
})

test('reconciliation reports drift and refreshes the displayed balance without a mutation', async () => {
  jest.mocked(reconcileAccountPreviewWallet).mockResolvedValue({ scope: 'sandbox', consistent: false, issues: ['available_ledger_mismatch'], ledger_entries: 1, open_reservations: 0, balance: empty.balance })
  render(<SharedWalletPreview />)
  await screen.findByText('Доступно: 0.0000')
  jest.mocked(fetchAccountPreviewWallet).mockResolvedValue({ ...empty, balance: { available: '5.0000', reserved: '0.0000', revision: 2 } })
  fireEvent.click(screen.getByRole('button', { name: 'Сверить журнал' }))
  expect(await screen.findByText('Найдено расхождение. Требуется проверка журнала.')).toBeInTheDocument()
  expect(await screen.findByText('Доступно: 5.0000')).toBeInTheDocument()
  expect(applyAccountPreviewWallet).not.toHaveBeenCalled()
})
