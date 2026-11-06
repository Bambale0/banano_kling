'use client'

import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { accountLaunch, accountLinkUrl, incomingAccountLink } from '@/lib/account-platform'
import { acceptAccountLink, createAccountLink, updateAccountLink, type AccountLink } from '@/lib/shared-account-api'

export function SharedAccountLinkPreview({ vkAppId, telegramBotUsername = '', onCommitted }: { vkAppId: number | null; telegramBotUsername?: string; onCommitted?: () => void }) {
  const [link, setLink] = useState<AccountLink | null>(null)
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const operation = useRef<AbortController | null>(null)
  useEffect(() => {
    // Opening an invitation only fills the form. No acceptance or consent.
    setToken(incomingAccountLink())
    return () => operation.current?.abort()
  }, [])

  async function run(action: (signal: AbortSignal) => Promise<void>) {
    operation.current?.abort()
    const controller = new AbortController()
    operation.current = controller
    setBusy(true)
    setMessage('')
    try { await action(controller.signal) }
    catch (error) { if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : 'Попробуйте ещё раз.') }
    finally { if (!controller.signal.aborted) setBusy(false) }
  }

  function applyLink(next: AccountLink) {
    setLink(next)
    if (next.state === 'committed') onCommitted?.()
  }

  const active = link && !['committed', 'cancelled'].includes(link.state)
  return <section aria-label="Связывание аккаунтов" className="space-y-3 rounded-lg border border-border p-3">
    <h4 className="font-medium">Связать ТГ и ВК</h4>
    <p className="text-sm text-muted-foreground">Откройте ссылку в своём аккаунте другой платформы. Затем подтвердите связь с обеих сторон. Баланс, история и генерации станут общими после двух подтверждений.</p>
    {!active ? <Button disabled={busy} onClick={() => void run(async signal => {
      const target = accountLaunch().platform === 'telegram' ? 'vk' : 'telegram'
      // Validate configured destination before creating a one-time invitation.
      accountLinkUrl(target, 'a'.repeat(43), vkAppId, telegramBotUsername)
      const created = await createAccountLink(target, signal)
      setLink(created)
      setUrl(accountLinkUrl(target, created.token!, vkAppId, telegramBotUsername))
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
    {link?.state === 'committed' ? <p role="status">Аккаунты связаны. Обновите тестовый баланс.</p> : null}
    {link?.state === 'cancelled' ? <p role="status">Ссылка отменена.</p> : null}
    {message ? <p role="status">{message}</p> : null}
  </section>
}
