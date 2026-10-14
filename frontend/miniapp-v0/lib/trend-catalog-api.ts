'use client'

import { getApiBasePath, getInitData, getStartParamFallback } from './api'
import { genjutsuCall } from './genjutsu-api'
import type { PromptItem } from './types'

export interface ShowcaseTrend extends PromptItem {
  badge?: 'new'
  badge_until?: string | null
}

export interface ShowcaseCategory {
  id: number | 'unassigned'
  title: string
  emoji: string
  sort_order: number
  is_visible: boolean
  revision: number
  total: number
  items: ShowcaseTrend[]
}

export interface ShowcasePage {
  category: Pick<ShowcaseCategory, 'id' | 'title' | 'emoji' | 'revision' | 'is_visible'>
  items: ShowcaseTrend[]
  total: number
  page: number
  has_more: boolean
}

export class ShowcaseApiError extends Error {
  constructor(message: string, readonly status: number, readonly code: string) {
    super(message)
    this.name = 'ShowcaseApiError'
  }
}

async function call<T>(path: string, payload: Record<string, unknown> = {}): Promise<T> {
  const initData = getInitData()
  if (!initData) throw new ShowcaseApiError('Откройте Mini App из Telegram', 401, 'missing_telegram_auth')

  let response: Response
  try {
    response = await fetch(getApiBasePath() + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify({
        init_data: initData,
        start_param_fallback: getStartParamFallback(),
        ...payload,
      }),
    })
  } catch {
    throw new ShowcaseApiError('Нет связи с сервером. Повторите попытку.', 0, 'network')
  }

  let result: { ok?: boolean; error?: string; code?: string } & Partial<T>
  try {
    result = await response.json()
  } catch {
    throw new ShowcaseApiError('Сервер вернул некорректный ответ', response.status, 'invalid_json')
  }
  if (!response.ok || result.ok !== true) {
    throw new ShowcaseApiError(result.error || 'Не удалось загрузить каталог', response.status, result.code || 'unknown')
  }
  return result as T
}

export async function fetchTrendCatalog(limit = 6): Promise<ShowcaseCategory[]> {
  const result = await call<{ ok: true; categories: ShowcaseCategory[] }>('/trends/catalog', { limit })
  if (!Array.isArray(result.categories) || result.categories.some((category) =>
    !category || typeof category.title !== 'string' || !Array.isArray(category.items)
  )) {
    throw new ShowcaseApiError('Сервер пока не поддерживает каталог категорий', 422, 'invalid_catalog')
  }
  return result.categories
}

export async function fetchTrendCategory(
  categoryId: number | 'unassigned',
  page = 1,
  limit = 24,
): Promise<ShowcasePage> {
  const result = await call<{ ok: true } & ShowcasePage>('/trends/category', {
    category_id: categoryId, page, limit,
  })
  if (!result.category || !Array.isArray(result.items) || typeof result.has_more !== 'boolean') {
    throw new ShowcaseApiError('Не удалось получить страницу категории', 422, 'invalid_category')
  }
  return result
}

export type ShowcaseAdminAction =
  | { op: 'create'; title: string; emoji: string }
  | { op: 'update'; category_id: number; revision: number; title?: string; emoji?: string; is_visible?: boolean }
  | { op: 'delete'; category_id: number; revision: number }
  | { op: 'reorder'; categories: Array<{ id: number; revision: number }> }
  | { op: 'set_items'; category_id: number; revision: number; trend_ids: number[] }
  | { op: 'set_trend_categories'; trend_id: number; category_ids: number[] }
  | { op: 'move_item'; trend_id: number; source_id: number; target_id: number; source_revision: number; target_revision: number }
  | { op: 'set_badge'; category_id: number; trend_id: number; revision: number; badge: 'new' | ''; badge_until?: string | null }
  | { op: 'search_trends'; query?: string; page?: number; limit?: number }
  | { op: 'history'; limit?: number }

export async function adminShowcaseAction<T = unknown>(action: ShowcaseAdminAction): Promise<T> {
  const result = await call<{ ok: true; result: T }>('/admin/trends/categories', action)
  return result.result
}

export interface ShowcaseSearchResult {
  items: ShowcaseTrend[]
  total: number
  page: number
  has_more: boolean
}


/** An existing server quote, not a model-price guess, for the private recipe. */
export async function resolveGenjutsuPrices(items: ShowcaseTrend[]): Promise<ShowcaseTrend[]> {
  const recipeIds = Array.from(new Set(items.map((item) => item.generation_settings?.genjutsu_recipe_id)
    .filter((value): value is string => Boolean(value))))
  if (!recipeIds.length) return items
  try {
    const { costs } = await genjutsuCall<{ costs: Record<string, number | null> }>('recipe_costs', { recipe_ids: recipeIds })
    if (!costs || typeof costs !== 'object') return items
    return items.map((item) => {
      const recipeId = item.generation_settings?.genjutsu_recipe_id
      if (!recipeId || !Object.prototype.hasOwnProperty.call(costs, recipeId)) return item
      const value = costs[recipeId]
      if (value !== null && (typeof value !== 'number' || !Number.isFinite(value) || value < 0)) return item
      return { ...item, repeat_cost: value }
    })
  } catch {
    // No request should be blocked just because the optional quote failed.
    // Existing Genjutsu flow always computes its own authoritative quote.
    return items
  }
}

export async function resolveGenjutsuCatalogPrices(categories: ShowcaseCategory[]): Promise<ShowcaseCategory[]> {
  const priced = await resolveGenjutsuPrices(categories.flatMap((category) => category.items))
  const priceById = new Map(priced.map((item) => [item.id, item.repeat_cost]))
  return categories.map((category) => ({
    ...category,
    items: category.items.map((item) => priceById.has(item.id)
      ? { ...item, repeat_cost: priceById.get(item.id) } : item),
  }))
}


export interface ShowcaseAuditEvent {
  id: string
  action: string
  actor_telegram_id: number
  category_id: number | null
  trend_id: number | null
  before: unknown
  after: unknown
  created_at: string
}
