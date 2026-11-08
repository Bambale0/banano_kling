'use client'

import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { SharedWalletPreview } from '@/components/shared-wallet-preview'
import { SharedCommercialPreview } from '@/components/shared-commercial-preview'
import { SharedAccountLinkPreview } from '@/components/shared-account-link-preview'
import {
  checkAccountPreviewLogin, fetchAccountPreviewSettings, saveAccountPreviewSettings,
  type AccountPreviewSettings,
} from '@/lib/shared-account-api'

export function SharedAccountPreview({ isAdmin, telegramBotUsername = '' }: { isAdmin: boolean; telegramBotUsername?: string }) {
  const [policy, setPolicy] = useState<AccountPreviewSettings | null>(null)
  const [enabled, setEnabled] = useState(false)
  const [appId, setAppId] = useState('')
  const [admins, setAdmins] = useState('')
  const [sessionTtl, setSessionTtl] = useState(3600)
  const [launchAge, setLaunchAge] = useState(600)
  const [linkTtl, setLinkTtl] = useState(600)
  const [communityId, setCommunityId] = useState('')
  const [vkDeliveryEnabled, setVkDeliveryEnabled] = useState(false)
  const [vkAttempts, setVkAttempts] = useState(3)
  const [vkRetrySeconds, setVkRetrySeconds] = useState(30)
  const [vkMessage, setVkMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  const operation = useRef<AbortController | null>(null)

  function apply(value: AccountPreviewSettings) {
    setPolicy(value)
    setEnabled(value.enabled)
    setAppId(value.vk_app_id ? String(value.vk_app_id) : '')
    setAdmins(value.vk_admin_ids.join(', '))
    setSessionTtl(value.session_ttl_seconds)
    setLaunchAge(value.launch_max_age_seconds)
    setLinkTtl(value.link_ttl_seconds ?? 600)
    setCommunityId(value.vk_community_id ? String(value.vk_community_id) : '')
    setVkDeliveryEnabled(value.vk_result_delivery_enabled ?? false)
    setVkAttempts(value.vk_delivery_max_attempts ?? 3)
    setVkRetrySeconds(value.vk_delivery_retry_seconds ?? 30)
    setVkMessage(value.vk_result_message_template ?? '')
  }

  useEffect(() => {
    if (!isAdmin) return
    const controller = new AbortController()
    operation.current = controller
    setLoading(true)
    setMessage('')
    const timeout = setTimeout(() => {
      if (controller.signal.aborted) return
      controller.abort()
      setLoading(false)
      setMessage('Загрузка настроек заняла слишком много времени. Попробуйте ещё раз.')
    }, 15000)
    fetchAccountPreviewSettings(controller.signal).then(value => {
      if (!controller.signal.aborted) apply(value)
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : 'Не удалось загрузить настройки.')
    }).finally(() => {
      clearTimeout(timeout)
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => { clearTimeout(timeout); operation.current?.abort() }
  }, [isAdmin, attempt])

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

  if (!isAdmin) {
    return <SharedAccountLinkPreview vkAppId={null} telegramBotUsername={telegramBotUsername} />
  }

  function identifier(raw: string): number {
    const value = Number(raw)
    if (!/^[1-9][0-9]*$/.test(raw) || !Number.isSafeInteger(value)) throw new Error('Укажите корректные числовые ID ВК.')
    return value
  }

  return <div className="space-y-4">
    <SharedAccountLinkPreview policyRevision={policy?.revision} vkAppId={policy?.vk_app_id ?? null} telegramBotUsername={telegramBotUsername} />
    <details className="rounded-xl border border-border bg-card">
      <summary className="cursor-pointer p-4 text-sm font-medium">Настройки общих аккаунтов</summary>
    <section aria-label="Проверка общих аккаунтов" className="space-y-3 rounded-xl border border-border bg-card p-4">
      <h3 className="font-semibold">Общие аккаунты ТГ и ВК</h3>
      <p className="text-sm text-muted-foreground">Вход и привязка аккаунтов доступны всем. Настройки и тестовые инструменты доступны только администраторам.</p>
      {policy ? <>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} disabled={busy} />
          Публичный вход и привязка аккаунтов
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
        <label className="block text-sm">Срок ссылки, секунд
          <input type="number" min={60} max={86400} className="mt-1 w-full rounded border border-border bg-background p-2" value={linkTtl} onChange={(event) => setLinkTtl(Number(event.target.value))} disabled={busy} />
        </label>
        <div className="flex flex-wrap gap-2">
          {policy.vk_result_message_template !== undefined ? <fieldset className="w-full space-y-3 rounded-lg border border-border p-3" disabled={busy}>
            <legend className="px-1 text-sm font-medium">Доставка результатов в чат ВК</legend>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={vkDeliveryEnabled}
              onChange={event => setVkDeliveryEnabled(event.target.checked)} />Отправлять готовые фото в ВК</label>
            <label className="block text-sm">ID сообщества ВК<input inputMode="numeric" value={communityId}
              onChange={event => setCommunityId(event.target.value)} className="mt-1 w-full rounded border border-border bg-background p-2" /></label>
            <label className="block text-sm">Автоматических попыток<input type="number" min={1} max={10} value={vkAttempts}
              onChange={event => setVkAttempts(Number(event.target.value))} className="mt-1 w-full rounded border border-border bg-background p-2" /></label>
            <label className="block text-sm">Пауза между попытками, секунд<input type="number" min={1} max={3600} value={vkRetrySeconds}
              onChange={event => setVkRetrySeconds(Number(event.target.value))} className="mt-1 w-full rounded border border-border bg-background p-2" /></label>
            <label className="block text-sm">Текст сообщения ВК<textarea value={vkMessage} maxLength={1024}
              onChange={event => setVkMessage(event.target.value)} className="mt-1 w-full rounded border border-border bg-background p-2" /></label>
            <p className="text-xs text-muted-foreground">Доступны поля {'{result_url}'} и {'{task_id}'}. Ссылка на результат обязательна.
              Изменение текста не переписывает уже принятые сообщения.</p>
          </fieldset> : null}
          <Button disabled={busy} onClick={() => void run(async (signal) => {
            const next = await saveAccountPreviewSettings({
              enabled, vk_app_id: appId.trim() ? identifier(appId.trim()) : null,
              vk_admin_ids: admins.trim() ? admins.trim().split(/[,;\s]+/).map(identifier) : [],
              session_ttl_seconds: sessionTtl, launch_max_age_seconds: launchAge, link_ttl_seconds: linkTtl,
              ...(policy.vk_result_message_template !== undefined ? {
                vk_community_id: communityId.trim() ? identifier(communityId.trim()) : null,
                vk_result_delivery_enabled: vkDeliveryEnabled,
                vk_delivery_max_attempts: vkAttempts, vk_delivery_retry_seconds: vkRetrySeconds,
                vk_result_message_template: vkMessage,
              } : {}),
            }, policy.revision, signal)
            apply(next)
            setMessage('Настройки сохранены.')
          })}>Сохранить доступ</Button>
          <Button variant="outline" disabled={busy || !policy.enabled} onClick={() => void run(async (signal) => {
            await checkAccountPreviewLogin(signal)
            setMessage('Вход подтверждён.')
          })}>Проверить вход</Button>
        </div>
      </> : loading ? <p className="text-sm text-muted-foreground">Загрузка настроек…</p> : <Button variant="outline" disabled={busy} onClick={() => setAttempt(value => value + 1)}>Повторить загрузку настроек</Button>}
      {message ? <p role="status" className="text-sm">{message}</p> : null}
      {policy?.enabled ? <SharedWalletPreview key={policy.revision} /> : null}
      {policy?.enabled ? <SharedCommercialPreview key={'commerce:' + policy.revision} /> : null}
    </section>
    </details>
  </div>
}
