import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { GenerationFundingOffer } from './generation-funding-offer'
import { useOptionalApp } from '@/lib/app-context'

jest.mock('@/lib/app-context', () => ({ useOptionalApp: jest.fn() }))

const openBalance = jest.fn()
const packages = [
  { id: 'mini', name: 'Мини', credits: 15, price_rub: 150 },
  { id: 'start', name: 'Старт', credits: 25, price_rub: 250 },
  { id: 'optimal', name: 'Оптимальный', credits: 50, price_rub: 500 },
  { id: 'pro', name: 'Про', credits: 100, price_rub: 1000 },
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
