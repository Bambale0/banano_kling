import { formatTrendRepeatCost } from '../trend-price'

test('an unquoted price is not displayed as free generation', () => {
  expect(formatTrendRepeatCost(null)).toBeNull()
  expect(formatTrendRepeatCost(undefined)).toBeNull()
  expect(formatTrendRepeatCost(0)).toBe('0')
  expect(formatTrendRepeatCost(12.5)).toBe('12.5')
})
