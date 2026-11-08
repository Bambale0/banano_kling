'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { LinkedAccountsCard } from '@/components/linked-accounts-card'
import { buildTelegramMiniAppUrl } from '@/lib/api'
import { accountLinkUrl, currentAccountPlatform, incomingAccountLink, type AccountPlatform } from '@/lib/account-platform'
import {
  acceptAccountLink, createAccountLink, fetchAccountPreviewAccess, previewAccountLink,
  updateAccountLink, type AccountLink,
} from '@/lib/shared-account-api'

const platformLabel = (value: AccountPlatform) => value === 'telegram' ? 'Telegram' : 'ВКонтакте'

export function SharedAccountLinkPreview({ vkAppId, telegramBotUsername = '', policyRevision, onCommitted }: {
  vkAppId: number | null
  telegramBotUsername?: string
  policyRevision?: number
  onCommitted?: () => void
}) {
  const [link, setLink] = useState<AccountLink | null>(null)
  const [url, setUrl] = useState('')
  const [incomingToken, setIncomingToken] = useState('')
  const [incomingPreview, setIncomingPreview] = useState<AccountLink | null>(null)
  const [incomingError, setIncomingError] = useState('')
  const [incomingRetry, setIncomingRetry] = useState(0)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [linkedPlatforms, setLinkedPlatforms] = useState<AccountPlatform[] | null>(null)
  const [statusError, setStatusError] = useState('')
  const [statusRetry, setStatusRetry] = useState(0)
  const [destination, setDestination] = useState({ vkAppId, telegramBotUsername })
  const operation = useRef<AbortController | null>(null)
  const statusOperation = useRef<AbortController | null>(null)
  const linked = Boolean(linkedPlatforms?.includes('telegram') && linkedPlatforms?.includes('vk'))

  useEffect(() => {
    // Deep links carry a bearer invitation. Reading it never grants consent.
    setIncomingToken(incomingAccountLink())
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

  useEffect(() => {
    if (!incomingToken || linked) return
    const controller = new AbortController()
    setIncomingError('')
    setIncomingPreview(null)
    previewAccountLink(incomingToken, controller.signal).then(value => {
      if (!controller.signal.aborted) setIncomingPreview(value)
    }).catch(error => {
      if (!controller.signal.aborted) setIncomingError(error instanceof Error ? error.message : 'Не удалось проверить приглашение.')
    })
    return () => controller.abort()
  }, [incomingToken, incomingRetry, linked])

  async function run(action: (signal: AbortSignal) => Promise<void>) {
    if (operation.current && !operation.current.signal.aborted) return
    const controller = new AbortController()
    operation.current = controller
    setBusy(true)
    setMessage('')
    try { await action(controller.signal) }
    catch (error) {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : 'Попробуйте ещё раз.')
    } finally {
      if (!controller.signal.aborted) setBusy(false)
      if (operation.current === controller) operation.current = null
    }
  }

  const applyLink = useCallback((next: AccountLink) => {
    setLink(next)
    if (next.state === 'committed') {
      statusOperation.current?.abort()
      setStatusError('')
      setLinkedPlatforms(['telegram', 'vk'])
      setIncomingToken('')
      setUrl('')
      onCommitted?.()
    }
  }, [onCommitted])

  // The original platform stays open while the verified destination accepts.
  // Polling is read-only and cannot commit an invitation on anyone's behalf.
  useEffect(() => {
    if (!link || !url || link.state === 'committed' || link.state === 'cancelled') return
    const controller = new AbortController()
    let checking = false
    const timer = window.setInterval(() => {
      if (checking || controller.signal.aborted) return
      checking = true
      void updateAccountLink(link, 'get', controller.signal).then(next => {
        if (!controller.signal.aborted) applyLink(next)
      }).catch(error => {
        if (controller.signal.aborted) return
        const description = error instanceof Error ? error.message : 'Не удалось проверить связь.'
        if (description.startsWith('Ссылка истекла или отменена.')) {
          setLink(null)
          setUrl('')
          setMessage('Ссылка истекла. Нажмите «Привязать» ещё раз.')
        } else {
          setMessage(description)
        }
      }).finally(() => { checking = false })
    }, 4000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [link, url, applyLink])

  function beginLink(target: AccountPlatform) {
    if (busy || (operation.current && !operation.current.signal.aborted) || currentAccountPlatform() === target) return
    try {
      // Reject absent destination metadata before making a pending invitation.
      accountLinkUrl(target, 'a'.repeat(43), destination.vkAppId, destination.telegramBotUsername)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Не удалось открыть другую платформу.')
      return
    }
    // Open the window synchronously with the click to avoid popup blockers.
    let popup: Window | null = null
    try { popup = window.open('about:blank', '_blank') } catch { /* Continue with same-window navigation. */ }
    if (popup) {
      try {
        popup.opener = null
        popup.document.title = 'Открываем приложение…'
      } catch { /* Browser-owned cross-origin window. */ }
    }
    void run(async signal => {
      try {
        const created = await createAccountLink(target, signal, true)
        if (signal.aborted) { popup?.close(); return }
        const targetUrl = accountLinkUrl(target, created.token || '', destination.vkAppId, destination.telegramBotUsername)
        setLink(created)
        setUrl(targetUrl)
        if (popup && !popup.closed) {
          popup.location.replace(targetUrl)
        } else {
          // Embedded VK/Telegram clients may block popups but allow navigation.
          window.location.assign(targetUrl)
        }
      } catch (error) {
        popup?.close()
        throw error
      }
    })
  }

  const active = link && link.state !== 'committed' && link.state !== 'cancelled'
  const botUsername = destination.telegramBotUsername.trim().replace(/^@/, '')
  const reopenUrl = statusError && currentAccountPlatform() === 'telegram'
    ? /^[A-Za-z0-9_]+$/.test(botUsername) ? `https://t.me/${botUsername}?startapp` : buildTelegramMiniAppUrl()
    : ''

  return <div className="space-y-3">
    <LinkedAccountsCard
      linkedPlatforms={linkedPlatforms}
      failed={Boolean(statusError)}
      busy={busy}
      onLink={beginLink}
      onRetry={() => setStatusRetry(value => value + 1)}
    />
    {statusError ? <p role="status" className="text-sm text-muted-foreground">{statusError}</p> : null}
    {reopenUrl ? <Button variant="outline" asChild><a href={reopenUrl} target="_blank" rel="noopener noreferrer">Открыть приложение заново</a></Button> : null}

    {!linked && incomingToken ? <section aria-label="Подтверждение привязки" className="space-y-3 rounded-xl border border-border bg-card p-4">
      <h4 className="font-medium">Подтвердите аккаунт</h4>
      {incomingPreview ? <>
        <p className="text-sm text-muted-foreground">
          Связать {platformLabel(incomingPreview.source_identity!.platform)} №{incomingPreview.source_identity!.external_id} с этим аккаунтом {platformLabel(currentAccountPlatform())}?
          Общими станут баланс, история и генерации.
        </p>
        <Button disabled={busy} onClick={() => void run(async signal => {
          const result = await acceptAccountLink(incomingToken, signal, true)
          applyLink(result)
          if (result.state !== 'committed') setMessage('Ожидаем подтверждения со второй стороны.')
        })}>Подтвердить привязку</Button>
      </> : incomingError
        ? <><p role="status" className="text-sm text-muted-foreground">{incomingError}</p>
          <Button variant="outline" disabled={busy} onClick={() => setIncomingRetry(v => v + 1)}>Повторить проверку приглашения</Button></>
        : <p role="status" className="text-sm text-muted-foreground">Проверяем приглашение…</p>}
      <Button variant="ghost" disabled={busy} onClick={() => { setIncomingToken(''); setIncomingPreview(null) }}>Не привязывать</Button>
    </section> : null}

    {!linked && !incomingToken && active && url ? <section aria-label="Ожидание привязки" className="space-y-3 rounded-xl border border-border bg-card p-4">
      <p className="text-sm text-muted-foreground">Открыли {platformLabel(link.target_platform!)}. Подтвердите там свой аккаунт — здесь статус обновится автоматически.</p>
      <Button variant="outline" asChild><a href={url} target="_blank" rel="noopener noreferrer">Открыть {platformLabel(link.target_platform!)} ещё раз</a></Button>
      <Button variant="ghost" disabled={busy} onClick={() => void run(async signal => {
        applyLink(await updateAccountLink(link, 'cancel', signal))
        setUrl('')
      })}>Отменить</Button>
    </section> : null}
    {message ? <p role="status" className="text-sm text-muted-foreground">{message}</p> : null}
    {link?.state === 'committed' ? <p role="status" className="text-sm text-success">Аккаунты связаны.</p> : null}
  </div>
}
