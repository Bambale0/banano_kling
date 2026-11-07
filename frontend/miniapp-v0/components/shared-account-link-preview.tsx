'use client'

import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { LinkedAccountsCard } from '@/components/linked-accounts-card'
import { buildTelegramMiniAppUrl } from '@/lib/api'
import { currentAccountPlatform, accountLinkUrl, incomingAccountLink, type AccountPlatform } from '@/lib/account-platform'
import { acceptAccountLink, createAccountLink, fetchAccountPreviewAccess, updateAccountLink, type AccountLink } from '@/lib/shared-account-api'

export function SharedAccountLinkPreview({ vkAppId, telegramBotUsername = '', policyRevision, onCommitted }: { vkAppId: number | null; telegramBotUsername?: string; policyRevision?: number; onCommitted?: () => void }) {
  const [link, setLink] = useState<AccountLink | null>(null)
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [showFlow, setShowFlow] = useState(false)
  const [linkedPlatforms, setLinkedPlatforms] = useState<AccountPlatform[] | null>(null)
  const [statusError, setStatusError] = useState('')
  const [statusRetry, setStatusRetry] = useState(0)
  const [destination, setDestination] = useState({ vkAppId, telegramBotUsername })
  const operation = useRef<AbortController | null>(null)
  const statusOperation = useRef<AbortController | null>(null)
  useEffect(() => {
    // Opening an invitation only fills the form. No acceptance or consent.
    const incoming = incomingAccountLink()
    setToken(incoming)
    setShowFlow(Boolean(incoming))
    return () => operation.current?.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    statusOperation.current = controller
    setStatusError('')
    setLinkedPlatforms(null)
    const timeout = setTimeout(() => {
      if (controller.signal.aborted) return
      controller.abort()
      setStatusError('Проверка заняла слишком много времени. Попробуйте ещё раз.')
    }, 15000)
    fetchAccountPreviewAccess(controller.signal).then(access => {
      if (controller.signal.aborted) return
      // Older servers cannot prove the other platform's status.
      if (!access.linked_platforms) throw new Error('Обновите приложение, чтобы проверить связанные аккаунты.')
      setLinkedPlatforms(access.linked_platforms)
      setDestination({ vkAppId: access.vk_app_id, telegramBotUsername: access.telegram_bot_username })
    }).catch(error => {
      if (!controller.signal.aborted) setStatusError(error instanceof Error ? error.message : 'Не удалось проверить связанные аккаунты.')
    }).finally(() => clearTimeout(timeout))
    return () => {
      clearTimeout(timeout)
      controller.abort()
    }
  }, [statusRetry, policyRevision])

  async function run(action: (signal: AbortSignal) => Promise<void>) {
    if (operation.current && !operation.current.signal.aborted) return
    const controller = new AbortController()
    operation.current = controller
    setBusy(true)
    setMessage('')
    try { await action(controller.signal) }
    catch (error) { if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : 'Попробуйте ещё раз.') }
    finally {
      if (!controller.signal.aborted) setBusy(false)
      if (operation.current === controller) operation.current = null
    }
  }

  function applyLink(next: AccountLink) {
    setLink(next)
    if (next.state === 'committed') {
      statusOperation.current?.abort()
      setStatusError('')
      setLinkedPlatforms(['telegram', 'vk'])
      setShowFlow(false)
      setUrl('')
      onCommitted?.()
    }
  }

  const active = link && !['committed', 'cancelled'].includes(link.state)
  const botUsername = telegramBotUsername.trim().replace(/^@/, '')
  const reopenUrl = statusError && currentAccountPlatform() === 'telegram'
    ? /^[A-Za-z0-9_]+$/.test(botUsername) ? `https://t.me/${botUsername}?startapp` : buildTelegramMiniAppUrl()
    : ''
  return <div className="space-y-3">
    <LinkedAccountsCard
      linkedPlatforms={linkedPlatforms}
      failed={Boolean(statusError)}
      busy={busy}
      onLink={() => setShowFlow(true)}
      onRetry={() => setStatusRetry(value => value + 1)}
    />
    {statusError ? <p role="status" className="text-sm text-muted-foreground">{statusError}</p> : null}
    {reopenUrl ? <Button variant="outline" asChild><a href={reopenUrl} target="_blank" rel="noopener noreferrer">Открыть приложение заново</a></Button> : null}
    {showFlow ? <section aria-label="Связывание аккаунтов" className="space-y-3 rounded-xl border border-border bg-card p-4">
    <h4 className="font-medium">Связать ТГ и ВК</h4>
    <p className="text-sm text-muted-foreground">Откройте ссылку в своём аккаунте другой платформы. Затем подтвердите связь с обеих сторон. Баланс, история и генерации станут общими после двух подтверждений.</p>
    {!active ? <Button disabled={busy} onClick={() => void run(async signal => {
      const target = currentAccountPlatform() === 'telegram' ? 'vk' : 'telegram'
      // Validate configured destination before creating a one-time invitation.
      accountLinkUrl(target, 'a'.repeat(43), destination.vkAppId, destination.telegramBotUsername)
      const created = await createAccountLink(target, signal)
      setLink(created)
      setUrl(accountLinkUrl(target, created.token!, destination.vkAppId, destination.telegramBotUsername))
    })}>Создать ссылку</Button> : null}
    {url && active ? <label className="block text-sm">Ссылка для другого аккаунта
      <input aria-label="Ссылка для другого аккаунта" readOnly value={url} className="mt-1 w-full rounded border border-border bg-background p-2" onFocus={event => event.target.select()} />
    </label> : null}
    {!link ? <>
      <label className="block text-sm">Код из ссылки
        <input className="mt-1 w-full rounded border border-border bg-background p-2" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} />
      </label>
      <Button variant="outline" disabled={busy || !token} onClick={() => void run(async signal => {
        const code = token.match(/(?:link_)?([A-Za-z0-9_-]{43})$/)?.[1]
        if (!code) throw new Error('Вставьте код или ссылку целиком.')
        applyLink(await acceptAccountLink(code, signal))
        setToken('')
      })}>Принять приглашение</Button>
    </> : null}
    {active ? <>
      <p className="text-sm">Отправитель: {link.source_identity?.platform ?? '—'} {link.source_identity?.external_id ?? '—'}. Получатель: {link.target_identity ? `${link.target_identity.platform} ${link.target_identity.external_id}` : 'ещё не вошёл'}.</p>
      <p className="text-sm">Подтверждение отправителя: {link.source_confirmed ? 'да' : 'ожидается'}. Подтверждение получателя: {link.target_confirmed ? 'да' : 'ожидается'}.</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={busy} onClick={() => void run(async signal => applyLink(await updateAccountLink(link, 'get', signal)))}>Обновить статус</Button>
        <Button disabled={busy || link.state === 'pending'} onClick={() => void run(async signal => applyLink(await updateAccountLink(link, 'confirm', signal)))}>Подтверждаю связь аккаунтов</Button>
        {url ? <Button variant="outline" disabled={busy} onClick={() => void run(async signal => {
          applyLink(await updateAccountLink(link, 'cancel', signal)); setUrl('')
        })}>Отменить ссылку</Button> : null}
      </div>
    </> : null}
    {link ? <Button variant="outline" disabled={busy} onClick={() => { setLink(null); setUrl(''); setToken(''); setMessage('') }}>Начать заново</Button> : null}
    {link?.state === 'cancelled' ? <p role="status">Ссылка отменена.</p> : null}
    {message ? <p role="status">{message}</p> : null}
    <Button variant="ghost" disabled={busy} onClick={() => setShowFlow(false)}>Свернуть</Button>
  </section> : null}
    {link?.state === 'committed' ? <p role="status" className="text-sm text-success">Аккаунты связаны.</p> : null}
  </div>
}
