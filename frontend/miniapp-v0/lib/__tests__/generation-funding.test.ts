import { getGenerationFunding } from '../generation-funding'
import type { PaymentPackage } from '../types'

const packages: PaymentPackage[] = [
  { id: 'mini', name: 'Мини', credits: 15, price_rub: 150 },
  { id: 'start', name: 'Старт', credits: 25, price_rub: 250 },
  { id: 'optimal', name: 'Оптимальный', credits: 50, price_rub: 500 },
  { id: 'pro', name: 'Про', credits: 100, price_rub: 1000 },
]

describe('generation funding recommendation', () => {
  it('covers only the deficit, using server configured rubles and bananas', () => {
    const offer = getGenerationFunding(50, 20, packages)
    expect(offer?.shortage).toBe(30)
    expect(offer?.recommended?.package.id).toBe('optimal')
    expect(offer?.recommended?.totalCredits).toBe(50)
    expect(offer?.recommended?.package.price_rub).toBe(500)
  })

  it('uses the smallest-priced sufficient package and never equates rubles with credits', () => {
    const offer = getGenerationFunding(50, 0, packages)
    expect(offer?.recommended?.package.credits).toBe(50)
    expect(offer?.recommended?.package.price_rub).toBe(500)
    expect(getGenerationFunding(15, 0, packages)?.recommended?.package.credits).toBe(15)
  })

  it('includes configured package bonuses but not presumed promo bonuses', () => {
    const offer = getGenerationFunding(55, 0, [
      { id: 'bonus', name: 'Бонус', credits: 50, bonus_credits: 5, price_rub: 460 },
      ...packages,
    ])
    expect(offer?.recommended?.package.id).toBe('bonus')
    expect(offer?.recommended?.totalCredits).toBe(55)
  })

  it('does not suggest any package if backend provides an empty catalog', () => {
    expect(getGenerationFunding(50, 1, [])?.recommended).toBeNull()
  })

  it('does not falsely promise a single package when none covers the deficit', () => {
    expect(getGenerationFunding(600, 0, packages)?.recommended).toBeNull()
  })

  it('rejects malformed or unavailable amounts instead of constructing a checkout', () => {
    const malformed = [
      { id: 'bad', name: 'Bad', credits: -1, price_rub: 150 },
      { id: 'nan', name: 'Nan', credits: Number.NaN, price_rub: 150 },
      { id: 'zero', name: 'Zero', credits: 10, price_rub: 0 },
    ]
    expect(getGenerationFunding(20, 0, malformed)?.recommended).toBeNull()
    expect(getGenerationFunding(Number.NaN, 0, packages)).toBeNull()
  })

  it('never offers payment when the user already has enough', () => {
    expect(getGenerationFunding(15, 15, packages)?.shortage).toBe(0)
    expect(getGenerationFunding(15, 16, packages)?.shortage).toBe(0)
  })
})
