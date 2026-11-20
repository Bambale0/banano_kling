'use client'

import { useEffect, useState } from 'react'
import { WebPaymentsPanel } from './web-payments-panel'
import { WebGenerationPanel } from './web-generation-panel'
import { WebOmniAssetsPanel } from './web-omni-assets-panel'
import { ArrowRight, CircleCheck, Link2, LoaderCircle, LogOut, ShieldCheck } from 'lucide-react'
import { clearBrowserAccountCredentials, revokeBrowserAccountSession } from '@/lib/browser-account-session'

type BrowserAccount = {
  ok: boolean
  account_id: string
  studio_mode: 'web'
  connected: string[]
  telegram_linked: boolean
  can_generate: boolean
  can_topup?: boolean
  providers?: { yandex?: boolean; google?: boolean; email?: boolean }
  balance: { available: string; reserved: string; revision: number }
}

type WebTask = {
  task_id: string
  type: 'image' | 'video' | 'asset'
  model: string
  status: 'pending' | 'completed' | 'failed'
  result_url: string | null
  created_at_epoch: number
  bundle_url?: string | null
  output_count?: number | null
  cost?: string | null
  result_seconds?: string | null
  asset_kind?: 'audio' | 'character' | null
  asset_id?: string | null
}

const methodNames: Record<string, string> = {
  yandex: 'Яндекс ID', google: 'Google', email: 'Почта',
}

