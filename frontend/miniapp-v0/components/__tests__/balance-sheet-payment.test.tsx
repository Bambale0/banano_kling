import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BalanceSheet } from '@/components/balance-sheet'
import { useApp } from '@/lib/app-context'
import { createPayment } from '@/lib/payment-api'
import { bootstrapApp, sendMiniAppClientLog } from '@/lib/api'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/payment-api', () => ({ createPayment: jest.fn() }))
jest.mock('@/lib/api', () => ({ bootstrapApp: jest.fn(), sendMiniAppClientLog: jest.fn() }))

const exactUrl = 'https://auth.robokassa.ru/Merchant/Index.aspx?InvId=9007199254740993123&Receipt=%257B%2522items%2522%253A%255B%255D%257D&SignatureValue=synthetic'
const openLink = jest.fn()
const fixture = { state: { mode: 'live', user: { credits: 1 }, recentTasks: [], paymentPackages: [
  { id: 'start', name: 'Старт', credits: 50, price_rub: 500, robokassa_enabled: true },
] }, isBalanceOpen: true, closeBalance: jest.fn(), refreshTasks: jest.fn() }

beforeEach(() => {
  jest.clearAllMocks()
  openLink.mockReset()
  ;(useApp as jest.Mock).mockReturnValue(fixture)
  ;(bootstrapApp as jest.Mock).mockResolvedValue({})
  ;(createPayment as jest.Mock).mockResolvedValue({ ok: true, provider: 'robokassa', order_id: '9007199254740993123', credits: 50, payment_url: exactUrl })
  Object.assign(window.Telegram!.WebApp!, { platform: 'ios', openLink })
})

it('opens an iPhone checkout externally on a fresh tap and reuses the exact signed URL', async () => {
  render(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: 'СБП / карта' }))
  const proceed = await screen.findByRole('link', { name: 'Перейти к оплате' })
  expect(openLink).not.toHaveBeenCalled()
  expect(screen.getByRole('region', { name: 'Готовый счёт' })).toHaveTextContent('500 ₽')
  expect(proceed).toHaveAttribute('href', exactUrl)
  fireEvent.click(proceed)
  expect(openLink).toHaveBeenCalledWith(exactUrl)
  fireEvent.click(proceed)
  expect(openLink).toHaveBeenCalledTimes(2)
  expect(createPayment).toHaveBeenCalledTimes(1)
})

it('keeps a direct retry after an Android bridge silently ignores the async open', async () => {
  Object.assign(window.Telegram!.WebApp!, { platform: 'android' })
  render(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: 'СБП / карта' }))
  await waitFor(() => expect(openLink).toHaveBeenCalledWith(exactUrl))
  fireEvent.click(await screen.findByRole('link', { name: 'Перейти к оплате' }))
  expect(openLink).toHaveBeenCalledTimes(2)
  expect(createPayment).toHaveBeenCalledTimes(1)
})

it('does not show a checkout when creation fails', async () => {
  ;(createPayment as jest.Mock).mockRejectedValue(new Error('Unavailable'))
  render(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: 'СБП / карта' }))
  await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(1))
  expect(screen.queryByRole('link', { name: 'Перейти к оплате' })).not.toBeInTheDocument()
  expect(openLink).not.toHaveBeenCalled()
})


it('falls back to a native external anchor when Telegram has no bridge', async () => {
  Object.assign(window.Telegram!.WebApp!, { openLink: undefined })
  render(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: 'СБП / карта' }))
  const proceed = await screen.findByRole('link', { name: 'Перейти к оплате' })
  expect(proceed).toHaveAttribute('href', exactUrl)
  expect(proceed).toHaveAttribute('target', '_blank')
  expect(proceed).toHaveAttribute('rel', 'noopener noreferrer')
})

it('leaves the native anchor action available if Telegram throws', async () => {
  openLink.mockImplementation(() => { throw new Error('Bridge unavailable') })
  render(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: 'СБП / карта' }))
  const proceed = await screen.findByRole('link', { name: 'Перейти к оплате' })
  const click = new MouseEvent('click', { bubbles: true, cancelable: true })
  fireEvent(proceed, click)
  expect(click.defaultPrevented).toBe(false)
  expect(createPayment).toHaveBeenCalledTimes(1)
  expect(sendMiniAppClientLog).toHaveBeenLastCalledWith('payment-checkout-open-requested', {
    message: 'provider=robokassa order_id=9007199254740993123 method=browser-link-fallback',
  })
})

it('does not open a late checkout response after the balance sheet closes', async () => {
  Object.assign(window.Telegram!.WebApp!, { platform: 'android' })
  let resolvePayment!: (value: unknown) => void
  ;(createPayment as jest.Mock).mockImplementation(() => new Promise(resolve => { resolvePayment = resolve }))
  const { rerender } = render(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: 'СБП / карта' }))
  ;(useApp as jest.Mock).mockReturnValue({ ...fixture, isBalanceOpen: false })
  rerender(<BalanceSheet />)
  resolvePayment({ ok: true, provider: 'robokassa', order_id: 'fixture', credits: 50, payment_url: exactUrl })
  await waitFor(() => expect(sendMiniAppClientLog).toHaveBeenCalledWith('payment-checkout-ready', expect.anything()))
  expect(openLink).not.toHaveBeenCalled()
})

it('keeps Telegram Stars on the native invoice flow', async () => {
  const openInvoice = jest.fn((_url, callback) => callback('cancelled'))
  Object.assign(window.Telegram!.WebApp!, { openInvoice })
  ;(createPayment as jest.Mock).mockResolvedValue({ ok: true, provider: 'telegram_stars', invoice_url: 'https://t.me/$synthetic', credits: 50 })
  render(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: /Stars/ }))
  await waitFor(() => expect(openInvoice).toHaveBeenCalled())
  expect(openLink).not.toHaveBeenCalled()
  expect(screen.queryByRole('link', { name: 'Перейти к оплате' })).not.toBeInTheDocument()
})
