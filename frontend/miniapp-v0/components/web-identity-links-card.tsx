'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { getInitData } from '@/lib/api'

type Provider = 'yandex' | 'google' | 'email'
type IdentityConfig = {
  ok?: boolean
  authenticated?: boolean
  connected?: string[]
  providers?: Partial<Record<Provider | 'telegram', boolean>>
}
type ChallengeResponse = { ok?: boolean; challenge_id?: string; message?: string }
type VerifyResponse = { ok?: boolean }

const AUTH = '/mini-app/api/web-auth'
const METHODS: { key: Provider; title: string; glyph: string; bg: string }[] = [
  { key: 'yandex', title: 'Яндекс ID', glyph: 'Я', bg: 'bg-[#e44438]' },
  { key: 'google', title: 'Google', glyph: 'G', bg: 'bg-[#4285f4]' },
  { key: 'email', title: 'Электронная почта', glyph: '@', bg: 'bg-[#7c6ac8]' },
]

async function getConfig(signal: AbortSignal): Promise<IdentityConfig> {
  const response = await fetch(AUTH + '/config', {
    credentials: 'same-origin', cache: 'no-store', signal,
  })
  if (!response.ok) throw new Error('config_unavailable')
  const data = await response.json() as IdentityConfig
  if (!data.ok) throw new Error('config_invalid')
  return data
}

/** Existing web identity providers on the verified Telegram account.
 * Native Telegram WebApp data creates only a browser session, never new funds. */
