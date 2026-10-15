export function formatTrendRepeatCost(value?: number | null): string | null {
  if (value == null) return null
  const cost = Number(value)
  if (!Number.isFinite(cost) || cost < 0) return null
  return Number(cost.toFixed(2)).toString()
}


/** A Wan catalog price is only a server-calculated floor or Auto reserve. */
export function formatTrendRepeatPrice(trend: {
  repeat_cost?: number | null
  repeat_price_hint?: { amount: number; kind: 'from' | 'reserve' } | null
}): string | null {
  const fixed = formatTrendRepeatCost(trend.repeat_cost)
  if (fixed !== null) return fixed + '🍌'
  const hint = trend.repeat_price_hint
  if (!hint || (hint.kind !== 'from' && hint.kind !== 'reserve')) return null
  const amount = formatTrendRepeatCost(hint.amount)
  if (amount === null || Number(amount) <= 0) return null
  return hint.kind === 'reserve' ? 'резерв ' + amount + '🍌' : 'от ' + amount + '🍌'
}
