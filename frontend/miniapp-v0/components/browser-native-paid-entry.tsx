'use client'

/**
 * The website and Telegram use the same product, but NOT the same financial
 * authority until a verified cutover. This component is deliberately
 * subordinate to the server actor and to BOTH web-paid availability gates.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { WebGenerationPanel } from './web-generation-panel'
import { WebOmniAssetsPanel } from './web-omni-assets-panel'
import { WebPaymentsPanel } from './web-payments-panel'

type Balance = { available: string; reserved: string; revision: number }
type WebTask = {
  task_id: string
  status: string
  type: string
  model: string
  cost?: string | null
  result_url?: string | null
  created_at_epoch: number
}
type WebState = {
  available: boolean
  balance: Balance | null
  tasks: WebTask[]
  nextCursor: string | null
}
class RevokedSession extends Error {}

async function fetchOwnerData<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    method: 'GET', credentials: 'same-origin', cache: 'no-store',
    headers: { Accept: 'application/json' }, signal,
  })
  if (response.status === 401 || response.status === 403) throw new RevokedSession()
  if (!response.ok) throw new Error('request_failed')
  return response.json() as Promise<T>
}

function safeResultUrl(raw: string | null | undefined): string | null {
  if (typeof raw !== 'string' || raw.length > 4096) return null
  try {
    const url = new URL(raw, window.location.origin)
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : null
  } catch {
    return null
  }
}

const ROOT = '/mini-app/api/web-auth'
const initial: WebState = { available: false, balance: null, tasks: [], nextCursor: null }

type LinkedBalance = {
  ok?: boolean
  scope?: string
  balance?: { available?: string }
  precision_review?: boolean
  held_web_balance?: { available: string; reserved: string } | null
}

/** The verified browser and native Telegram studio read ONE legacy authority.
 * This is a projection, not a second wallet or an opening-balance migration. */
function LinkedTelegramBalance({ onSessionExpired }: { onSessionExpired: () => void }) {
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [amount, setAmount] = useState<string | null>(null)
  const [precisionReview, setPrecisionReview] = useState(false)
  const [heldWebBalance, setHeldWebBalance] = useState<LinkedBalance['held_web_balance']>(null)

  useEffect(() => {
    const controller = new AbortController()
    void fetchOwnerData<LinkedBalance>(ROOT + '/web-payments/balance', controller.signal)
      .then(data => {
        if (controller.signal.aborted) return
        if (!data.ok || data.scope !== 'telegram_legacy'
          || typeof data.balance?.available !== 'string') {
          throw new Error('linked_balance_unavailable')
        }
        setAmount(data.balance.available)
        setPrecisionReview(Boolean(data.precision_review))
        setHeldWebBalance(data.held_web_balance ?? null)
        setStatus('ready')
      }).catch(error => {
        if (controller.signal.aborted) return
        setAmount(null)
        setHeldWebBalance(null)
        if (error instanceof RevokedSession) {
          onSessionExpired()
        } else {
          setStatus('error')
        }
      })
    return () => controller.abort()
  }, [onSessionExpired])

  if (status === 'loading') return <p role="status" className="text-sm text-[#bdb6aa]">
    Проверяем баланс Telegram…
  </p>
  if (status !== 'ready' || amount === null) return <p role="status" className="text-sm text-[#d6bf91]">
    Баланс Telegram временно недоступен. Повторите попытку после обновления страницы.
  </p>
  return <section aria-label="Баланс связанного аккаунта" className="space-y-2 border border-[#a48350]/40 bg-[#1b2325] p-4">
    <h2 className="text-lg font-semibold">Баланс Telegram в веб-студии</h2>
    <p className="text-sm text-[#dfcbaf]">Доступно: <strong>{amount}</strong> ROX</p>
    <p className="text-sm text-[#bdb6aa]">
      Это текущий баланс привязанного Telegram-аккаунта. Веб-кошелёк повторно не создаётся;
      оплата и генерации используют существующий Telegram-контур.
    </p>
    {precisionReview ? <p className="text-sm text-[#d6bf91]">
      Есть погрешность точности отображения старого баланса; исходная сумма не изменена.
    </p> : null}
    {heldWebBalance ? <p role="status" className="text-sm text-[#d6bf91]">
      В прежнем веб-кошельке сохранено {heldWebBalance.available} ROX
      {heldWebBalance.reserved !== '0.0000'
        ? ` (зарезервировано ${heldWebBalance.reserved} ROX)` : ''}.
      Эти средства не прибавлены к доступному Telegram-балансу;
      их перенос требует отдельной финансовой сверки.
    </p> : null}
  </section>
}

