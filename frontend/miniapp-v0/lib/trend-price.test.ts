import { formatTrendRepeatPrice } from './trend-price'

describe('visible repeat pricing', () => {
  it('uses the existing authoritative fixed price when known', () => {
    expect(formatTrendRepeatPrice({ repeat_cost: 21.5, repeat_price_hint: { amount: 11, kind: 'from' } })).toBe('21.5🍌')
  })
  it('labels a WAN source-video lower bound rather than showing it as a final debit', () => {
    expect(formatTrendRepeatPrice({ repeat_cost: null, repeat_price_hint: { amount: 22, kind: 'from' } })).toBe('от 22🍌')
  })
  it('labels Auto as a reserve', () => {
    expect(formatTrendRepeatPrice({ repeat_cost: null, repeat_price_hint: { amount: 60, kind: 'reserve' } })).toBe('резерв 60🍌')
  })
  it('hides unknown and impossible values instead of guessing', () => {
    expect(formatTrendRepeatPrice({ repeat_cost: null })).toBeNull()
    expect(formatTrendRepeatPrice({ repeat_price_hint: { amount: -2, kind: 'from' } })).toBeNull()
    expect(formatTrendRepeatPrice({ repeat_price_hint: { amount: Number.NaN, kind: 'from' } })).toBeNull()
  })
})
