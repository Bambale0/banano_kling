'use client'

import { useEffect, useState } from 'react'
import { ArrowRight, CircleCheck, Link2, LoaderCircle, LogOut, ShieldCheck } from 'lucide-react'
import { clearBrowserAccountCredentials, revokeBrowserAccountSession } from '@/lib/browser-account-session'

type BrowserAccount = {
  ok: boolean
  account_id: string
  studio_mode: 'web'
  connected: string[]
  telegram_linked: boolean
  can_generate: boolean
  balance: { available: string; reserved: string; revision: number }
}

const methodNames: Record<string, string> = {
  yandex: 'Яндекс ID', google: 'Google', email: 'Почта',
}

export function WebAccountWorkspace() {
  const [account, setAccount] = useState<BrowserAccount | null>(null)
  const [error, setError] = useState('')
  const [exiting, setExiting] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    void (async () => {
      try {
        const response = await fetch('/mini-app/api/web-auth/account', {
          credentials: 'same-origin', cache: 'no-store',
          headers: { Accept: 'application/json' }, signal: controller.signal,
        })
        if (response.status === 401) {
          if (!controller.signal.aborted) window.location.replace('/login')
          return
        }
        const data = await response.json() as BrowserAccount
        if (!response.ok || data.ok !== true || data.studio_mode !== 'web'
          || !/^[a-f0-9]{32}$/.test(data.account_id)
          || !Array.isArray(data.connected) || !data.balance) {
          throw new Error('Некорректный ответ сервера.')
        }
        if (!controller.signal.aborted) setAccount(data)
      } catch {
        if (!controller.signal.aborted) setError('Не удалось загрузить веб-аккаунт. Обновите страницу.')
      }
    })()
    return () => controller.abort()
  }, [])

  const signOut = async () => {
    if (exiting) return
    setExiting(true)
    setError('')
    try {
      // Server-side revocation is mandatory: clearing client state alone
      // would silently restore the existing Yandex/Google/email cookie.
      await revokeBrowserAccountSession()
      clearBrowserAccountCredentials()
      window.location.replace('/login')
    } catch {
      setError('Не удалось завершить сессию. Попробуйте ещё раз.')
      setExiting(false)
    }
  }

  return (
    <main className="min-h-dvh bg-[#0a0e11] px-4 py-7 text-[#f0e9df] sm:px-8" aria-label="Веб-аккаунт NEUROMIX">
      <div className="mx-auto max-w-4xl space-y-7">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[#8e7144]/40 pb-5">
          <a href="/" className="text-xl font-black tracking-[0.15em]">NEUROMIX</a>
          <button type="button" disabled={exiting}
            className="inline-flex min-h-11 items-center gap-2 border border-[#99805a]/50 px-4 text-sm text-[#ead9bb] hover:bg-[#c99e53]/10 disabled:opacity-60"
            onClick={() => void signOut()}>
            {exiting ? <LoaderCircle className="size-4 animate-spin" /> : <LogOut className="size-4" />}
            Выйти из аккаунта
          </button>
        </header>
        {error ? <p role="alert" className="border border-red-800/60 p-4 text-sm text-[#ffb6aa]">{error}</p> : null}
        {!account && !error ? <p role="status" className="inline-flex items-center gap-3 text-[#e7bd75]">
          <LoaderCircle className="size-5 animate-spin" /> Подтверждаем веб-сессию…
        </p> : null}
        {account ? <>
          <section className="space-y-4 border-l-4 border-[#d0a256] pl-5">
            <p className="inline-flex items-center gap-2 text-sm text-[#dbb979]">
              <CircleCheck className="size-4" /> Вход подтверждён
            </p>
            <h1 className="text-3xl font-black tracking-tight sm:text-5xl">Ваш аккаунт NEUROMIX</h1>
            <p className="max-w-2xl text-[#bdbbb7]">
              Вы вошли через браузер без Telegram. Веб-учётная запись существует отдельно;
              средства и история других аккаунтов не подключаются автоматически.
            </p>
          </section>
          <div className="grid gap-4 sm:grid-cols-2">
            <section className="border border-[#a48350]/40 bg-[#141919] p-5">
              <h2 className="mb-3 inline-flex items-center gap-2 font-semibold">
                <ShieldCheck className="size-5 text-[#d2a659]" /> Способы входа
              </h2>
              <p className="text-sm text-[#d3c9b7]">
                {account.connected.map(provider => methodNames[provider] || provider).join(' · ') || 'Веб-аккаунт'}
              </p>
              <p className="mt-3 text-xs text-[#8e908e]">Идентификатор аккаунта: {account.account_id.slice(0, 8)}</p>
            </section>
            <section className="border border-[#a48350]/40 bg-[#141919] p-5">
              <h2 className="mb-3 font-semibold">Отдельный веб-баланс</h2>
              <p className="text-3xl font-black tabular-nums text-[#f0c779]">{account.balance.available}</p>
              <p className="mt-3 text-xs text-[#a5a29d]">Не объединён с балансом Telegram без подтверждённой привязки.</p>
            </section>
          </div>
          <section className="space-y-4 border border-[#a48350]/40 p-5">
            <h2 className="text-xl font-bold">Генерации в браузере</h2>
            {account.can_generate ? (
              <p role="status">Веб-генерации доступны.</p>
            ) : (
              <p role="status" className="text-sm leading-relaxed text-[#c7c0b4]">
                Для независимых веб-аккаунтов запуск генераций и пополнение пока не активированы:
                необходимо подключить отдельный платёжный контур и очередь задач.
                Telegram для самого входа не требуется; списаний в этом режиме нет.
              </p>
            )}
            {!account.telegram_linked ? <a href="/login?link=telegram"
              className="inline-flex min-h-11 items-center gap-2 border border-[#c7a061] px-4 py-2 text-sm font-semibold text-[#efd09a] hover:bg-[#c7a061]/10">
              <Link2 className="size-4" /> Связать Telegram (по желанию) <ArrowRight className="size-4" />
            </a> : null}
          </section>
        </> : null}
      </div>
    </main>
  )
}
