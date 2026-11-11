'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { LinkedAccountsCard } from '@/components/linked-accounts-card'
import { buildTelegramMiniAppUrl } from '@/lib/api'
import { copyTextToClipboard } from '@/lib/clipboard'
import { accountLinkUrl, currentAccountPlatform, incomingAccountLink, nativeTelegramMiniAppUrl, type AccountPlatform } from '@/lib/account-platform'
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
  const [copyMessage, setCopyMessage] = useState('')
  const invitationInput = useRef<HTMLInputElement>(null)
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
    // VK Android/iOS WebView blocks deep links redirected from an asynchronous
    // about:blank popup. Do not launch Telegram until a *separate user click*
    // activates the native tg:// anchor after the invitation is ready.
    // This leaves the source VK WebView intact to poll for confirmation.
    setCopyMessage('')
    void run(async signal => {
      const created = await createAccountLink(target, signal, true)
      if (created.source_confirmed !== true) throw new Error('Сервер привязки требует обновления. Попробуйте позже.')
      if (signal.aborted) return
      const targetUrl = accountLinkUrl(target, created.token || '', destination.vkAppId, destination.telegramBotUsername)
      setLink(created)
      setUrl(targetUrl)
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
          В мини-приложении будут доступны баланс, история и генерации Telegram-аккаунта. Средства старого VK-бота пока остаются отдельно и автоматически не переносятся.
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
      <p className="text-sm text-muted-foreground">{link.target_platform === 'telegram'
        ? 'Приглашение подготовлено. Нажмите «Открыть приложение Telegram» — открытие должно происходить по вашему нажатию. Подтвердите привязку там; здесь статус обновится автоматически.'
        : 'Приглашение подготовлено. Откройте ВКонтакте по ссылке ниже и подтвердите там свой аккаунт — здесь статус обновится автоматически.'}</p>
      {link.target_platform === 'telegram' ? <>
        <Button asChild className="w-full"><a href={nativeTelegramMiniAppUrl(url)} target="_self">Открыть приложение Telegram</a></Button>
        <Button variant="outline" asChild><a href={url} target="_blank" rel="noopener noreferrer">Открыть через браузер</a></Button>
        <label className="block text-xs text-muted-foreground" htmlFor="telegram-invitation">Если VK не запускает Telegram, скопируйте ссылку и откройте её в Telegram.</label>
        <input id="telegram-invitation" ref={invitationInput} value={url} readOnly autoComplete="off"
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs" />
        <Button variant="outline" onClick={() => void copyTextToClipboard(url, invitationInput.current)
          .then(() => setCopyMessage('Ссылка скопирована.'))
          .catch(() => {
            invitationInput.current?.focus()
            invitationInput.current?.select()
            setCopyMessage('Выделите и скопируйте ссылку вручную.')
          })}>Скопировать ссылку</Button>
        {copyMessage ? <p role="status" className="text-xs text-muted-foreground">{copyMessage}</p> : null}
      </> : <Button variant="outline" asChild><a href={url} target="_blank" rel="noopener noreferrer">Открыть ВКонтакте ещё раз</a></Button>}
      <Button variant="ghost" disabled={busy} onClick={() => void run(async signal => {
        applyLink(await updateAccountLink(link, 'cancel', signal))
        setUrl('')
      })}>Отменить</Button>
    </section> : null}
    {message ? <p role="status" className="text-sm text-muted-foreground">{message}</p> : null}
    {link?.state === 'committed' ? <p role="status" className="text-sm text-success">Аккаунты связаны.</p> : null}
  </div>
}
