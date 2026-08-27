'use client'

import { getInitData } from './api'

const RENDERGRID_ADMIN_ROOT = '/api/admin/rendergrid'

export interface RenderGridEnvelope<T = unknown> {
  ok: boolean
  data?: T
  error?: string
  configured?: boolean
  base_url?: string
  provider_status?: number | null
  provider_code?: string | null
  retry_after?: number | null
}

export interface RenderGridCreation {
  id?: string
  task_id?: string
  status?: string
  cost?: number
  result_urls?: string[]
  [key: string]: unknown
}

async function renderGridFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<RenderGridEnvelope<T>> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте Mini App через Telegram.')
  }

  const response = await fetch(`${RENDERGRID_ADMIN_ROOT}${path}`, {
    ...options,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-Telegram-Init-Data': initData,
      ...options.headers,
    },
  })

  const payload = (await response.json().catch(() => ({}))) as RenderGridEnvelope<T>
  if (!response.ok || payload.ok === false) {
    const suffix = payload.provider_code ? ` (${payload.provider_code})` : ''
    throw new Error(`${payload.error || `RenderGrid: HTTP ${response.status}`}${suffix}`)
  }
  return payload
}

export function getRenderGridHealth() {
  return renderGridFetch('/health')
}

export function getRenderGridModels() {
  return renderGridFetch<unknown>('/models')
}

export function getRenderGridBalance() {
  return renderGridFetch<unknown>('/balance')
}

export function generateRenderGridImage(
  payload: Record<string, unknown>,
  idempotencyKey?: string,
) {
  return renderGridFetch<RenderGridCreation>('/images/generate', {
    method: 'POST',
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    body: JSON.stringify(payload),
  })
}

export function getRenderGridCreation(creationId: string) {
  return renderGridFetch<RenderGridCreation>(
    `/creations/${encodeURIComponent(creationId.trim())}`,
  )
}