export function WebAccountWorkspace() {
  const [account, setAccount] = useState<BrowserAccount | null>(null)
  const [referral, setReferral] = useState<{ url: string; registrations: number } | null>(null)
  const [copied, setCopied] = useState(false)
  const [history, setHistory] = useState<WebTask[] | null>(null)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [historyBusy, setHistoryBusy] = useState(false)
  const [historyError, setHistoryError] = useState('')
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
        // A self-owned referral link has no messenger URL and never credits
        // money on registration; confirmed purchases are handled separately.
        try {
        const referralResponse = await fetch('/mini-app/api/web-auth/referral', {
          credentials: 'same-origin', cache: 'no-store',
          headers: { Accept: 'application/json' }, signal: controller.signal,
        })
        if (referralResponse.ok) {
          const referralPayload = await referralResponse.json() as {
            ok?: boolean; url?: string; registrations?: number
          }
          if (referralPayload.ok && referralPayload.url?.startsWith(window.location.origin + '/login?')
            && !controller.signal.aborted) {
            setReferral({ url: referralPayload.url, registrations: Number(referralPayload.registrations || 0) })
          }
        }
        } catch {
          // Referral link is optional; a temporary referral-service failure
          // must never make an authenticated account appear logged out.
        }
      } catch {
        if (!controller.signal.aborted) setError('Не удалось загрузить веб-аккаунт. Обновите страницу.')
      }
    })()
    return () => controller.abort()
  }, [])

  const loadHistory = async (cursor?: string) => {
    if (historyBusy) return
    setHistoryBusy(true)
    setHistoryError('')
    try {
      const url = new URL('/mini-app/api/web-auth/history', window.location.origin)
      if (cursor) url.searchParams.set('cursor', cursor)
      const response = await fetch(url.pathname + url.search, {
        credentials: 'same-origin', cache: 'no-store',
        headers: { Accept: 'application/json' },
      })
      const data = await response.json() as {
        ok?: boolean; recent_tasks?: WebTask[]; next_cursor?: string | null
      }
      if (!response.ok || !data.ok || !Array.isArray(data.recent_tasks)) throw new Error('history')
      setHistory(previous => cursor ? [...(previous || []), ...data.recent_tasks!] : data.recent_tasks!)
      setNextCursor(data.next_cursor || null)
    } catch {
      setHistoryError('Не удалось загрузить историю веб-работ. Попробуйте снова.')
    } finally {
      setHistoryBusy(false)
    }
  }

  const refreshAccount = async () => {
    try {
      const response = await fetch('/mini-app/api/web-auth/account', {
        credentials: 'same-origin', cache: 'no-store',
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) return
      const data = await response.json() as BrowserAccount
      if (data.ok && /^[a-f0-9]{32}$/.test(data.account_id)) setAccount(data)
    } catch {
      // The existing balance stays visible until a successful refresh.
    }
  }

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
          <a href="/mini-app/" className="text-sm text-[#efd09a] underline">Вернуться в студию</a>
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
              <div className="mt-5 space-y-2">
                <p className="text-xs text-[#bbb2a6]">Привязать другой способ входа (по желанию)</p>
                {(account.providers?.yandex && !account.connected.includes('yandex')) ? <a
                  className="block text-sm text-[#e6c37f] underline"
                  href="/mini-app/api/web-auth/start/yandex?intent=link">Связать Яндекс ID</a> : null}
                {(account.providers?.google && !account.connected.includes('google')) ? <a
                  className="block text-sm text-[#e6c37f] underline"
                  href="/mini-app/api/web-auth/start/google?intent=link">Связать Google</a> : null}
                {(account.providers?.email && !account.connected.includes('email')) ? <a
                  className="block text-sm text-[#e6c37f] underline"
                  href="/login?link=email">Связать почту</a> : null}
              </div>
            </section>
            <section className="border border-[#a48350]/40 bg-[#141919] p-5">
              <h2 className="mb-3 font-semibold">Отдельный веб-баланс</h2>
              <p className="text-3xl font-black tabular-nums text-[#f0c779]">{account.balance.available}</p>
              <p className="mt-3 text-xs text-[#a5a29d]">Не объединён с балансом Telegram без подтверждённой привязки.</p>
            </section>
          </div>
          {referral ? <section className="space-y-3 border border-[#a48350]/40 p-5" aria-label="Реферальная ссылка">
            <h2 className="text-xl font-bold">Пригласить в NEUROMIX</h2>
            <p className="text-sm text-[#c7c0b4]">Веб-ссылка работает без Telegram и других мессенджеров.
              Регистрации сами по себе не начисляют вознаграждение.</p>
            <div className="flex flex-wrap gap-2">
              <input type="text" readOnly aria-label="Веб-реферальная ссылка"
                value={referral.url} className="min-h-11 min-w-0 flex-1 border border-[#92754a] bg-black/30 px-3 text-sm" />
              <button type="button" className="min-h-11 border border-[#c7a061] px-4 text-sm text-[#efd09a]"
                onClick={() => {
                  void navigator.clipboard.writeText(referral.url).then(() => {
                    setCopied(true)
                  }).catch(() => { setCopied(false) })
                }}>
                {copied ? 'Скопировано' : 'Скопировать'}
              </button>
            </div>
            <p className="text-xs text-[#9d9b96]">Регистраций по ссылке: {referral.registrations}</p>
          </section> : null}
          {account.can_topup ? <WebPaymentsPanel
            onBalanceChanged={() => { void refreshAccount() }}
          /> : <section className="space-y-2 border border-[#a48350]/40 p-5">
            <h2 className="text-xl font-bold">Пополнение веб-баланса</h2>
            <p className="text-sm text-[#bcb7af]">Независимые веб-платежи ещё не включены
              на этом сервере. Списание через Telegram ID запрещено.</p>
          </section>}
          <section className="space-y-4 border border-[#a48350]/40 p-5" aria-label="История веб-работ">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-xl font-bold">Мои веб-работы</h2>
              <button type="button" disabled={historyBusy} onClick={() => void loadHistory()}
                className="min-h-10 border border-[#c7a061]/70 px-3 text-sm text-[#f3cf92] disabled:opacity-60">
                {historyBusy ? 'Загружаем…' : history ? 'Обновить историю' : 'Показать историю'}
              </button>
            </div>
            <p className="text-sm text-[#bab4aa]">Только результаты, принадлежащие этому веб-аккаунту.
              Работы Telegram без подтверждённой связки сюда не копируются.</p>
            {historyError ? <p role="alert" className="text-sm text-red-300">{historyError}</p> : null}
            {history?.length === 0 ? <p role="status" className="text-sm text-[#c7c0b4]">
              Веб-работ пока нет.
            </p> : null}
            {history?.length ? <div className="space-y-3">
              {history.map(task => <article key={task.task_id}
                className="space-y-2 border border-[#9d7c47]/35 bg-[#111716] p-3">
                <p className="text-sm font-semibold">{
                  task.type === 'asset'
                    ? (task.asset_kind === 'audio' ? 'Audio ID' : 'Character ID')
                    : task.type === 'image' ? 'Изображение' : 'Видео'
                } · {task.model}</p>
                <p className="text-xs text-[#b8b7b1]">
                  {task.status === 'completed' ? 'Готово' : task.status === 'pending' ? 'В обработке' : 'Не удалось завершить'}
                </p>
                {task.result_seconds ? <p className="text-xs text-[#d8c8a6]">
                  Длительность видео: {task.result_seconds} сек.
                  {task.cost ? ' Списано: ' + task.cost + ' кредитов.' : ''}
                </p> : null}
                {task.output_count ? <p className="text-xs text-[#d8c8a6]">
                  Изображений и слоёв: {task.output_count}.
                  {task.cost ? ' Списано: ' + task.cost + ' кредитов.' : ''}
                </p> : null}
                <div className="flex flex-wrap gap-4">
                  {task.result_url ? <a href={task.result_url} target="_blank" rel="noopener noreferrer"
                    className="text-sm text-[#f1ca8a] underline">Открыть результат</a> : null}
                  {task.bundle_url ? <a href={task.bundle_url} target="_blank" rel="noopener noreferrer"
                    className="text-sm text-[#f1ca8a] underline">Скачать слои ZIP</a> : null}
                </div>
              </article>)}
              {nextCursor ? <button type="button" disabled={historyBusy}
                className="min-h-10 border border-[#c7a061]/70 px-3 text-sm text-[#f3cf92]"
                onClick={() => void loadHistory(nextCursor)}>Показать ещё</button> : null}
            </div> : null}
          </section>
          <section className="space-y-4 border border-[#a48350]/40 p-5">
            <h2 className="text-xl font-bold">Генерации в браузере</h2>
            {account.can_generate ? (<div className="space-y-5">
              <WebOmniAssetsPanel
                onBalanceChanged={() => { void refreshAccount() }}
                onTaskChanged={() => { void loadHistory() }}
              />
              <WebGenerationPanel
                onBalanceChanged={() => { void refreshAccount() }}
                onTaskChanged={() => { void loadHistory() }}
              />
              </div>
            ) : account.telegram_linked ? (
              <p role="status" className="text-sm text-[#d5c8aa]">
                Аккаунт Telegram подключён. Можно пользоваться существующей студией
                и её балансом; независимая веб-генерация пока отключена на сервере.
              </p>
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
