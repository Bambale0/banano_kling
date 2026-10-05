'use client'

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { type Operation, type Run, type RunSummary, type Settings, genjutsuCall, operationLabels, statusLabels } from '@/lib/genjutsu-api'

const field = 'w-full rounded-lg border border-border bg-background px-3 py-2 text-sm'
const labels: Record<string, string> = {
  max_steps: 'Шагов в цепочке', max_variants: 'Вариантов за запуск', max_active_runs_per_user: 'Активных работ пользователя',
  max_active_provider_tasks: 'Параллельных задач провайдера', quote_ttl_seconds: 'Срок котировки, с', lease_seconds: 'Блокировка worker, с',
  poll_seconds: 'Интервал проверки, с', request_timeout_seconds: 'Таймаут API, с', media_timeout_seconds: 'Таймаут обработки файла, с',
  input_url_ttl_seconds: 'Срок ссылки для провайдера, с', preview_url_ttl_seconds: 'Срок ссылки предпросмотра, с', presets_ttl_seconds: 'Кеш стилей, с',
  unknown_review_seconds: 'Порог неизвестной отправки, с', max_quote_credits: 'Максимальный резерв, бананы',
  provider_retry_deadline_seconds: 'Дедлайн повторов провайдера/хранилища, с',
  notification_max_attempts: 'Попыток уведомления', notification_retry_deadline_seconds: 'Срок повторов уведомления, с',
  upload_video_bytes: 'Максимум видео, байты', upload_image_bytes: 'Максимум изображения, байты', upload_audio_bytes: 'Максимум аудио, байты',
  result_max_bytes: 'Максимум результата, байты', max_source_duration_ms: 'Максимальная загрузка видео, мс',
  owner_storage_bytes: 'Хранилище пользователя, байты', total_storage_bytes: 'Общее хранилище, байты',
  max_parallel_uploads: 'Параллельных загрузок пользователя', media_parallelism: 'Параллельных обработок медиа',
}

const notificationLabels: Record<string, string> = {
  failed: 'Заголовок ошибки', canceled: 'Заголовок отмены', partial: 'Заголовок частичного результата',
  moderation: 'Причина: модерация', provider_failure: 'Причина: ошибка провайдера',
  technical_failure: 'Причина: техническая ошибка', canceled_steps: 'Остановленные шаги',
  no_charge: 'Без списания', refund: 'Возврат на баланс', charge: 'Итоговое списание', details: 'Подробности работы',
}

