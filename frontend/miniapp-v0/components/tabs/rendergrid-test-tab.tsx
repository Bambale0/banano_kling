'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  Beaker,
  CircleDollarSign,
  Copy,
  Loader2,
  Play,
  RefreshCw,
  ServerCog,
} from 'lucide-react'

import { useApp } from '@/lib/app-context'
import {
  generateRenderGridImage,
  getRenderGridBalance,
  getRenderGridCreation,
  getRenderGridHealth,
  getRenderGridModels,
  type RenderGridCreation,
} from '@/lib/rendergrid-api'

const POLL_INTERVAL_MS = 5500
const ACTIVE_STATUSES = new Set(['queued', 'processing'])

type JsonObject = Record<string, unknown>

function asObject(value: unknown): JsonObject | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonObject)
    : null
}

function extractModels(value: unknown): JsonObject[] {
  if (Array.isArray(value)) return value.filter((item): item is JsonObject => Boolean(asObject(item)))
  const root = asObject(value)
  if (!root) return []
  for (const key of ['models', 'items', 'data']) {
    const candidate = root[key]
    if (Array.isArray(candidate)) {
      return candidate.filter((item): item is JsonObject => Boolean(asObject(item)))
    }
    const nested = asObject(candidate)
    if (nested) {
      const nestedModels = nested.models ?? nested.items
      if (Array.isArray(nestedModels)) {
        return nestedModels.filter((item): item is JsonObject => Boolean(asObject(item)))
      }
    }
  }
  return []
}

function modelId(model: JsonObject): string {
  return String(model.id ?? model.slug ?? model.model ?? model.name ?? '').trim()
}

function modelLabel(model: JsonObject): string {
  const id = modelId(model)
  const name = String(model.display_name ?? model.displayName ?? model.name ?? id).trim()
  const price = model.price ?? model.cost ?? model.price_per_image
  return price === undefined || price === null ? name : `${name} · ${price}`
}

function stringify(value: unknown) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function extractResultUrls(creation: RenderGridCreation | null): string[] {
  if (!creation) return []
  const direct = creation.result_urls
  if (Array.isArray(direct)) return direct.map(String).filter(Boolean)

  const result = asObject(creation.result)
  const nested = result?.urls ?? result?.result_urls ?? creation.output_urls
  return Array.isArray(nested) ? nested.map(String).filter(Boolean) : []
}

function balanceText(value: unknown): string {
  if (typeof value === 'number' || typeof value === 'string') return String(value)
  const root = asObject(value)
  if (!root) return '—'
  const nested = asObject(root.data)
  for (const source of [root, nested]) {
    if (!source) continue
    const balance = source.balance ?? source.amount ?? source.available_balance ?? source.available
    if (balance !== undefined && balance !== null) {
      const currency = source.currency ? ` ${String(source.currency)}` : ''
      return `${String(balance)}${currency}`
    }
  }
  return 'получен'
}

