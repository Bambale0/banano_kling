'use client'

import { useState } from 'react'
import { smartRepeatCall, type RepeatSlot } from '@/lib/smart-repeat-api'
import { Button } from './ui/button'

type Diagnostic = { draft_id: string; task_id?: string; status: string; charge_amount: number; refund_amount: number;
  expected_slots: RepeatSlot[]; snapshot: { references: Record<string, { state: string; asset_id: string; binding: string }> } }

export function SmartRepeatDiagnostics({ taskId }: { taskId: string }) {
  const [lookup, setLookup] = useState(taskId)
  const [result, setResult] = useState<Diagnostic | null>(null)
  const [error, setError] = useState('')
  const [migration, setMigration] = useState('')
  const [cursor, setCursor] = useState(0)
  const [busy, setBusy] = useState(false)
  const load = async () => {
    setBusy(true); setError(''); setResult(null)
    try { setResult(await smartRepeatCall<Diagnostic>('diagnostics', { task_id: lookup })) }
    catch (e) { setError(e instanceof Error ? e.message : 'Не удалось получить диагностику.') }
    finally { setBusy(false) }
  }
  return <details className="rounded-xl border p-3 space-y-2">
    <summary className="text-sm">Диагностика умного повтора · администратор</summary>
    <input aria-label="ID задачи для диагностики" value={lookup} onChange={event => setLookup(event.target.value)} className="w-full rounded border bg-background p-2 text-xs" />
    <Button variant="outline" disabled={busy || !lookup.trim()} onClick={load}>Проверить привязки</Button>
    <Button variant="outline" disabled={busy} onClick={async () => {
      setBusy(true); setError('')
      try {
        const response = await smartRepeatCall<{ publications: Array<{ source_id: number; status: string }>; next_after_id: number; has_more: boolean }>('migration', { after_id: cursor })
        setCursor(response.next_after_id)
        setMigration(response.publications.map(item => `${item.source_id}: ${item.status === 'ready' ? 'схема сохранена' : 'нужна проверка автора'}`).join('; ') || 'Проверка публикаций завершена.')
      } catch (e) { setError(e instanceof Error ? e.message : 'Ошибка проверки.') }
      finally { setBusy(false) }
    }}>Проверить следующую группу старых публикаций</Button>
    {migration ? <p role="status" className="text-xs">{migration}</p> : null}
    {error ? <p role="alert" className="text-xs text-destructive">{error}</p> : null}
    {result ? <div className="space-y-2 text-xs break-all">
      <p>Операция: {result.draft_id} · {result.status}</p>
      <p>Списано: {result.charge_amount} · Возвращено: {result.refund_amount}</p>
      {result.expected_slots.map(slot => { const actual = result.snapshot.references?.[slot.slot_id]; return <p key={slot.slot_id}>
        {slot.label} · {slot.kind} · {slot.required ? 'обязательное' : 'необязательное'}<br />
        {slot.slot_id}: {actual ? `${actual.state} · ${actual.binding} · asset ${actual.asset_id}` : 'В снимке запуска отсутствует'}
      </p> })}
    </div> : null}
  </details>
}