export function WebIdentityLinksCard() {
  const [config, setConfig] = useState<IdentityConfig | null>(null)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [emailOpen, setEmailOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [challenge, setChallenge] = useState('')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const refresh = useCallback(() => setReload(value => value + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    let finished = false
    setError('')
    async function load() {
      try {
        let data = await getConfig(controller.signal)
        const signed = getInitData()
        const queryId = signed ? new URLSearchParams(signed).get('query_id') || '' : ''
        const nativeLaunch = Boolean(signed)
          && !queryId.startsWith('webstudio_')
          && !queryId.startsWith('browser_')
          && !signed.startsWith('vk_session:')
        // Even if a website cookie exists, the real Telegram owner must
        // match it. Otherwise a stale browser cookie could expose another
        // person's linked identities inside a native Telegram profile.
        if (nativeLaunch) {
          const result = await fetch(AUTH + '/native-session', {
            method: 'POST', credentials: 'same-origin', cache: 'no-store',
            signal: controller.signal, headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ init_data: signed }),
          })
          if (!result.ok) {
            throw new Error(result.status === 409
              ? 'В веб-сессии открыт другой аккаунт. Выйдите из него перед привязкой.'
              : 'Не удалось подтвердить Telegram-сессию. Откройте приложение заново.')
          }
          data = await getConfig(controller.signal)
        }
        if (!data.authenticated) {
          throw new Error('Для привязки откройте профиль в Telegram или войдите на сайте.')
        }
        if (!controller.signal.aborted) {
          setConfig(data)
          finished = true
        }
      } catch (cause) {
        if (!controller.signal.aborted) {
          setConfig(null)
          setError(cause instanceof Error ? cause.message : 'Не удалось проверить привязки.')
        }
      }
    }
    void load()
    const timeout = window.setTimeout(() => {
      if (finished || controller.signal.aborted) return
      controller.abort()
      setConfig(null)
      setError('Проверка привязок заняла слишком много времени.')
    }, 15000)
    return () => { controller.abort(); window.clearTimeout(timeout) }
  }, [reload])

  async function startEmail(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !config?.providers?.email || config.connected?.includes('email')) return
    setBusy(true); setMessage('')
    try {
      const response = await fetch(AUTH + '/email/start', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), intent: 'link', next: '/mini-app/' }),
      })
      const payload = await response.json() as ChallengeResponse
      if (!response.ok || !payload.ok || !payload.challenge_id) throw new Error('email_send_failed')
      setChallenge(payload.challenge_id)
      setMessage(payload.message || 'Введите шестизначный код из письма.')
    } catch {
      setMessage('Не удалось отправить код. Попробуйте позже.')
    } finally {
      setBusy(false)
    }
  }

  async function verifyEmail(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !challenge || !/^[0-9]{6}$/.test(code)) return
    setBusy(true); setMessage('')
    try {
      const response = await fetch(AUTH + '/email/verify', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ challenge_id: challenge, code }),
      })
      const payload = await response.json() as VerifyResponse
      if (!response.ok || !payload.ok) throw new Error('email_verification_failed')
      setEmailOpen(false); setChallenge(''); setCode(''); setMessage('')
      refresh() // Verified identity and HttpOnly session cookie are already set server-side.
    } catch {
      setMessage('Код неверен, истёк или адрес уже привязан к другому аккаунту.')
    } finally {
      setBusy(false)
    }
  }

  return <section aria-label="Связанные аккаунты"
    className="rounded-[20px] border border-border bg-card px-[19px] pb-2 pt-[19px]">
    <h3 className="mb-3 text-[11px] font-normal uppercase tracking-[0.16em] text-muted-foreground">
      Связанные аккаунты
    </h3>
    <ul className="divide-y divide-border/50">
      {METHODS.map(({ key, title, glyph, bg }) => {
        const linked = config?.connected?.includes(key) || false
        const enabled = config?.providers?.[key] || false
        return <li key={key} className="flex min-h-[67px] items-center gap-3 py-3 min-[360px]:gap-3.5">
          <span aria-hidden="true" className={`flex size-[42px] shrink-0 items-center justify-center rounded-[12px] text-xl font-bold text-white ${bg}`}>
            {glyph}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold leading-6 text-foreground min-[360px]:text-base">{title}</p>
            <p className="text-[13px] leading-5 text-muted-foreground">
              {!config ? error ? 'Статус недоступен' : 'Проверяем…'
                : linked ? 'Привязан' : enabled ? 'Не привязан' : 'Сервис пока не настроен'}
            </p>
          </div>
          {linked ? <span aria-label={key === 'email' ? 'Электронная почта привязана' : `${title} привязан`}
            className="flex size-8 shrink-0 items-center justify-center rounded-full bg-success/15 text-success">
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
              strokeLinejoin="round"><path d="m6 12 4 4 8-10" /></svg>
          </span> : config && enabled && key !== 'email'
            ? <Button variant="outline" asChild className="h-[42px] rounded-full border-border bg-foreground/[0.03] px-3 text-sm font-semibold min-[360px]:px-5">
              <a aria-label={`Привязать ${title}`}
                href={`${AUTH}/start/${key}?intent=link&next=%2Fmini-app%2F`}>Привязать</a>
            </Button>
            : config && enabled && key === 'email'
              ? <Button variant="outline" disabled={busy} onClick={() => {
                setEmailOpen(value => !value)
                setMessage('')
              }} aria-label="Добавить почту"
                className="h-[42px] rounded-full border-border bg-foreground/[0.03] px-3 text-sm font-semibold min-[360px]:px-5">
                Добавить
              </Button>
              : null}
        </li>
      })}
    </ul>
    {config && emailOpen && config.providers?.email && !config.connected?.includes('email')
      ? <div className="space-y-3 border-t border-border/50 py-4">
        {!challenge ? <form onSubmit={event => void startEmail(event)} className="space-y-2">
          <label htmlFor="linked-email-address" className="block text-sm">Адрес электронной почты</label>
          <input id="linked-email-address" autoComplete="email" type="email" required maxLength={254}
            value={email} onChange={event => setEmail(event.target.value)}
            className="min-h-11 w-full rounded-lg border border-border bg-background px-3 text-sm" />
          <Button type="submit" disabled={busy || !email.trim()} className="w-full">
            {busy ? 'Отправляем…' : 'Отправить код'}
          </Button>
        </form> : <form onSubmit={event => void verifyEmail(event)} className="space-y-2">
          <label htmlFor="linked-email-code" className="block text-sm">Код из письма</label>
          <input id="linked-email-code" type="text" inputMode="numeric" pattern="[0-9]{6}"
            autoComplete="one-time-code" value={code} maxLength={6}
            onChange={event => setCode(event.target.value)}
            className="min-h-11 w-full rounded-lg border border-border bg-background px-3 text-sm" />
          <Button type="submit" disabled={busy || !/^[0-9]{6}$/.test(code)} className="w-full">
            {busy ? 'Проверяем…' : 'Подтвердить почту'}
          </Button>
          <Button type="button" variant="ghost" className="w-full" onClick={() => {
            setChallenge(''); setCode(''); setMessage('')
          }}>Запросить новый код</Button>
        </form>}
        {message ? <p role="status" className="text-sm text-muted-foreground">{message}</p> : null}
      </div> : null}
    {config && !config.providers?.email && !config.connected?.includes('email') ? <p
      className="py-2 text-xs text-muted-foreground">
      Добавление почты станет доступно после настройки отправки кодов подтверждения.
    </p> : null}
    <div className="border-t border-border/50 py-3">
      <a href="/login?web=1" target="_blank" rel="noopener noreferrer"
        onClick={event => {
          const native = window.Telegram?.WebApp as
            | ({ openLink?: (url: string) => void }) | undefined
          if (typeof native?.openLink === 'function') {
            // Telegram's native openLink opens the actual website browser;
            // otherwise a new WebView can keep Telegram launch credentials
            // and silently reopen the Telegram-only studio.
            event.preventDefault()
            native.openLink(new URL('/login?web=1', window.location.origin).href)
          }
        }}
        className="text-sm font-semibold text-foreground underline underline-offset-4">
        Открыть самостоятельную веб-версию
      </a>
      <p className="mt-1 text-xs text-muted-foreground">
        Вход в браузере не требует Telegram. Для существующих привязок можно использовать Яндекс ID.
      </p>
    </div>
    {error ? <div className="space-y-2 py-3">
      <p role="status" className="text-sm text-muted-foreground">{error}</p>
      <Button variant="outline" onClick={refresh}>Повторить проверку</Button>
    </div> : null}
  </section>
}