function StatusBadge({ status }: { status?: string }) {
  const value = String(status || '—').toLowerCase()
  const classes =
    value === 'completed'
      ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
      : value === 'failed'
        ? 'border-red-500/30 bg-red-500/10 text-red-300'
        : 'border-amber-500/30 bg-amber-500/10 text-amber-200'
  return (
    <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${classes}`}>
      {value}
    </span>
  )
}

export function RenderGridTestTab() {
  const { state } = useApp()
  const isAdmin = state.user?.isAdmin === true
  const [health, setHealth] = useState<{ configured?: boolean; base_url?: string } | null>(null)
  const [modelsRaw, setModelsRaw] = useState<unknown>(null)
  const [balanceRaw, setBalanceRaw] = useState<unknown>(null)
  const [model, setModel] = useState('nano-banana-2')
  const [prompt, setPrompt] = useState('a cinematic studio portrait, soft light, detailed skin, 35mm photo')
  const [aspectRatio, setAspectRatio] = useState('1:1')
  const [advancedJson, setAdvancedJson] = useState('{}')
  const [idempotencyKey, setIdempotencyKey] = useState('')
  const [creationId, setCreationId] = useState('')
  const [creation, setCreation] = useState<RenderGridCreation | null>(null)
  const [loadingMeta, setLoadingMeta] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollTimer = useRef<number | null>(null)

  const models = useMemo(() => extractModels(modelsRaw), [modelsRaw])
  const resultUrls = useMemo(() => extractResultUrls(creation), [creation])
  const status = String(creation?.status || '').toLowerCase()

  const stopPolling = useCallback(() => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current)
      pollTimer.current = null
    }
  }, [])

  const refreshCreation = useCallback(
    async (idOverride?: string) => {
      const id = String(idOverride || creationId || creation?.id || creation?.task_id || '').trim()
      if (!id) return
      setRefreshing(true)
      setError(null)
      try {
        const response = await getRenderGridCreation(id)
        const next = response.data || null
        setCreation(next)
        setCreationId(String(next?.id || next?.task_id || id))
        return next
      } catch (requestError) {
        setError(requestError instanceof Error ? requestError.message : 'Не удалось получить статус RenderGrid')
        return null
      } finally {
        setRefreshing(false)
      }
    },
    [creation?.id, creation?.task_id, creationId],
  )

  const loadMeta = useCallback(async () => {
    if (!isAdmin) return
    setLoadingMeta(true)
    setError(null)
    try {
      const [healthResponse, modelsResponse, balanceResponse] = await Promise.all([
        getRenderGridHealth(),
        getRenderGridModels(),
        getRenderGridBalance(),
      ])
      setHealth({
        configured: healthResponse.configured,
        base_url: healthResponse.base_url,
      })
      setModelsRaw(modelsResponse.data)
      setBalanceRaw(balanceResponse.data)
      const available = extractModels(modelsResponse.data)
      const first = available.map(modelId).find(Boolean)
      if (first) setModel((current) => current || first)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Не удалось загрузить RenderGrid')
    } finally {
      setLoadingMeta(false)
    }
  }, [isAdmin])

  useEffect(() => {
    void loadMeta()
  }, [loadMeta])

  useEffect(() => {
    stopPolling()
    if (!isAdmin || !creationId || !ACTIVE_STATUSES.has(status)) return
    pollTimer.current = window.setTimeout(() => {
      void refreshCreation(creationId)
    }, POLL_INTERVAL_MS)
    return stopPolling
  }, [creationId, isAdmin, refreshCreation, status, stopPolling])

  useEffect(() => stopPolling, [stopPolling])

  const submit = async () => {
    if (!model.trim() || !prompt.trim()) {
      setError('Укажите модель и промпт.')
      return
    }

    let advanced: JsonObject = {}
    try {
      const parsed = JSON.parse(advancedJson || '{}')
      const object = asObject(parsed)
      if (!object) throw new Error('Дополнительные параметры должны быть JSON-объектом.')
      advanced = object
    } catch (parseError) {
      setError(parseError instanceof Error ? parseError.message : 'Проверьте JSON дополнительных параметров.')
      return
    }

    const payload: JsonObject = {
      model: model.trim(),
      prompt: prompt.trim(),
      ...(aspectRatio.trim() ? { aspect_ratio: aspectRatio.trim() } : {}),
      ...advanced,
    }

    setSubmitting(true)
    setError(null)
    stopPolling()
    try {
      const response = await generateRenderGridImage(payload, idempotencyKey.trim() || undefined)
      const next = response.data || null
      setCreation(next)
      setCreationId(String(next?.id || next?.task_id || ''))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'RenderGrid не принял задачу')
    } finally {
      setSubmitting(false)
    }
  }

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value)
    } catch {}
  }

  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-3xl px-3 py-6 sm:px-4">
        <div className="rounded-2xl border border-border/60 bg-card/70 p-5 text-sm text-muted-foreground">
          Этот раздел доступен только администраторам.
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 px-3 py-4 pb-28 sm:px-4">
      <div className="rounded-3xl border border-border/60 bg-card/75 p-4 shadow-sm backdrop-blur sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-gold">
              <Beaker className="h-5 w-5" />
              <span className="text-xs font-semibold uppercase tracking-[0.16em]">Admin test</span>
            </div>
            <h1 className="mt-2 text-xl font-semibold">RenderGrid</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Прямой тест API без списаний бананов и без участия пользовательского generation flow.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadMeta()}
            disabled={loadingMeta}
            className="rounded-xl border border-border/70 bg-secondary/60 p-2.5 text-muted-foreground transition hover:text-foreground disabled:opacity-50"
            aria-label="Обновить RenderGrid"
          >
            {loadingMeta ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
          <div className="rounded-2xl border border-border/50 bg-background/35 p-3">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground"><Activity className="h-3.5 w-3.5" />Ключ</div>
            <div className="mt-1 text-sm font-medium">{health?.configured ? 'подключён' : 'не настроен'}</div>
          </div>
          <div className="rounded-2xl border border-border/50 bg-background/35 p-3">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground"><CircleDollarSign className="h-3.5 w-3.5" />Баланс</div>
            <div className="mt-1 text-sm font-medium">{balanceText(balanceRaw)}</div>
          </div>
          <div className="col-span-2 rounded-2xl border border-border/50 bg-background/35 p-3 sm:col-span-1">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground"><ServerCog className="h-3.5 w-3.5" />Модели</div>
            <div className="mt-1 text-sm font-medium">{models.length || '—'}</div>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      <div className="space-y-4 rounded-3xl border border-border/60 bg-card/75 p-4 shadow-sm backdrop-blur sm:p-5">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Модель</label>
          {models.length ? (
            <select
              value={model}
              onChange={(event) => setModel(event.target.value)}
              className="w-full rounded-xl border border-border/70 bg-background/60 px-3 py-2.5 text-sm outline-none focus:border-gold/60"
            >
              {!models.some((item) => modelId(item) === model) && <option value={model}>{model}</option>}
              {models.map((item, index) => {
                const id = modelId(item)
                return id ? <option key={`${id}-${index}`} value={id}>{modelLabel(item)}</option> : null
              })}
            </select>
          ) : (
            <input
              value={model}
              onChange={(event) => setModel(event.target.value)}
              className="w-full rounded-xl border border-border/70 bg-background/60 px-3 py-2.5 text-sm outline-none focus:border-gold/60"
              placeholder="nano-banana-2"
            />
          )}
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Промпт</label>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={4}
            className="w-full resize-y rounded-xl border border-border/70 bg-background/60 px-3 py-2.5 text-sm outline-none focus:border-gold/60"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Aspect ratio</label>
            <input
              value={aspectRatio}
              onChange={(event) => setAspectRatio(event.target.value)}
              className="w-full rounded-xl border border-border/70 bg-background/60 px-3 py-2.5 text-sm outline-none focus:border-gold/60"
              placeholder="1:1"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Idempotency key</label>
            <input
              value={idempotencyKey}
              onChange={(event) => setIdempotencyKey(event.target.value)}
              className="w-full rounded-xl border border-border/70 bg-background/60 px-3 py-2.5 text-sm outline-none focus:border-gold/60"
              placeholder="авто"
            />
          </div>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Дополнительные параметры JSON</label>
          <textarea
            value={advancedJson}
            onChange={(event) => setAdvancedJson(event.target.value)}
            rows={6}
            spellCheck={false}
            className="w-full resize-y rounded-xl border border-border/70 bg-background/60 px-3 py-2.5 font-mono text-xs outline-none focus:border-gold/60"
            placeholder={'{"resolution":"2K","reference_images":["https://…"],"webhook_url":"https://…"}'}
          />
          <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
            Сюда можно передать любые поддерживаемые выбранной моделью поля RenderGrid — resolution, референсы, webhook и новые параметры API.
          </p>
        </div>

        <button
          type="button"
          onClick={() => void submit()}
          disabled={submitting || !health?.configured}
          className="flex w-full items-center justify-center gap-2 rounded-2xl bg-gold px-4 py-3 text-sm font-semibold text-black transition active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-45"
        >
          {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {submitting ? 'Отправляю…' : 'Запустить тест'}
        </button>
      </div>

      <div className="space-y-3 rounded-3xl border border-border/60 bg-card/75 p-4 shadow-sm backdrop-blur sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">Creation</h2>
            <p className="text-xs text-muted-foreground">Автообновление не чаще одного раза в 5 секунд.</p>
          </div>
          {creation && <StatusBadge status={creation.status} />}
        </div>

        <div className="flex gap-2">
          <input
            value={creationId}
            onChange={(event) => setCreationId(event.target.value)}
            className="min-w-0 flex-1 rounded-xl border border-border/70 bg-background/60 px-3 py-2.5 text-sm outline-none focus:border-gold/60"
            placeholder="creation id"
          />
          <button
            type="button"
            onClick={() => void refreshCreation()}
            disabled={!creationId.trim() || refreshing}
            className="rounded-xl border border-border/70 bg-secondary/60 px-3 text-sm font-medium disabled:opacity-45"
          >
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Статус'}
          </button>
        </div>

        {creationId && (
          <button
            type="button"
            onClick={() => void copy(creationId)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <Copy className="h-3.5 w-3.5" />
            {creationId}
          </button>
        )}

        {resultUrls.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            {resultUrls.map((url, index) => (
              <a
                key={`${url}-${index}`}
                href={url}
                target="_blank"
                rel="noreferrer"
                className="overflow-hidden rounded-2xl border border-border/60 bg-background/50"
              >
                {/* RenderGrid returns CDN URLs dynamically; a plain img avoids a static Next remote-host allowlist. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={url} alt={`RenderGrid result ${index + 1}`} className="aspect-square w-full object-cover" />
              </a>
            ))}
          </div>
        )}

        {creation && (
          <details className="rounded-2xl border border-border/50 bg-background/35">
            <summary className="cursor-pointer px-3 py-2.5 text-xs font-medium text-muted-foreground">Raw response</summary>
            <pre className="max-h-80 overflow-auto border-t border-border/40 p-3 text-[11px] leading-relaxed text-muted-foreground">
              {stringify(creation)}
            </pre>
          </details>
        )}
      </div>

      {health?.base_url && (
        <p className="px-1 text-center text-[10px] text-muted-foreground/70">{health.base_url}</p>
      )}
    </div>
  )
}
