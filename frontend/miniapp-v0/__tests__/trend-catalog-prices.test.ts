import { resolveGenjutsuCatalogPrices, resolveGenjutsuPrices, type ShowcaseTrend } from '@/lib/trend-catalog-api'
import { genjutsuCall } from '@/lib/genjutsu-api'

jest.mock('@/lib/genjutsu-api', () => ({ genjutsuCall: jest.fn() }))
const mockedCall = genjutsuCall as jest.Mock

const recipeId = 'a'.repeat(32)
const genjutsu = {
  id: 71, title: 'Genjutsu motion', generation_settings: { kind: 'video', genjutsu_recipe_id: recipeId },
  repeat_cost: null,
} as ShowcaseTrend
const ordinary = {
  id: 72, title: 'Photo', generation_settings: { kind: 'image' }, repeat_cost: 10,
} as ShowcaseTrend

beforeEach(() => jest.clearAllMocks())

test('recipe costs are taken from the existing authenticated quote and shared between folders', async () => {
  mockedCall.mockResolvedValue({ costs: { [recipeId]: 43 } })
  const result = await resolveGenjutsuCatalogPrices([
    { id: 1, title: 'One', emoji: '🎬', is_visible: true, revision: 1, sort_order: 0, total: 2, items: [genjutsu, ordinary] },
    { id: 2, title: 'Two', emoji: '⭐', is_visible: true, revision: 1, sort_order: 1, total: 1, items: [genjutsu] },
  ])
  expect(mockedCall).toHaveBeenCalledTimes(1)
  expect(mockedCall).toHaveBeenCalledWith('recipe_costs', { recipe_ids: [recipeId] })
  expect(result[0].items[0].repeat_cost).toBe(43)
  expect(result[1].items[0].repeat_cost).toBe(43)
  expect(result[0].items[1].repeat_cost).toBe(10)
})

test('temporary quote failure preserves cards and existing cost', async () => {
  mockedCall.mockRejectedValue(new Error('provider unavailable'))
  const result = await resolveGenjutsuPrices([genjutsu, ordinary])
  expect(result).toEqual([genjutsu, ordinary])
})
