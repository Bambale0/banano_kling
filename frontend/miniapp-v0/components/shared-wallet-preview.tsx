'use client'

import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  applyAccountPreviewWallet, fetchAccountPreviewWallet, reconcileAccountPreviewWallet,
  type PreviewWallet, type PreviewWalletOperation,
} from '@/lib/shared-account-api'

function operationKey(): string {
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  return 'preview:' + Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
}

export function SharedWalletPreview() {
  const [wallet, setWallet] = useState<PreviewWallet | null>(null)
  const [action, setAction] = useState<PreviewWalletOperation['action']>('credit')
  const [amount, setAmount] = useState('')
  const [reference, setReference] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [audit, setAudit] = useState('')
  const pending = useRef<{ fingerprint: string; key: string } | null>(null)
  const controller = useRef<AbortController | null>(null)

  useEffect(() => {
    const operation = new AbortController()
    controller.current = operation
    fetchAccountPreviewWallet(operation.signal).then(setWallet).catch((failure: unknown) => {
      if (!operation.signal.aborted) setError(failure instanceof Error ? failure.message : 'Не удалось загрузить тестовый кошелёк.')
    })
    return () => controller.current?.abort()
  }, [])

  async function execute() {
    controller.current?.abort()
    const operation = new AbortController()
    controller.current = operation
    setBusy(true)
    setError('')
    setAudit('')
    const referenceKey = ['capture', 'release', 'refund'].includes(action) ? reference.trim() : ''
    try {
      const exactAmount = amount.trim().replace(',', '.')
      const fingerprint = JSON.stringify([action, exactAmount, referenceKey])
      let request = pending.current
      if (!request || request.fingerprint !== fingerprint) request = { fingerprint, key: operationKey() }
      pending.current = request
      const result = await applyAccountPreviewWallet({
        action, amount: exactAmount, reference_key: referenceKey, idempotency_key: request.key,
      }, operation.signal)
      if (!operation.signal.aborted) {
        setWallet(result)
        pending.current = null
      }
    } catch (failure) {
      if (!operation.signal.aborted) setError(failure instanceof Error ? failure.message : 'Повторите проверку.')
    } finally {
      if (!operation.signal.aborted) setBusy(false)
    }
  }

  async function refresh(check = false) {
    controller.current?.abort()
    const operation = new AbortController()
    controller.current = operation
    setBusy(true)
    setError('')
    setAudit('')
    try {
      if (check) {
        const report = await reconcileAccountPreviewWallet(operation.signal)
        if (!operation.signal.aborted) setAudit(report.consistent ? 'Баланс, резервы и журнал совпадают.' : 'Найдено расхождение. Требуется проверка журнала.')
      }
      const result = await fetchAccountPreviewWallet(operation.signal)
      if (!operation.signal.aborted) setWallet(result)
    } catch (failure) {
      if (!operation.signal.aborted) setError(failure instanceof Error ? failure.message : 'Не удалось обновить баланс.')
    } finally {
      if (!operation.signal.aborted) setBusy(false)
    }
  }

  return <section className="space-y-3 rounded-lg border border-border p-3" aria-label="Тестовый кошелёк">
    <h4 className="font-medium">Тестовый кошелёк</h4>
    <p className="text-xs text-muted-foreground">Отдельные тестовые единицы для проверки операций. Реальный баланс сюда не переносится.</p>
    {wallet ? <>
      <p className="text-sm">Доступно: {wallet.balance.available}</p>
      <p className="text-sm">В резерве: {wallet.balance.reserved}</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={busy} onClick={() => void refresh()}>Обновить баланс</Button>
        <Button variant="outline" disabled={busy} onClick={() => void refresh(true)}>Сверить журнал</Button>
      </div>
      <label className="block text-sm">Операция кошелька
        <select className="mt-1 w-full rounded border border-border bg-background p-2" value={action} onChange={event => setAction(event.target.value as PreviewWalletOperation['action'])} disabled={busy}>
          <option value="credit">Пополнить тестовый баланс</option>
          <option value="reserve">Зарезервировать</option>
          <option value="capture">Подтвердить списание</option>
          <option value="release">Снять резерв</option>
          <option value="refund">Вернуть списание</option>
        </select>
      </label>
      <label className="block text-sm">Тестовая сумма
        <input className="mt-1 w-full rounded border border-border bg-background p-2" inputMode="decimal" value={amount} onChange={event => setAmount(event.target.value)} disabled={busy} />
      </label>
      {['capture', 'release', 'refund'].includes(action) ? <label className="block text-sm">Ключ резерва или списания
        <input className="mt-1 w-full rounded border border-border bg-background p-2" value={reference} onChange={event => setReference(event.target.value)} disabled={busy} />
      </label> : null}
      <Button disabled={busy || !amount.trim()} onClick={() => void execute()}>Выполнить проверку</Button>
      {wallet.receipt ? <p className="break-all text-xs">Ключ операции: {wallet.receipt.operation_key}</p> : null}
      <ul className="max-h-48 space-y-1 overflow-auto text-xs" aria-label="Журнал тестовых операций">
        {wallet.entries.map(entry => <li key={entry.operation_key} className="break-all">{entry.kind}: {entry.amount} · {entry.operation_key}</li>)}
      </ul>
    </> : <p className="text-sm">Загрузка тестового кошелька…</p>}
    {error ? <p role="status" className="text-sm">{error}</p> : null}
    {audit ? <p role="status" className="text-sm">{audit}</p> : null}
  </section>
}
