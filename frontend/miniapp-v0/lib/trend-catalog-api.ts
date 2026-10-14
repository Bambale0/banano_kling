'use client'

import { getApiBasePath, getInitData, getStartParamFallback } from './api'
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
