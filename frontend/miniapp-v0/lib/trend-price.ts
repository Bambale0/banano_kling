export function formatTrendRepeatCost(value?: number | null): string | null {
  const cost = Number(value)
  if (!Number.isFinite(cost) || cost < 0) return null
  return Number(cost.toFixed(2)).toString()
}
