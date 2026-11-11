import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BalanceSheet } from '@/components/balance-sheet'
import { useApp } from '@/lib/app-context'
import { createPayment } from '@/lib/payment-api'
import { bootstrapApp, sendMiniAppClientLog } from '@/lib/api'
import { toast } from 'sonner'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/payment-api', () => ({ createPayment: jest.fn() }))
jest.mock('@/lib/api', () => ({ bootstrapApp: jest.fn(), sendMiniAppClientLog: jest.fn() }))

const exactUrl = 'https://gate.lava.top/pay/fixture-9007199254740993123?order=fixture&signature=synthetic'
const openLink = jest.fn()
const fixture = { state: { mode: 'live', user: { credits: 1 }, recentTasks: [], paymentPackages: [
  { id: 'start', name: 'Старт', credits: 50, price_rub: 500, robokassa_enabled: true, lava_offer_id: 'configured-offer' },
] }, isBalanceOpen: true, closeBalance: jest.fn(), refreshTasks: jest.fn(), refreshBalance: jest.fn() }

beforeEach(() => {
  window.history.replaceState({}, '', '/')
  jest.clearAllMocks()
  openLink.mockReset()
  ;(useApp as jest.Mock).mockReturnValue(fixture)
  ;(bootstrapApp as jest.Mock).mockResolvedValue({})
  ;(createPayment as jest.Mock).mockResolvedValue({ ok: true, provider: 'lava_card', order_id: '9007199254740993123', credits: 50, payment_url: exactUrl })
  Object.assign(window.Telegram!.WebApp!, { platform: 'ios', openLink })
})

it('opens an iPhone checkout externally on a fresh tap and reuses the exact signed URL', async () => {
  render(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: 'Карта' }))
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
  fireEvent.click(screen.getByRole('button', { name: 'Карта' }))
  await waitFor(() => expect(openLink).toHaveBeenCalledWith(exactUrl))
  fireEvent.click(await screen.findByRole('link', { name: 'Перейти к оплате' }))
  expect(openLink).toHaveBeenCalledTimes(2)
  expect(createPayment).toHaveBeenCalledTimes(1)
})

it('does not show a checkout when creation fails', async () => {
  ;(createPayment as jest.Mock).mockRejectedValue(new Error('Unavailable'))
  render(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: 'Карта' }))
  await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(1))
  expect(screen.queryByRole('link', { name: 'Перейти к оплате' })).not.toBeInTheDocument()
  expect(openLink).not.toHaveBeenCalled()
})


it('falls back to a native external anchor when Telegram has no bridge', async () => {
  Object.assign(window.Telegram!.WebApp!, { openLink: undefined })
  render(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: 'Карта' }))
  const proceed = await screen.findByRole('link', { name: 'Перейти к оплате' })
  expect(proceed).toHaveAttribute('href', exactUrl)
  expect(proceed).toHaveAttribute('target', '_blank')
  expect(proceed).toHaveAttribute('rel', 'noopener noreferrer')
})

it('leaves the native anchor action available if Telegram throws', async () => {
  openLink.mockImplementation(() => { throw new Error('Bridge unavailable') })
  render(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: 'Карта' }))
  const proceed = await screen.findByRole('link', { name: 'Перейти к оплате' })
  const click = new MouseEvent('click', { bubbles: true, cancelable: true })
  fireEvent(proceed, click)
  expect(click.defaultPrevented).toBe(false)
  expect(createPayment).toHaveBeenCalledTimes(1)
  expect(sendMiniAppClientLog).toHaveBeenLastCalledWith('payment-checkout-open-requested', {
    message: 'provider=lava_card order_id=9007199254740993123 method=browser-link-fallback',
  })
})

it('does not open a late checkout response after the balance sheet closes', async () => {
  Object.assign(window.Telegram!.WebApp!, { platform: 'android' })
  let resolvePayment!: (value: unknown) => void
  ;(createPayment as jest.Mock).mockImplementation(() => new Promise(resolve => { resolvePayment = resolve }))
  const { rerender } = render(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: 'Карта' }))
  ;(useApp as jest.Mock).mockReturnValue({ ...fixture, isBalanceOpen: false })
  rerender(<BalanceSheet />)
  await act(async () => {
    resolvePayment({ ok: true, provider: 'lava_card', order_id: 'fixture', credits: 50, payment_url: exactUrl })
  })
  expect(openLink).not.toHaveBeenCalled()
  expect(sendMiniAppClientLog).not.toHaveBeenCalledWith('payment-checkout-ready', expect.anything())

  // A pending checkout from a closed repeat must not reappear later.
  ;(useApp as jest.Mock).mockReturnValue(fixture)
  rerender(<BalanceSheet />)
  expect(screen.queryByRole('link', { name: 'Перейти к оплате' })).not.toBeInTheDocument()
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


