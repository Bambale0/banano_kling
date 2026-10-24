import { trendCardDescription } from '../trend-card-description'

test('legacy count is displayed separately without clamping the actual description', () => {
  expect(trendCardDescription({ description: '✅ Успешных запусков: 55 · Море', successful_runs_count: 55 })).toBe('Море')
  expect(trendCardDescription({ description: '✅ Успешных запусков: 0', successful_runs_count: 0 })).toBe('')
  expect(trendCardDescription({ description: 'Море', successful_runs_count: 55 })).toBe('Море')
  expect(trendCardDescription({ description: '✅ Успешных запусков: 5', successful_runs_count: 55 })).toBe('✅ Успешных запусков: 5')
})
