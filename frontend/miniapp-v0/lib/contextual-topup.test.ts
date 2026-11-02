import { selectTopupPackages } from './contextual-topup'
import type { PaymentPackage } from './types'

const packages: PaymentPackage[] = [
  { id: 'mini', name: 'Мини', credits: 15, price_rub: 150 },
  { id: 'start', name: 'Старт', credits: 25, price_rub: 250 },
  { id: 'optimal', name: 'Оптимальный', credits: 50, price_rub: 500 },
  { id: 'pro', name: 'Про', credits: 100, price_rub: 1000 },
]

describe('contextual top-up offer', () => {
  it('recommends the cheapest package covering the shortage, not the entire generation cost', () => {
    const offer = selectTopupPackages(50, 20, packages)
    expect(offer.shortage).toBe(30)
    expect(offer.recommended?.package.id).toBe('optimal')
    expect(offer.recommended?.credited).toBe(50)
    expect(offer.alternative?.package.id).toBe('pro')
  })

  it('never confuses rubles and credits', () => {
    const offer = selectTopupPackages(15, 0, packages)
    expect(offer.recommended?.package.price_rub).toBe(150)
    expect(offer.recommended?.credited).toBe(15)
  })

  it('counts configured package bonuses without editing business prices', () => {
    const offer = selectTopupPackages(30, 0, [
      { id: 'bonus', name: 'Бонус', credits: 25, bonus_credits: 5, price_rub: 250 },
      ...packages,
    ])
    expect(offer.recommended?.package.id).toBe('bonus')
    expect(offer.recommended?.credited).toBe(30)
  })

  it('uses the smallest payable price even if package sizes are non-monotonic', () => {
    const offer = selectTopupPackages(40, 0, [
      { id: 'expensive', name: 'Малый', credits: 40, price_rub: 800 },
      { id: 'cheap', name: 'Большой', credits: 60, price_rub: 500 },
    ])
    expect(offer.recommended?.package.id).toBe('cheap')
    expect(offer.alternative).toBeNull()
  })

  it('does not recommend a package that leaves the balance insufficient', () => {
    const offer = selectTopupPackages(300, 0, packages)
    expect(offer.shortage).toBe(300)
    expect(offer.recommended).toBeNull()
  })

  it('does not show a purchase for an affordable, unknown, or invalidly priced generation', () => {
    expect(selectTopupPackages(50, 50, packages).recommended).toBeNull()
    expect(selectTopupPackages(Number.NaN, 0, packages).shortage).toBe(0)
    expect(selectTopupPackages(20, 0, []).recommended).toBeNull()
    expect(selectTopupPackages(20, 0, [
      { id: 'broken', name: 'Broken', credits: 300, price_rub: 0 },
      { id: 'nan', name: 'NaN', credits: 100, price_rub: Number.NaN },
    ]).recommended).toBeNull()
  })
})