it('puts the recommended package first without exposing hidden Robokassa', () => {
  ;(useApp as jest.Mock).mockReturnValue({
    ...fixture,
    balanceRequest: { packageId: 'pro', requiredCredits: 50 },
    state: {
      ...fixture.state,
      paymentPackages: [
        { id: 'start', name: 'Старт', credits: 50, price_rub: 500, robokassa_enabled: true, lava_offer_id: 'configured-offer' },
        { id: 'pro', name: 'Про', credits: 100, price_rub: 1000, robokassa_enabled: true, lava_offer_id: 'configured-offer' },
      ],
    },
  })
  render(<BalanceSheet />)
  expect(screen.getByRole('region', { name: 'Пополнение для повтора' })).toHaveTextContent('нужно 50🍌')
  expect(screen.getByText('Для вашего видео')).toBeInTheDocument()
  const first = screen.getByRole('heading', { name: 'Про' })
  const second = screen.getByRole('heading', { name: 'Старт' })
  expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.getAllByRole('button', { name: 'Карта' })).toHaveLength(2)
  expect(screen.queryByText(/Robokassa/)).not.toBeInTheDocument()
})

it('offers explicit return to the unchanged repeat only once wallet funds cover its cost', () => {
  ;(useApp as jest.Mock).mockReturnValue({
    ...fixture,
    balanceRequest: { packageId: 'start', requiredCredits: 50 },
  })
  const { rerender } = render(<BalanceSheet />)
  expect(screen.queryByRole('button', { name: 'Вернуться к видео' })).not.toBeInTheDocument()

  ;(useApp as jest.Mock).mockReturnValue({
    ...fixture,
    balanceRequest: { packageId: 'start', requiredCredits: 50 },
    state: { ...fixture.state, user: { credits: 51 } },
  })
  rerender(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: 'Вернуться к видео' }))
  expect(fixture.closeBalance).toHaveBeenCalledTimes(1)
})

it('explains an automatic repeat shortage and starts its configured checkout', async () => {
  ;(useApp as jest.Mock).mockReturnValue({
    ...fixture,
    balanceRequest: { packageId: 'start', requiredCredits: 50, reason: 'video-repeat' },
    state: { ...fixture.state, user: { credits: 12 } },
  })
  render(<BalanceSheet />)

  const region = screen.getByRole('region', { name: 'Пополнение для повтора' })
  expect(region).toHaveTextContent('Для повтора нужно 50🍌')
  expect(region).toHaveTextContent('На балансе 12🍌')
  expect(region).toHaveTextContent('Не хватает 38🍌')
  expect(region).toHaveTextContent('Подойдёт пакет «Старт»: 50🍌 за 500 ₽')
  fireEvent.click(screen.getByRole('button', { name: 'Купить 50🍌 за 500 ₽' }))
  await waitFor(() => expect(createPayment).toHaveBeenCalledWith(expect.objectContaining({
    packageId: 'start', provider: 'lava_card',
  })))
  expect(screen.getByRole('button', { name: 'Выбрать другой пакет' })).toBeInTheDocument()
})

it('shows Stars for a Stars-only automatic repeat package', async () => {
  ;(useApp as jest.Mock).mockReturnValue({
    ...fixture,
    balanceRequest: { packageId: 'stars', requiredCredits: 50, reason: 'video-repeat' },
    state: { ...fixture.state, user: { credits: 0 }, paymentPackages: [
      { id: 'stars', name: 'Stars', credits: 50, price_rub: 500, price_stars: 650 },
    ] },
  })
  ;(createPayment as jest.Mock).mockResolvedValue({
    ok: true, provider: 'telegram_stars', invoice_url: 'https://t.me/$synthetic', credits: 50,
  })
  const openInvoice = jest.fn((_url, callback) => callback('cancelled'))
  Object.assign(window.Telegram!.WebApp!, { openInvoice })

  render(<BalanceSheet />)
  fireEvent.click(screen.getByRole('button', { name: 'Купить 50🍌 за 650 ⭐' }))
  await waitFor(() => expect(createPayment).toHaveBeenCalledWith(expect.objectContaining({
    packageId: 'stars', provider: 'telegram_stars',
  })))
})


