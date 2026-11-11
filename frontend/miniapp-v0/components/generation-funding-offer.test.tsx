import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { GenerationFundingOffer } from './generation-funding-offer'
import { useOptionalApp } from '@/lib/app-context'

jest.mock('@/lib/app-context', () => ({ useOptionalApp: jest.fn() }))

const openBalance = jest.fn()
const packages = [
  { id: 'mini', name: 'Мини', credits: 15, price_rub: 150, robokassa_enabled: true },
  { id: 'start', name: 'Старт', credits: 25, price_rub: 250, robokassa_enabled: true },
  { id: 'optimal', name: 'Оптимальный', credits: 50, price_rub: 500, robokassa_enabled: true },
  { id: 'pro', name: 'Про', credits: 100, price_rub: 1000, robokassa_enabled: true },
]

beforeEach(() => {
  jest.clearAllMocks()
  ;(useOptionalApp as jest.Mock).mockReturnValue({
    state: { mode: 'live', user: { isAdmin: false, credits: 20 }, paymentPackages: packages },
    openBalance,
  })
})

it('shows real deficit and purchase amount, without auto-starting video or checkout', () => {
  render(<GenerationFundingOffer cost={50} credits={20} />)
  const region = screen.getByRole('region', { name: 'Пополнение для генерации' })
  expect(region).toHaveTextContent('Стоимость: 50🍌')
  expect(region).toHaveTextContent('На балансе: 20🍌')
  expect(region).toHaveTextContent('Не хватает 30🍌')
  fireEvent.click(screen.getByRole('button', { name: /Купить 50🍌 за 500 ₽/ }))
  expect(openBalance).toHaveBeenCalledTimes(1)
  expect(openBalance).toHaveBeenCalledWith({ packageId: 'optimal', requiredCredits: 50 })
})

it('lets users select a larger package or open all payment methods', () => {
  render(<GenerationFundingOffer cost={50} credits={20} />)
  fireEvent.click(screen.getByRole('button', { name: /Больше бананов: 100🍌/ }))
  expect(openBalance).toHaveBeenLastCalledWith({ packageId: 'pro', requiredCredits: 50 })
  fireEvent.click(screen.getByRole('button', { name: 'Другие суммы и способы оплаты' }))
  expect(openBalance).toHaveBeenLastCalledWith({ packageId: undefined, requiredCredits: 50 })
})

it('never suggests buying credits for unverified prices, sufficient credit or admins', () => {
  const { rerender } = render(<GenerationFundingOffer cost={null} credits={0} />)
  expect(screen.queryByRole('region', { name: 'Пополнение для генерации' })).not.toBeInTheDocument()
  rerender(<GenerationFundingOffer cost={25} credits={25} />)
  expect(screen.queryByRole('region', { name: 'Пополнение для генерации' })).not.toBeInTheDocument()
  rerender(<GenerationFundingOffer cost={50} credits={0} adminFree />)
  expect(screen.queryByRole('region', { name: 'Пополнение для генерации' })).not.toBeInTheDocument()
})

it('does not fabricate packages when the live API returned none', () => {
  ;(useOptionalApp as jest.Mock).mockReturnValue({
    state: { mode: 'live', user: { isAdmin: false, credits: 0 }, paymentPackages: [] },
    openBalance,
  })
  render(<GenerationFundingOffer cost={50} credits={0} />)
  expect(screen.getByText(/Одного доступного пакета недостаточно/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Купить/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Другие суммы и способы оплаты' }))
  expect(openBalance).toHaveBeenCalledTimes(1)
})

it('keeps isolated component previews safe without a global Mini App provider', () => {
  ;(useOptionalApp as jest.Mock).mockReturnValue(null)
  expect(() => render(<GenerationFundingOffer cost={50} credits={0} />)).not.toThrow()
  expect(screen.queryByRole('region', { name: 'Пополнение для генерации' })).not.toBeInTheDocument()
})

it('opens the recommended package once for a confirmed video repeat', async () => {
  const view = render(<GenerationFundingOffer cost={50} credits={20} autoOpenKey="repeat:42" />)
  await waitFor(() => expect(openBalance).toHaveBeenCalledWith({
    packageId: 'optimal', requiredCredits: 50, reason: 'video-repeat',
  }))
  view.rerender(<GenerationFundingOffer cost={50} credits={20} autoOpenKey="repeat:42" />)
  expect(openBalance).toHaveBeenCalledTimes(1)
})

it('labels a Stars-only package in Stars', () => {
  ;(useOptionalApp as jest.Mock).mockReturnValue({
    state: { mode: 'live', user: { isAdmin: false, credits: 0 }, paymentPackages: [
      { id: 'stars', name: 'Stars', credits: 50, price_rub: 500, price_stars: 650 },
    ] },
    openBalance,
  })
  render(<GenerationFundingOffer cost={50} credits={0} />)
  expect(screen.getByRole('button', { name: /Купить 50🍌 за 650 ⭐/ })).toBeEnabled()
})

it('still opens all packages when no single package covers a repeat shortage', async () => {
  ;(useOptionalApp as jest.Mock).mockReturnValue({
    state: { mode: 'live', user: { isAdmin: false, credits: 0 }, paymentPackages: [
      { id: 'mini', name: 'Мини', credits: 15, price_rub: 150, robokassa_enabled: true },
    ] },
    openBalance,
  })
  render(<GenerationFundingOffer cost={50} credits={0} autoOpenKey="repeat:expensive" />)
  await waitFor(() => expect(openBalance).toHaveBeenCalledWith({
    packageId: undefined, requiredCredits: 50, reason: 'video-repeat',
  }))
})


afterEach(() => {
  window.history.replaceState({}, '', '/')
  delete process.env.NEXT_PUBLIC_MINIAPP_PLATFORM
})

it('VK funding recommends only a configured Lava bundle rather than an unavailable cheaper option', () => {
  window.history.replaceState({}, '', '/?vk_app_id=54880352&vk_user_id=2001')
  ;(useOptionalApp as jest.Mock).mockReturnValue({
    state: { mode: 'live', user: { isAdmin: false, credits: 0 }, paymentPackages: [
      { id: 'unsupported', name: 'Недоступен', credits: 50, price_rub: 500, robokassa_enabled: true },
      { id: 'lava', name: 'Lava', credits: 100, price_rub: 1000, lava_offer_id: 'configured-offer' },
    ] },
    openBalance,
  })
  render(<GenerationFundingOffer cost={30} credits={0} />)
  expect(screen.queryByRole('button', { name: /Купить 50🍌/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Купить 100🍌 за 1000 ₽/ }))
  expect(openBalance).toHaveBeenCalledWith({ packageId: 'lava', requiredCredits: 30 })
})

it('VK never offers an unsupported quick-checkout package when no Lava method exists', () => {
  process.env.NEXT_PUBLIC_MINIAPP_PLATFORM = 'vk'
  render(<GenerationFundingOffer cost={50} credits={0} />)
  expect(screen.queryByRole('button', { name: /Купить/ })).not.toBeInTheDocument()
  expect(screen.getByText(/Одного доступного пакета недостаточно/)).toBeInTheDocument()
})
