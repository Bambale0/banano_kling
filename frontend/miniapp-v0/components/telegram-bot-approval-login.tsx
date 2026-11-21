'use client'

import { useEffect, useRef, useState } from 'react'
import { ArrowRight, ExternalLink, LoaderCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'

type Approval = {
  id: string
  url: string
  confirmation_code: string
  expires_in: number
}

type Phase = 'idle' | 'starting' | 'waiting' | 'claiming' | 'error' | 'denied' | 'expired'

const ROOT = '/mini-app/api/web-auth/telegram-approval'

/** A browser-bound device authorization; Telegram alone cannot mint a web session. */
export function TelegramBotApprovalLogin() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [approval, setApproval] = useState<Approval | null>(null)
  const [message, setMessage] = useState('')
  const inFlight = useRef(false)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  useEffect(() => {
    if (!approval) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let failures = 0
    const deadline = Date.now() + approval.expires_in * 1000

    async function poll(): Promise<void> {
      if (controller.signal.aborted) return
      if (Date.now() >= deadline) {
        if (mounted.current) { setPhase('expired'); setMessage('Время подтверждения истекло. Попробуйте снова.') }
        return
      }
      try {
        const response = await fetch(ROOT + '/status?id=' + encodeURIComponent(approval!.id), {
          method: 'GET', credentials: 'same-origin', cache: 'no-store',
          headers: { Accept: 'application/json' }, signal: controller.signal,
        })
        const data = await response.json() as { status?: string }
        if (!response.ok) throw new Error('status_unavailable')
        if (controller.signal.aborted) return
        failures = 0
        if (data.status === 'approved') {
          setPhase('claiming')
          setMessage('Подтверждение получено. Открываем студию…')
          const claimed = await fetch(ROOT + '/claim', {
            method: 'POST', credentials: 'same-origin', cache: 'no-store',
            headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: JSON.stringify({ id: approval!.id }), signal: controller.signal,
          })
          const result = await claimed.json() as { ok?: boolean; status?: string }
          if (!claimed.ok || !result.ok || result.status !== 'authenticated') {
            throw new Error('claim_rejected')
          }
          if (mounted.current && !controller.signal.aborted) {
            // Existing web-auth config resolves the shared Telegram owner and studio bridge.
            window.location.replace('/login' + window.location.search)
          }
          return
        }
        if (data.status === 'denied') {
          setPhase('denied')
          setMessage('Вход отклонён в Telegram. Новая попытка доступна ниже.')
          return
        }
        if (data.status === 'expired' || data.status === 'consumed') {
          setPhase('expired')
          setMessage('Запрос уже истёк или был использован. Начните вход заново.')
          return
        }
        if (data.status !== 'pending') throw new Error('invalid_status')
      } catch {
        if (controller.signal.aborted) return
        failures += 1
        if (failures >= 3) setMessage('Проверяем соединение с сайтом. Подтверждение в Telegram остаётся доступным.')
      }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), failures ? 3000 : 1500)
    }
    void poll()
    return () => { controller.abort(); if (timer) clearTimeout(timer) }
  }, [approval])

  const start = async () => {
    if (inFlight.current || phase === 'waiting' || phase === 'claiming') return
    inFlight.current = true
    setPhase('starting')
    setApproval(null)
    setMessage('Создаём одноразовый запрос для Telegram…')

    // Reserve a tab synchronously with the user's click; async window.open
    // would be blocked in Safari and mobile Chromium.
    const telegramTab = window.open('about:blank', '_blank')
    if (telegramTab) {
      telegramTab.opener = null
      try { telegramTab.document.title = 'Открываем Telegram — NEUROMIX' } catch { /* ignored */ }
    }

    try {
      const response = await fetch(ROOT + '/start', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: '{}',
      })
      const data = await response.json() as Partial<Approval> & { ok?: boolean; error?: string }
      if (!response.ok || !data.ok || !data.id || !data.url ||
          !/^https:\/\/t\.me\/[a-zA-Z0-9_]{5,32}\?start=auth_[A-Za-z0-9_-]{43}$/.test(data.url) ||
          !/^\d{6}$/.test(data.confirmation_code || '') ||
          typeof data.expires_in !== 'number' || !Number.isInteger(data.expires_in) || data.expires_in <= 0) {
        throw new Error(data.error || 'unavailable')
      }
      if (!mounted.current) return
      const ticket = data as Approval
      setApproval(ticket)
      setPhase('waiting')
      setMessage(telegramTab
        ? 'Подтвердите вход в боте и вернитесь на эту страницу.'
        : 'Браузер заблокировал новое окно. Откройте Telegram по ссылке ниже.')
      if (telegramTab && !telegramTab.closed) telegramTab.location.replace(ticket.url)
    } catch {
      if (telegramTab && !telegramTab.closed) telegramTab.close()
      if (mounted.current) {
        setPhase('error')
        setMessage('Не удалось запустить подтверждение. Проверьте соединение и попробуйте снова.')
      }
    } finally {
      inFlight.current = false
    }
  }

  const cancel = async () => {
    if (!approval || phase !== 'waiting') return
    const id = approval.id
    // Changing approval aborts the polling request and any in-flight claim.
    setApproval(null)
    setPhase('denied')
    setMessage('Запрос отменён.')
    try {
      await fetch(ROOT + '/cancel', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      })
    } catch {
      // Server expiry still limits any unconfirmed challenge to five minutes.
      setMessage('Не удалось связаться с сервером. Не подтверждайте запрос в Telegram.')
    }
  }

  const busy = phase === 'starting' || phase === 'claiming'
  return <div className="space-y-3">
    {phase !== 'waiting' && phase !== 'claiming' ? <Button
      type="button" onClick={() => void start()} disabled={busy}
      className="h-14 w-full rounded-sm bg-[#e7b154] text-base font-extrabold text-[#18140e] hover:bg-[#f2c477]"
    >
      {busy ? <LoaderCircle aria-hidden="true" className="mr-2 size-4 animate-spin" /> : null}
      Войти через Telegram
      <ArrowRight aria-hidden="true" className="ml-2 size-4" />
    </Button> : null}
    {approval && (phase === 'waiting' || phase === 'claiming') ? <div
      className="space-y-3 border border-[#b48a46]/50 bg-white/[0.03] p-4"
      aria-live="polite"
    >
      <p className="text-sm font-semibold text-[#f3d392]">Подтвердите вход в боте NEUROMIX</p>
      <p className="text-xs text-[#c4c5c5]">Сверьте код на сайте и в Telegram:</p>
      <p className="text-center text-3xl font-black tracking-[0.25em] text-[#f3d392]">
        {approval.confirmation_code}
      </p>
      <p className="text-xs text-[#b8babd]">Ссылка действует 5 минут. Никому не пересылайте её.</p>
      <a href={approval.url} target="_blank" rel="noopener noreferrer"
        className="flex min-h-11 items-center justify-center gap-2 border border-[#e7b154]/60 text-sm font-semibold text-[#f3d392]">
        Открыть Telegram <ExternalLink aria-hidden="true" className="size-4" />
      </a>
      <button type="button" disabled={phase !== 'waiting'} onClick={() => void cancel()}
        className="w-full text-center text-xs text-[#c1ae8e] underline disabled:opacity-50">
        Отменить вход
      </button>
    </div> : null}
    <p role="status" aria-live="polite" className="text-center text-xs text-[#b8babd]">
      {message || 'Telegram откроет бота с кнопками «Подтвердить» и «Отклонить».'}
    </p>
  </div>
}