it('keeps paid Stars confirmation separate from a failed authenticated balance refresh', async () => {
  const refreshBalance = jest.fn().mockRejectedValue(new Error('Temporary bootstrap timeout'))
  const refreshTasks = jest.fn()
  ;(useApp as jest.Mock).mockReturnValue({ ...fixture, refreshBalance, refreshTasks })
  ;(createPayment as jest.Mock).mockResolvedValue({
    ok: true, provider: 'telegram_stars', invoice_url: 'https://t.me/$synthetic', credits: 50,
  })
  const openInvoice = jest.fn((_url: string, callback: (status: string) => void) => callback('paid'))
  Object.assign(window.Telegram!.WebApp!, { openInvoice })
  const errorSpy = jest.spyOn(toast, 'error')
  const noticeSpy = jest.spyOn(toast, 'message')
  const successSpy = jest.spyOn(toast, 'success')
  render(<BalanceSheet />)

  fireEvent.click(screen.getByRole('button', { name: /Stars/ }))
  await waitFor(() => expect(refreshBalance).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(noticeSpy).toHaveBeenCalledWith(
    expect.stringContaining('Платёж подтверждён'), expect.anything(),
  ))
  expect(successSpy).toHaveBeenCalledWith('Оплата Stars прошла', expect.anything())
  expect(refreshTasks).not.toHaveBeenCalled()
  expect(errorSpy).not.toHaveBeenCalled()
  errorSpy.mockRestore()
  noticeSpy.mockRestore()
  successSpy.mockRestore()
})

it('keeps a user-clickable native Stars link if both Telegram and popup bridges fail', async () => {
  Object.assign(window.Telegram!.WebApp!, { platform: 'android', openLink: undefined, openInvoice: undefined })
  ;(createPayment as jest.Mock).mockResolvedValue({
    ok: true, provider: 'telegram_stars', invoice_url: 'https://t.me/$synthetic', credits: 50,
  })
  const popup = jest.spyOn(window, 'open').mockReturnValue(null)
  render(<BalanceSheet />)

  fireEvent.click(screen.getByRole('button', { name: /Stars/ }))
  const manual = await screen.findByRole('region', { name: 'Ссылка на оплату' })
  expect(manual).toBeInTheDocument()
  const link = screen.getByRole('link', { name: 'Перейти к оплате' })
  expect(link).toHaveAttribute('href', 'https://t.me/$synthetic')
  expect(link).toHaveAttribute('target', '_blank')
  expect(createPayment).toHaveBeenCalledTimes(1)
  popup.mockRestore()
})

it('keeps a Tribute fallback link in the same WebView without issuing a duplicate invoice', async () => {
  Object.assign(window.Telegram!.WebApp!, { platform: 'android', openLink: undefined, openInvoice: undefined })
  const popup = jest.spyOn(window, 'open').mockReturnValue(null)
  render(<BalanceSheet />)

  fireEvent.click(screen.getByRole('button', { name: 'Зарубежная / СНГ' }))
  const link = await screen.findByRole('link', { name: 'Перейти к оплате' })
  expect(link).toHaveAttribute('href', 'https://web.tribute.tg/p/Dxn')
  expect(link).toHaveAttribute('target', '_blank')
  expect(createPayment).not.toHaveBeenCalled()
  popup.mockRestore()
})


