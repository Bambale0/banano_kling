import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BalanceSheet } from '@/components/balance-sheet'
import { useApp } from '@/lib/app-context'
import { createPayment } from '@/lib/payment-api'
import { bootstrapApp } from '@/lib/api'
import { fetchVkNativeCommerce, createVkInvoice } from '@/lib/shared-account-api'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/account-platform', () => ({ currentAccountPlatform: () => 'vk' }))
jest.mock('@/lib/payment-api', () => ({ createPayment: jest.fn() }))
jest.mock('@/lib/api', () => ({ bootstrapApp: jest.fn(), sendMiniAppClientLog: jest.fn() }))
jest.mock('@/lib/shared-account-api', () => ({
  fetchVkNativeCommerce: jest.fn(), createVkInvoice: jest.fn(),
}))

const fixture = {
  state: {
    mode: 'live', user: { credits: 3 }, recentTasks: [],
    // This Telegram-only package must NEVER be used for native VK checkout.
    paymentPackages: [{ id: 'telegram', name: 'TG пакет', credits: 100,
      price_rub: 1000, lava_offer_id: 'tg-offer' }],
  },
  isBalanceOpen: true, closeBalance: jest.fn(), refreshTasks: jest.fn(),
  refreshBalance: jest.fn(), balanceRequest: { packageId: 'telegram', requiredCredits: 50 },
}
const vkCommerce = {
  ok: true, registered: true, balance: 3, payments_enabled: true,
  payment_packages: [
    { id: '250', credits: 25, price_rub: 250, lava_offer_id: 'vk-offer',
      methods: ['lava_card', 'lava_sbp'] },
  ],
  payments: [], referrals: { first_level_count: 0, second_level_count: 0, earned_rub: 0 },
}

beforeEach(() => {
  jest.clearAllMocks()
  ;(useApp as jest.Mock).mockReturnValue(fixture)
  ;(fetchVkNativeCommerce as jest.Mock).mockResolvedValue(vkCommerce)
  ;(createVkInvoice as jest.Mock).mockResolvedValue({
    ok: true, status: 'ready', amount_rub: 250, credits: 25,
    payment_url: 'https://lava.top/pay/native-test',
  })
})

it('uses the real VK commerce and native invoice, never the Telegram payment route', async () => {
  render(<BalanceSheet />)
  expect(fetchVkNativeCommerce).toHaveBeenCalledTimes(1)
  expect(await screen.findByRole('form', { name: 'Пополнение VK-баланса' })).toBeInTheDocument()
  expect(screen.queryByText('TG пакет')).not.toBeInTheDocument()
  expect(screen.queryByText(/Welcome-бонус/)).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Stars/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Купить 100/ })).not.toBeInTheDocument()

  fireEvent.change(screen.getByRole('textbox', { name: 'Email для чека' }), {
    target: { value: 'payer@example.test' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Получить ссылку на оплату' }))
  await waitFor(() => expect(createVkInvoice).toHaveBeenCalledTimes(1))
  expect(createVkInvoice).toHaveBeenCalledWith(expect.objectContaining({
    package_id: '250', payment_method: 'CARD', customer_email: 'payer@example.test',
    client_request_id: expect.any(String),
  }))
  expect(createPayment).not.toHaveBeenCalled()
  expect(bootstrapApp).not.toHaveBeenCalled()
  expect(await screen.findByRole('link', { name: 'Перейти к оплате Lava' }))
    .toHaveAttribute('href', 'https://lava.top/pay/native-test')
})

it('fails closed when both native payment gates have not been accepted', async () => {
  ;(fetchVkNativeCommerce as jest.Mock).mockResolvedValue({
    ...vkCommerce, payments_enabled: false,
  })
  render(<BalanceSheet />)
  expect(await screen.findByText(/Пополнение ВКонтакте временно недоступно/))
    .toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Карта|СБП|Stars|Купить/ }))
    .not.toBeInTheDocument()
  expect(createPayment).not.toHaveBeenCalled()
  expect(createVkInvoice).not.toHaveBeenCalled()
})

it('fails closed when native actor commerce cannot be verified', async () => {
  ;(fetchVkNativeCommerce as jest.Mock).mockRejectedValue(new Error('private transport diagnostics'))
  render(<BalanceSheet />)
  expect(await screen.findByRole('alert'))
    .toHaveTextContent('Не удалось проверить оплату ВКонтакте')
  expect(screen.queryByText('private transport diagnostics')).not.toBeInTheDocument()
  expect(createPayment).not.toHaveBeenCalled()
})


it('reopens a failed VK checkout with the identical idempotency claim, not a second order', async () => {
  ;(createVkInvoice as jest.Mock)
    .mockRejectedValueOnce(new Error('provider outcome unknown'))
    .mockResolvedValueOnce({
      ok: true, status: 'ready', amount_rub: 250, credits: 25,
      payment_url: 'https://lava.top/pay/native-test',
    })
  const { rerender } = render(<BalanceSheet />)
  expect(await screen.findByRole('form', { name: 'Пополнение VK-баланса' })).toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox', { name: 'Email для чека' }), {
    target: { value: 'payer@example.test' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Получить ссылку на оплату' }))
  await waitFor(() => expect(createVkInvoice).toHaveBeenCalledTimes(1))
  expect(await screen.findByRole('alert')).toHaveTextContent('provider outcome unknown')
  const originalClaim = (createVkInvoice as jest.Mock).mock.calls[0][0].client_request_id

  ;(useApp as jest.Mock).mockReturnValue({ ...fixture, isBalanceOpen: false })
  rerender(<BalanceSheet />)
  ;(useApp as jest.Mock).mockReturnValue(fixture)
  rerender(<BalanceSheet />)
  expect(await screen.findByRole('form', { name: 'Пополнение VK-баланса' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Получить ссылку на оплату' }))
  await waitFor(() => expect(createVkInvoice).toHaveBeenCalledTimes(2))
  expect((createVkInvoice as jest.Mock).mock.calls[1][0].client_request_id).toBe(originalClaim)
  expect(createPayment).not.toHaveBeenCalled()
})
