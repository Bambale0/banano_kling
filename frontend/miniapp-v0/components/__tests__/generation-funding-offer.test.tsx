import '@testing-library/jest-dom'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { GenerationFundingOffer } from '@/components/generation-funding-offer'
import type { PaymentPackage } from '@/lib/types'

const packages: PaymentPackage[] = [
  { id: 'mini', name: 'Мини', credits: 15, price_rub: 150 },
  { id: 'optimal', name: 'Оптимальный', credits: 50, price_rub: 500 },
  { id: 'pro', name: 'Про', credits: 100, price_rub: 1000 },
]

it('suggests the cheapest sufficient configured package, with separate currency and credits', () => {
  const onTopup = jest.fn()
  render(<GenerationFundingOffer cost={50} credits={20}
    paymentPackages={packages} onTopup={onTopup} />)

  const section = within(screen.getByRole('region', { name: 'Пополнение для генерации' }))
  expect(section.getByText(/Не хватает/)).toHaveTextContent('30🍌')
  fireEvent.click(section.getByRole('button', { name: 'Купить 50🍌 за 500 ₽' }))
  expect(onTopup).toHaveBeenCalledWith({ cost: 50, packageId: 'optimal' })
})

it('does not charge when alternative packages are chosen: only opens existing checkout', () => {
  const onTopup = jest.fn()
  render(<GenerationFundingOffer cost={50} credits={20}
    paymentPackages={packages} onTopup={onTopup} />)
  fireEvent.click(screen.getByRole('button', { name: 'Выбрать другой пакет' }))
  fireEvent.click(screen.getByRole('button', { name: '100🍌 за 1000 ₽' }))
  expect(onTopup).toHaveBeenCalledWith({ cost: 50, packageId: 'pro' })
  expect(onTopup).toHaveBeenCalledTimes(1)
})

it('does not show an invented checkout or price when the catalog is missing', () => {
  render(<GenerationFundingOffer cost={50} credits={0} paymentPackages={[]} onTopup={jest.fn()} />)
  expect(screen.getByText(/Пакеты временно недоступны/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Купить/ })).not.toBeInTheDocument()
})

it('never offers a payment for an admin or when the balance is sufficient', () => {
  const onTopup = jest.fn()
  const { rerender } = render(<GenerationFundingOffer cost={50} credits={0}
    isAdmin paymentPackages={packages} onTopup={onTopup} />)
  expect(screen.queryByRole('region', { name: 'Пополнение для генерации' })).not.toBeInTheDocument()
  rerender(<GenerationFundingOffer cost={50} credits={50} paymentPackages={packages} onTopup={onTopup} />)
  expect(screen.queryByRole('region', { name: 'Пополнение для генерации' })).not.toBeInTheDocument()
})

it('allows opening the full catalog when no single package can cover the cost', () => {
  const onTopup = jest.fn()
  render(<GenerationFundingOffer cost={120} credits={0} paymentPackages={packages} onTopup={onTopup} />)
  fireEvent.click(screen.getByRole('button', { name: 'Посмотреть все пакеты' }))
  expect(onTopup).toHaveBeenCalledWith({ cost: 120 })
})