it('discards a late Stars invoice and never reopens checkout after the user closed it', async () => {
  let resolvePayment!: (value: unknown) => void
  ;(createPayment as jest.Mock).mockImplementation(() => new Promise(resolve => { resolvePayment = resolve }))
  const openInvoice = jest.fn((_url: string, callback: (status: string) => void) => callback('cancelled'))
  Object.assign(window.Telegram!.WebApp!, { openInvoice, openLink: undefined })
  const { rerender } = render(<BalanceSheet />)

  fireEvent.click(screen.getByRole('button', { name: /Stars/ }))
  ;(useApp as jest.Mock).mockReturnValue({ ...fixture, isBalanceOpen: false })
  rerender(<BalanceSheet />)
  await act(async () => {
    resolvePayment({
      ok: true, provider: 'telegram_stars',
      invoice_url: 'https://t.me/$stale-synthetic', credits: 50,
    })
  })
  expect(openInvoice).not.toHaveBeenCalled()
  expect(screen.queryByRole('region', { name: 'Ссылка на оплату' })).not.toBeInTheDocument()

  ;(useApp as jest.Mock).mockReturnValue(fixture)
  rerender(<BalanceSheet />)
  expect(screen.queryByRole('link', { name: 'Перейти к оплате' })).not.toBeInTheDocument()
})

it('scrolls the manual payment fallback into view even when checkout was selected below the fold', async () => {
  const oldDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView')
  const scroll = jest.fn()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scroll })
  try {
    Object.assign(window.Telegram!.WebApp!, {
      platform: 'android', openInvoice: undefined, openLink: undefined,
    })
    const popup = jest.spyOn(window, 'open').mockReturnValue(null)
    ;(createPayment as jest.Mock).mockResolvedValue({
      ok: true, provider: 'telegram_stars',
      invoice_url: 'https://t.me/$synthetic', credits: 50,
    })
    render(<BalanceSheet />)
    fireEvent.click(screen.getByRole('button', { name: /Stars/ }))
    await screen.findByRole('region', { name: 'Ссылка на оплату' })
    await waitFor(() => expect(scroll).toHaveBeenCalledWith(expect.objectContaining({
      behavior: 'smooth', block: 'center',
    })))
    popup.mockRestore()
  } finally {
    if (oldDescriptor) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', oldDescriptor)
    else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
  }
})


it.each([
  ['Stars', { ok: true, provider: 'telegram_stars', invoice_url: 'https://t.me/$previous-session', credits: 50 }],
  ['Карта', { ok: true, provider: 'lava_card', order_id: 'old-order', payment_url: exactUrl, credits: 50 }],
] as const)('rejects a previous sheet session %s invoice after closing and reopening', async (name, reply) => {
  let resolvePayment!: (value: unknown) => void
  ;(createPayment as jest.Mock).mockImplementation(() => new Promise(resolve => { resolvePayment = resolve }))
  const openInvoice = jest.fn((_url: string, callback: (status: string) => void) => callback('cancelled'))
  Object.assign(window.Telegram!.WebApp!, { openInvoice, platform: 'ios' })
  const { rerender } = render(<BalanceSheet />)

  fireEvent.click(screen.getByRole('button', { name: name === 'Stars' ? /Stars/ : 'Карта' }))
  ;(useApp as jest.Mock).mockReturnValue({ ...fixture, isBalanceOpen: false })
  rerender(<BalanceSheet />)
  ;(useApp as jest.Mock).mockReturnValue(fixture)
  rerender(<BalanceSheet />)
  await act(async () => { resolvePayment(reply) })

  expect(openInvoice).not.toHaveBeenCalled()
  expect(openLink).not.toHaveBeenCalled()
  expect(screen.queryByRole('link', { name: 'Перейти к оплате' })).not.toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Ссылка на оплату' })).not.toBeInTheDocument()
  expect(sendMiniAppClientLog).not.toHaveBeenCalledWith('payment-checkout-ready', expect.anything())
})


it('shows only Lava payment methods in the VK application', () => {
  window.history.replaceState({}, '', '/?vk_app_id=54880352&vk_user_id=2001&sign=test')
  ;(useApp as jest.Mock).mockReturnValue({
    ...fixture,
    state: {
      ...fixture.state,
      paymentPackages: [{
        id: 'start',
        name: 'Старт',
        credits: 50,
        price_rub: 500,
        price_stars: 500,
        robokassa_enabled: true,
        freekassa_enabled: true,
        lava_offer_id: 'offer',
      }],
    },
  })

  render(<BalanceSheet />)

  expect(screen.queryByText(/Robokassa/i)).not.toBeInTheDocument()
  expect(screen.queryByText('Резерв · KASSA')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Stars/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Зарубежная / СНГ' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Карта' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'СБП' })).toBeInTheDocument()
  expect(screen.getByText('Lava.top · основной способ')).toBeInTheDocument()
})
