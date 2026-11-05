'use client'

import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  checkAccountPreviewLogin, fetchAccountPreviewSettings, saveAccountPreviewSettings,
  type AccountPreviewSettings,
} from '@/lib/shared-account-api'

export function SharedAccountPreview({ isAdmin }: { isAdmin: boolean }) {
  const [policy, setPolicy] = useState<AccountPreviewSettings | null>(null)
  const [enabled, setEnabled] = useState(false)
  const [appId, setAppId] = useState('')
  const [admins, setAdmins] = useState('')
  const [sessionTtl, setSessionTtl] = useState(3600)
  const [launchAge, setLaunchAge] = useState(600)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const operation = useRef<AbortController | null>(null)

  function apply(value: AccountPreviewSettings) {
    setPolicy(value)
    setEnabled(value.enabled)
    setAppId(value.vk_app_id ? String(value.vk_app_id) : '')
    setAdmins(value.vk_admin_ids.join(', '))
    setSessionTtl(value.session_ttl_seconds)
    setLaunchAge(value.launch_max_age_seconds)
  }

  useEffect(() => {
    if (!isAdmin) return
    const controller = new AbortController()
    operation.current = controller
    fetchAccountPreviewSettings(controller.signal).then(apply).catch((error: unknown) => {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : 'Не удалось загрузить настройки.')
    })
    return () => operation.current?.abort()
  }, [isAdmin])

  async function run(action: (signal: AbortSignal) => Promise<void>) {
    operation.current?.abort()
    const controller = new AbortController()
    operation.current = controller
    setBusy(true)
    setMessage('')
    try {
      await action(controller.signal)
    } catch (error) {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : 'Попробуйте ещё раз.')
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  if (!isAdmin) return null

  function identifier(raw: string): number {
    const value = Number(raw)
    if (!/^[1-9][0-9]*$/.test(raw) || !Number.isSafeInteger(value)) throw new Error('Укажите корректные числовые ID ВК.')
    return value
  }

  return (
    <section aria-label="Проверка общих аккаунтов" className="space-y-3 rounded-xl border border-border bg-card p-4">
      <h3 className="font-semibold">Общие аккаунты ТГ и ВК</h3>
      <p className="text-sm text-muted-foreground">Проверка входа для администраторов. Связывание и общий баланс появятся на следующих этапах.</p>
      {policy ? <>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} disabled={busy} />
          Доступ администраторам
        </label>
        <label className="block text-sm">ID приложения ВК
          <input className="mt-1 w-full rounded border border-border bg-background p-2" inputMode="numeric" value={appId} onChange={(event) => setAppId(event.target.value)} disabled={busy} />
        </label>
        <label className="block text-sm">ID администраторов ВК через запятую
          <input className="mt-1 w-full rounded border border-border bg-background p-2" value={admins} onChange={(event) => setAdmins(event.target.value)} disabled={busy} />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-sm">Сессия, секунд
            <input type="number" min={60} max={86400} className="mt-1 w-full rounded border border-border bg-background p-2" value={sessionTtl} onChange={(event) => setSessionTtl(Number(event.target.value))} disabled={busy} />
          </label>
          <label className="text-sm">Свежесть входа, секунд
            <input type="number" min={60} max={86400} className="mt-1 w-full rounded border border-border bg-background p-2" value={launchAge} onChange={(event) => setLaunchAge(Number(event.target.value))} disabled={busy} />
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy} onClick={() => void run(async (signal) => {
            const next = await saveAccountPreviewSettings({
              enabled, vk_app_id: appId.trim() ? identifier(appId.trim()) : null,
              vk_admin_ids: admins.trim() ? admins.trim().split(/[,;\s]+/).map(identifier) : [],
              session_ttl_seconds: sessionTtl, launch_max_age_seconds: launchAge,
            }, policy.revision, signal)
            apply(next)
            setMessage('Настройки сохранены.')
          })}>Сохранить доступ</Button>
          <Button variant="outline" disabled={busy || !policy.enabled} onClick={() => void run(async (signal) => {
            await checkAccountPreviewLogin(signal)
            setMessage('Вход подтверждён.')
          })}>Проверить вход</Button>
        </div>
      </> : <p className="text-sm text-muted-foreground">Загрузка настроек…</p>}
      {message ? <p role="status" className="text-sm">{message}</p> : null}
    </section>
  )
}