export function BrowserNativePaidEntry({
  accountId, telegramLinked, onSessionExpired,
}: {
  accountId: string
  telegramLinked: boolean
  onSessionExpired: () => void
}) {
  const [status, setStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const [web, setWeb] = useState<WebState>(initial)
  const [refreshing, setRefreshing] = useState(false)
  const [paging, setPaging] = useState(false)
  const owner = useRef(accountId)

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const [catalog, packages, balance, history] = await Promise.allSettled([
      fetchOwnerData<{ ok?: boolean; enabled?: boolean }>(
        ROOT + '/web-generation/models', signal),
      fetchOwnerData<{ ok?: boolean; available?: boolean }>(
        ROOT + '/web-payments/packages', signal),
      fetchOwnerData<{ ok?: boolean; balance?: Balance }>(
        ROOT + '/web-payments/balance', signal),
      fetchOwnerData<{ ok?: boolean; recent_tasks?: WebTask[]; next_cursor?: string | null }>(
        ROOT + '/web-generation/history', signal),
    ])
    const responses = [catalog, packages, balance, history]
    if (responses.some(result => result.status === 'rejected' && result.reason instanceof RevokedSession)) {
      onSessionExpired()
      return
    }
    if (signal?.aborted) return
    const models = catalog.status === 'fulfilled' ? catalog.value : null
    const payment = packages.status === 'fulfilled' ? packages.value : null
    const wallet = balance.status === 'fulfilled' ? balance.value : null
    const past = history.status === 'fulfilled' ? history.value : null
    setWeb({
      available: Boolean(models?.ok && models.enabled && payment?.ok && payment.available),
      balance: wallet?.ok && wallet.balance ? wallet.balance : null,
      tasks: past?.ok && Array.isArray(past.recent_tasks) ? past.recent_tasks : [],
      nextCursor: past?.ok ? past.next_cursor || null : null,
    })
    setStatus('ready')
  }, [onSessionExpired])

  useEffect(() => {
    owner.current = accountId
    if (telegramLinked) return
    const controller = new AbortController()
    setWeb(initial)
    setStatus('loading')
    void refresh(controller.signal).catch(() => {
      if (!controller.signal.aborted) setStatus('unavailable')
    })
    return () => controller.abort()
  }, [accountId, telegramLinked, refresh])

  const onChanged = () => {
    if (refreshing) return
    const verifiedOwner = accountId
    setRefreshing(true)
    void refresh().finally(() => {
      if (owner.current === verifiedOwner) setRefreshing(false)
    })
  }

  const loadMore = () => {
    if (!web.nextCursor || paging) return
    const cursor = web.nextCursor
    const verifiedOwner = accountId
    setPaging(true)
    void fetchOwnerData<{ ok?: boolean; recent_tasks?: WebTask[]; next_cursor?: string | null }>(
      ROOT + '/web-generation/history?cursor=' + encodeURIComponent(cursor),
    ).then(result => {
      if (owner.current !== verifiedOwner || !result.ok || !Array.isArray(result.recent_tasks)) return
      setWeb(previous => {
        const existing = new Set(previous.tasks.map(task => task.task_id))
        const additional = result.recent_tasks!.filter(task => !existing.has(task.task_id))
        return {
          ...previous, tasks: [...previous.tasks, ...additional],
          nextCursor: result.next_cursor || null,
        }
      })
    }).catch(error => {
      if (owner.current === verifiedOwner && error instanceof RevokedSession) onSessionExpired()
    }).finally(() => {
      if (owner.current === verifiedOwner) setPaging(false)
    })
  }

  if (telegramLinked) return <LinkedTelegramBalance key={accountId}
    onSessionExpired={onSessionExpired} />

  if (status === 'loading') return <p role="status" className="text-sm text-[#bdb6aa]">
    Проверяем доступность веб-генераций и состояние баланса…
  </p>

  if (status === 'unavailable') return <p role="status" className="text-sm text-[#cbbda9]">
    Веб-кабинет временно недоступен. Платежи и генерации не запускаются.
  </p>

  return <section aria-label="Генерации и баланс веб-аккаунта" className="space-y-6">
    <div className="space-y-2 border border-[#a48350]/40 bg-[#1b2325] p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">Веб-баланс</h2>
        <button type="button" disabled={refreshing}
          onClick={onChanged}
          className="inline-flex min-h-10 items-center gap-2 border border-[#b38c55]/60 px-3 text-sm disabled:opacity-60">
          <RefreshCw className="size-4" aria-hidden="true" />
          Обновить
        </button>
      </div>
      {web.balance ? <p className="text-sm text-[#dfcbaf]">
        Доступно: <strong>{web.balance.available}</strong> · В резерве: <strong>{web.balance.reserved}</strong> ROX
      </p> : <p className="text-sm text-[#bdb6aa]">
        Баланс пока не загружен. Telegram-средства не объединяются автоматически.
      </p>}
      {!web.available ? <p role="status" className="text-sm text-[#d6bf91]">
        Создание новых платных задач отключено на сервере. Уже выполненные веб-работы остаются доступны.
      </p> : null}
    </div>

    {web.available ? <div className="space-y-6">
      <WebPaymentsPanel onBalanceChanged={onChanged} />
      <WebOmniAssetsPanel onBalanceChanged={onChanged} onTaskChanged={onChanged} />
      <WebGenerationPanel onBalanceChanged={onChanged} onTaskChanged={onChanged} />
    </div> : null}

    <div className="space-y-3">
      <h2 className="text-lg font-semibold">Мои веб-генерации</h2>
      {!web.tasks.length ? <p className="text-sm text-[#bdb6aa]">Веб-работ пока нет.</p>
        : <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {web.tasks.map(task => {
            const href = safeResultUrl(task.result_url)
            return <article className="space-y-2 border border-[#a48350]/40 p-4" key={task.task_id}>
              <p className="font-semibold">{task.model}</p>
              <p className="text-xs text-[#cbbda9]">Статус: {task.status}</p>
              {task.cost ? <p className="text-xs text-[#cbbda9]">Стоимость: {task.cost} ROX</p> : null}
              {href && task.status === 'completed' ? <a
                className="inline-flex min-h-10 items-center border border-[#d2aa65] px-3 text-sm text-[#efd19c]"
                href={href} target="_blank" rel="noopener noreferrer">
                Открыть результат
              </a> : null}
            </article>
          })}
        </div>}
      {web.nextCursor ? <button type="button" className="min-h-10 border border-[#a48350] px-4 py-2 text-sm disabled:opacity-50"
        onClick={loadMore} disabled={paging}>
        {paging ? 'Загружаем…' : 'Загрузить ещё'}
      </button> : null}
    </div>
  </section>
}