export function GenjutsuAdmin({ onChanged }: { onChanged: () => Promise<unknown> }) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [version, setVersion] = useState(0)
  const [coverage, setCoverage] = useState<{ operation: Operation; resolution: string; step_id: string }[]>([])
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [run, setRun] = useState<Run | null>(null)
  const [events, setEvents] = useState<{ event: string; created_ms: number; step_id?: string }[]>([])
  const [reason, setReason] = useState('')
  const [externalId, setExternalId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const notificationTemplates = settings?.notification_templates as Record<string, string> | undefined

  async function act(work: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await work() } catch (cause) { setError(cause instanceof Error ? cause.message : 'Ошибка операции') }
    finally { setBusy(false) }
  }
  async function load() {
    const value = await genjutsuCall<{ settings: Settings; version: number; coverage: typeof coverage }>('settings')
    setSettings(value.settings); setVersion(value.version); setCoverage(value.coverage)
    setRuns((await genjutsuCall<{ items: RunSummary[] }>('admin_runs')).items)
  }
  useEffect(() => { void act(load) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function command(action: string, stepId: string) {
    if (!run) return
    if (action === 'admin_refund' && !window.confirm('Выполнить возврат по этому шагу? Это не отменяет запрос у провайдера. Действие попадёт в аудит.')) return
    if (action === 'admin_adopt' && !window.confirm('Подтверждаете, что указанный provider ID относится именно к этой отправке? Будет выполнена аутентифицированная проверка статуса.')) return
    const value = await genjutsuCall<{ run: Run }>(action, {
      run_id: run.id, step_id: stepId, reason,
      ...(action === 'admin_adopt' ? { provider_request_id: externalId, confirm_request_ownership: true } : {}),
    })
    setRun(value.run); setNotice('Операция записана в аудит')
  }

  return <div className="space-y-4">
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <p aria-live="polite" className="text-sm text-muted-foreground">{busy ? 'Выполняется…' : notice}</p>
    {settings && <fieldset disabled={busy} className="space-y-4 rounded-2xl border border-border p-4">
      <h3 className="font-medium">Управление доступом и тарифами · версия {version}</h3>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={settings.admin_enabled} onChange={e => setSettings({ ...settings, admin_enabled: e.target.checked })} />Тестовые запуски администратора</label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={settings.public_enabled} onChange={e => setSettings({ ...settings, public_enabled: e.target.checked })} />Новые запуски пользователей</label>
      <p className="text-xs text-muted-foreground">Публичное включение требует подключения провайдера, хранилища, тарифов и боевой проверки всех режимов/качеств. Выключение не прерывает принятые задачи.</p>
      {(Object.keys(settings.prices) as Operation[]).map(op => <section key={op} className="space-y-2 border-t border-border pt-3"><h4>{operationLabels[op]}</h4><div className="grid grid-cols-3 gap-2">{Object.entries(settings.prices[op]).map(([res, price]) => <label key={res} className="text-xs text-muted-foreground">{res}: бананов / сек.<input className={field} type="number" min={1} step={1} value={price ?? ''} placeholder="Не задано" onChange={e => setSettings({ ...settings, prices: { ...settings.prices, [op]: { ...settings.prices[op], [res]: e.target.value ? Number(e.target.value) : null } } })} /><span>{coverage.some(c => c.operation === op && c.resolution === res) ? 'Боевой результат сохранён' : 'Нужен боевой тест'}</span></label>)}</div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={settings.verified_operations.includes(op)} onChange={e => setSettings({ ...settings, verified_operations: e.target.checked ? [...settings.verified_operations, op] : settings.verified_operations.filter(v => v !== op) })} />Режим проверен</label>
      </section>)}
      <details><summary className="cursor-pointer text-sm">Лимиты и параметры восстановления</summary><div className="mt-3 grid gap-3 sm:grid-cols-2">{Object.entries(settings).filter(([key, value]) => typeof value === 'number' && labels[key]).map(([key, value]) => <label key={key} className="text-xs text-muted-foreground">{labels[key]}<input type="number" step={1} className={field} value={Number(value)} onChange={e => setSettings({ ...settings, [key]: Number(e.target.value) })} /></label>)}</div></details>
      {notificationTemplates && <details>
        <summary className="cursor-pointer text-sm">Тексты уведомлений</summary>
        <p className="mt-2 text-xs text-muted-foreground">Обычный текст, до 300 символов на поле. Условия показа и суммы определяет сервер. В возврате сохраните {'{refunded_credits}'}, в итоговом списании — {'{charged_credits}'}, по одному разу. Другие подстановки не поддерживаются.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">{Object.entries(notificationLabels).map(([key, label]) => <label key={key} className="text-xs text-muted-foreground">{label}<textarea aria-label={label} className={field} rows={3} maxLength={300} value={notificationTemplates[key] ?? ''} onChange={e => setSettings({ ...settings, notification_templates: { ...notificationTemplates, [key]: e.target.value } })} /></label>)}</div>
      </details>}
      <Button onClick={() => void act(async () => {
        await genjutsuCall('save_settings', { settings, expected_version: version }); await load(); await onChanged(); setNotice('Настройки сохранены')
      })}>Сохранить настройки</Button>
    </fieldset>}
    <section className="space-y-3 rounded-2xl border border-border p-4">
      <div className="flex justify-between gap-2"><h3 className="font-medium">Задачи и восстановление</h3><Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>Обновить</Button></div>
      <select aria-label="Задача для диагностики" className={field} value={run?.id || ''} disabled={busy} onChange={e => e.target.value && void act(async () => { setRun((await genjutsuCall<{ run: Run }>('run', { run_id: e.target.value, admin_view: true })).run); setEvents([]) })}><option value="">Выберите задачу</option>{runs.map(r => <option key={r.id} value={r.id}>{r.id.slice(0, 10)} · user {r.owner ?? '—'} · {statusLabels[r.state] || r.state}</option>)}</select>
      {run && <><p className="break-all text-xs">ID: {run.id} · Telegram user: {run.owner ?? '—'}</p><label className="block text-sm">Причина административного действия<input className={field} value={reason} maxLength={200} onChange={e => setReason(e.target.value)} /></label>
        {run.steps.map(s => <div key={s.id} className="space-y-2 border-t border-border pt-3"><p className="text-sm">Вариант {s.variant + 1}, шаг {s.ordinal + 1}: {statusLabels[s.status] || s.status}</p><p className="break-all text-xs text-muted-foreground">Provider ID: {s.provider_request_id || 'не получен'} · correlation: {s.provider_correlation_id || 'нет'} · ошибка: {s.error_code || 'нет'}</p><p className="text-xs">Резерв {s.reserved_credits}, возвращено {s.refunded_credits}</p>
          <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => command('admin_reconcile', s.id))}>Перепроверить статус</Button><Button size="sm" variant="outline" disabled={busy || reason.trim().length < 3 || s.refunded_credits >= s.reserved_credits} onClick={() => void act(() => command('admin_refund', s.id))}>Возврат по шагу</Button></div>
          {s.status === 'submission_unknown' && <div className="space-y-2"><label className="text-sm">Подтверждённый provider ID<input className={field} value={externalId} maxLength={200} onChange={e => setExternalId(e.target.value)} /></label><Button variant="outline" disabled={busy || !externalId || reason.trim().length < 3} onClick={() => void act(() => command('admin_adopt', s.id))}>Связать с отправленной задачей</Button></div>}
        </div>)}
        <Button variant="outline" disabled={busy} onClick={() => void act(async () => { setEvents((await genjutsuCall<{ items: typeof events }>('events', { run_id: run.id })).items) })}>История событий</Button>
        {events.map((e, i) => <p key={i} className="break-all text-xs text-muted-foreground">{new Date(e.created_ms).toLocaleString()} · {e.event} · {e.step_id?.slice(0, 8)}</p>)}
      </>}
    </section>
  </div>
}
