'use client'

import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, ExternalLink, LoaderCircle, LockKeyhole, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { NoiseTexture } from '@/components/magicui/noise-texture'
import { getInitData } from '@/lib/api'
import { isBrowserPaymentSession, safePaymentReturnTo } from '@/lib/web-payments'

type TelegramLoginUser = {
  id: number
  first_name: string
  last_name?: string
  username?: string
  photo_url?: string
  auth_date: number
  hash: string
}

type LoginState = 'loading-config' | 'loading-widget' | 'ready' | 'verifying' | 'error'

declare global {
  interface Window {
    onNeuromixLandingTelegramAuth?: (user: TelegramLoginUser) => void
  }
}

function browserStartParam(): string | null {
  const query = new URLSearchParams(window.location.search)
  return query.get('startapp') || query.get('tgWebAppStartParam')
}

function studioUrlWithSession(initData: string): string {
  const query = new URLSearchParams(window.location.search)
  const url = new URL(safePaymentReturnTo(query.get('return_to')), window.location.origin)
  const startapp = browserStartParam()
  if (startapp) url.searchParams.set('startapp', startapp)
  url.hash = new URLSearchParams({ tgWebAppData: initData }).toString()
  return url.toString()
}

function LegacyTelegramWidget({ linkYandex = false }: { linkYandex?: boolean } = {}) {
  const widgetRef = useRef<HTMLDivElement>(null)
  const activeRequest = useRef(false)
  const [botUsername, setBotUsername] = useState('')
  const [state, setState] = useState<LoginState>('loading-config')
  const [message, setMessage] = useState('Получаем настройки безопасного входа…')
  const [fallbackStudioUrl, setFallbackStudioUrl] = useState('/mini-app/')

  useEffect(() => {
    // Legacy signed Telegram launches must continue to the existing Mini App;
    // never parse, log or persist their credentials on the marketing page.
    const query = new URLSearchParams(window.location.search)
    setFallbackStudioUrl(safePaymentReturnTo(query.get('return_to')))
    const hash = new URLSearchParams(window.location.hash.slice(1))
    const session = new URLSearchParams(getInitData())
    const age = Date.now() / 1000 - Number(session.get('auth_date'))
    if (isBrowserPaymentSession() && age >= 0 && age < 86400) {
      window.location.replace(studioUrlWithSession(getInitData()))
      return
    }
    if (['tgWebAppData', 'tgWebAppVersion', 'tgWebAppPlatform'].some(
      key => query.has(key) || hash.has(key)
    )) {
      window.location.replace('/mini-app/' + window.location.search + window.location.hash)
      return
    }

    const controller = new AbortController()
    async function loadConfig() {
      try {
        const response = await fetch('/mini-app/api/browser-auth/config?legacy=1', {
          method: 'GET',
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
          cache: 'no-store',
          signal: controller.signal,
        })
        if (!response.ok) throw new Error('config-unavailable')
        const data = await response.json() as { ok?: boolean; bot_username?: string }
        const username = typeof data.bot_username === 'string'
          ? data.bot_username.replace(/^@/, '').trim()
          : ''
        if (!data.ok || !/^[a-zA-Z0-9_]{5,32}$/.test(username)) {
          throw new Error('invalid-config')
        }
        if (!controller.signal.aborted) {
          setBotUsername(username)
          setState('loading-widget')
          setMessage('Загружаем вход через Telegram…')
        }
      } catch {
        if (!controller.signal.aborted) {
          setState('error')
          setMessage('Не удалось загрузить вход. Откройте студию и попробуйте там.')
        }
      }
    }
    void loadConfig()
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!botUsername || !widgetRef.current) return
    const container = widgetRef.current
    let cancelled = false
    const controller = new AbortController()
    container.replaceChildren()

    window.onNeuromixLandingTelegramAuth = async (user: TelegramLoginUser) => {
      if (activeRequest.current) return
      activeRequest.current = true
      setState('verifying')
      setMessage('Проверяем вход в Telegram…')
      try {
        // This is the existing production server-side signature verifier,
        // not a fabricated Telegram ID or a separate authentication system.
        let response = await fetch(
          '/mini-app/api/web-auth/telegram', {
          method: 'POST',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          cache: 'no-store',
          signal: controller.signal,
          body: JSON.stringify({
            telegram_auth: user, intent: linkYandex ? 'link' : 'login',
            next: '/login' + window.location.search,
          }),
        })
        let data = await response.json() as {
          ok?: boolean; init_data?: string
        }
        if (response.status === 409 && !linkYandex) {
          // Existing legacy Telegram accounts with an older shared-link
          // mapping must retain their working Telegram studio. Only a
          // verified legacy login can be the fallback; never force-link.
          const legacy = await fetch('/mini-app/api/browser-auth', {
            method: 'POST', credentials: 'same-origin', cache: 'no-store',
            headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
            signal: controller.signal,
            body: JSON.stringify({ telegram_auth: user }),
          })
          data = await legacy.json() as { ok?: boolean; init_data?: string }
          response = legacy
        }
        // Both the verified shared-account route and its signed legacy
        // fallback must return a successful HTTP response and verified payload.
        if (!response.ok || !data.ok) throw new Error('verification-failed')
        if (typeof data.init_data === 'string' && data.init_data && !cancelled) {
          window.location.replace(studioUrlWithSession(data.init_data))
        } else {
          throw new Error('missing-session')
        }
      } catch {
        if (!cancelled) {
          setState('error')
          setMessage(linkYandex
            ? 'Не удалось связать аккаунты. Попробуй ещё раз или открой студию через Telegram.'
            : 'Не удалось подтвердить вход. Попробуйте ещё раз или войдите из студии.')
        }
      } finally {
        activeRequest.current = false
      }
    }

    const widget = document.createElement('script')
    widget.async = true
    widget.src = 'https://telegram.org/js/telegram-widget.js?22'
    widget.setAttribute('data-telegram-login', botUsername)
    widget.setAttribute('data-size', 'large')
    widget.setAttribute('data-radius', '8')
    widget.setAttribute('data-userpic', 'false')
    widget.setAttribute('data-onauth', 'onNeuromixLandingTelegramAuth(user)')
    widget.onload = () => {
      if (!cancelled) {
        setState(current => current === 'loading-widget' ? 'ready' : current)
        setMessage('Выберите Telegram, чтобы войти в существующий аккаунт.')
      }
    }
    widget.onerror = () => {
      if (!cancelled) {
        setState('error')
        setMessage('Telegram не загрузился. Откройте студию, чтобы войти другим способом.')
      }
    }
    container.appendChild(widget)

    return () => {
      cancelled = true
      controller.abort()
      delete window.onNeuromixLandingTelegramAuth
      container.replaceChildren()
    }
  }, [botUsername, linkYandex])

  const loading = state === 'loading-config' || state === 'loading-widget' || state === 'verifying'

  return (
    <div className="space-y-4">
      <div className="flex min-h-14 items-center justify-center rounded-sm border border-[#d4a34b]/40 bg-[#e4ab47]/[0.07] px-3 py-3">
        {state === 'loading-config' || state === 'verifying' ? (
          <LoaderCircle aria-hidden="true" className="h-5 w-5 animate-spin text-[#f3c76a]" />
        ) : null}
        <div
          ref={widgetRef}
          aria-label="Вход через Telegram"
          className={state === 'verifying' ? 'pointer-events-none opacity-40' : ''}
        />
      </div>
      <p aria-live="polite" role="status" className={state === 'error' ? 'text-center text-sm text-amber-300' : 'text-center text-xs text-[#b8babd]'}>
        {message}
      </p>
      {loading ? <div className="h-1 w-full overflow-hidden bg-white/10"><div className="h-full w-1/3 animate-pulse bg-[#dfac56]" /></div> : null}
      <Button asChild variant="outline" className="h-11 w-full rounded-sm border-[#907647] bg-transparent text-[#f4ebdd] hover:bg-[#dba64b]/10 hover:text-white">
          <a href={fallbackStudioUrl}>
          Или откройте существующую студию
          <ExternalLink aria-hidden="true" className="ml-1 h-4 w-4" />
        </a>
      </Button>
    </div>
  )
}


type TelegramOIDCResult = { id_token?: string; error?: string }
type TelegramOIDCClient = {
  auth: (
    options: { client_id: number; scope: string[]; nonce: string; lang: string },
    callback: (result: TelegramOIDCResult) => void
  ) => void
}

function telegramOIDCClient(): TelegramOIDCClient | null {
  return (window as unknown as { Telegram?: { Login?: TelegramOIDCClient } }).Telegram?.Login || null
}

/** Primary one-click login: the official OIDC SDK opens the Telegram approval prompt. */
function TelegramOIDCLogin({ linkAccount = false }: { linkAccount?: boolean }) {
  const [config, setConfig] = useState<{ clientId: number; nonce: string } | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'verifying' | 'error'>('loading')
  const [message, setMessage] = useState('Готовим быстрый вход через Telegram…')
  const [showLegacy, setShowLegacy] = useState(false)
  const activeRequest = useRef(false)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    const query = new URLSearchParams(window.location.search)
    const hash = new URLSearchParams(window.location.hash.slice(1))
    const initData = getInitData()
    const session = new URLSearchParams(initData)
    const age = Date.now() / 1000 - Number(session.get('auth_date'))
    // A valid browser session resumes the requested payment intent without
    // opening Telegram approval again.
    if (isBrowserPaymentSession() && age >= 0 && age < 86400) {
      window.location.replace(studioUrlWithSession(initData))
      return
    }
    const controller = new AbortController()
    // Native Telegram Mini App launches should never enter a browser auth loop.
    if (['tgWebAppData', 'tgWebAppVersion', 'tgWebAppPlatform'].some(
      key => query.has(key) || hash.has(key)
    )) {
      window.location.replace('/mini-app/' + window.location.search + window.location.hash)
      return
    }

    const script = document.createElement('script')
    script.async = true
    script.src = 'https://telegram.org/js/telegram-login.js'
    const prepare = async () => {
      try {
        const response = await fetch('/mini-app/api/browser-auth/config', {
          method: 'GET',
          headers: { Accept: 'application/json' },
          credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
        })
        if (!response.ok) throw new Error('config-unavailable')
        const data = await response.json() as {
          ok?: boolean; oidc_client_id?: string; oidc_nonce?: string
        }
        const clientId = Number(data.oidc_client_id)
        if (!data.ok || !Number.isSafeInteger(clientId) || clientId <= 0 ||
            typeof data.oidc_nonce !== 'string' || data.oidc_nonce.length < 24) {
          throw new Error('oidc-unavailable')
        }
        if (controller.signal.aborted || !mounted.current) return
        setConfig({ clientId, nonce: data.oidc_nonce })
        script.onload = () => {
          if (!mounted.current) return
          if (telegramOIDCClient()) {
            setState('ready')
            setMessage('Telegram откроет подтверждение входа. Номер вводить не нужно.')
          } else {
            setState('error')
            setShowLegacy(true)
            setMessage('Сейчас этот способ не работает. Попробуй другой ниже.')
          }
        }
        script.onerror = () => {
          if (mounted.current) {
            setState('error')
            setShowLegacy(true)
            setMessage('Не удалось открыть Telegram. Попробуй другой способ ниже.')
          }
        }
        document.head.appendChild(script)
      } catch {
        if (mounted.current && !controller.signal.aborted) {
          setState('error')
          setShowLegacy(true)
          setMessage('Не получилось войти сразу. Попробуй другой способ ниже.')
        }
      }
    }
    void prepare()
    return () => {
      mounted.current = false
      controller.abort()
      script.remove()
    }
  }, [])

  const startLogin = () => {
    const sdk = telegramOIDCClient()
    if (!config || !sdk || state !== 'ready' || activeRequest.current) return
    // Must run directly in the click handler so mobile browsers allow the popup.
    setMessage('Подтверди вход в Telegram и вернись сюда…')
    try {
      sdk.auth({
        client_id: config.clientId,
        scope: ['profile'], // no phone number or bot-write access requested
        nonce: config.nonce,
        lang: 'ru',
      }, (result) => {
        if (!mounted.current) return
        if (!result?.id_token) {
          setState('ready')
          setMessage(result?.error
            ? 'Telegram не подтвердил вход. Попробуйте ещё раз.'
            : 'Вход отменён. Можно попробовать снова.')
          return
        }
        if (activeRequest.current) return
        activeRequest.current = true
        setState('verifying')
        setMessage('Проверяем подтверждение Telegram…')
        void (async () => {
          try {
            const response = await fetch('/mini-app/api/browser-auth/account', {
              method: 'POST',
              headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
              credentials: 'same-origin',
              cache: 'no-store',
              body: JSON.stringify({
                id_token: result.id_token,
                intent: linkAccount ? 'link' : 'login',
                next: '/login' + window.location.search,
              }),
            })
            let data = await response.json() as { ok?: boolean; init_data?: string }
            if (response.status === 409 && !linkAccount) {
              const legacy = await fetch('/mini-app/api/browser-auth', {
                method: 'POST', credentials: 'same-origin', cache: 'no-store',
                headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
                body: JSON.stringify({ id_token: result.id_token }),
              })
              data = await legacy.json() as { ok?: boolean; init_data?: string }
              if (!legacy.ok) throw new Error('auth-failed')
            } else if (!response.ok) throw new Error('auth-failed')
            if (!data.ok || !data.init_data) throw new Error('auth-failed')
            if (mounted.current) window.location.replace(studioUrlWithSession(data.init_data))
          } catch {
            if (mounted.current) {
              setState('ready')
              setMessage('Подтверждение не удалось проверить. Попробуйте снова.')
            }
          } finally {
            activeRequest.current = false
          }
        })()
      })
    } catch {
      setState('error')
      setMessage('Не получилось открыть Telegram. Попробуйте резервный вход.')
    }
  }

  return (
    <div className="space-y-4">
      {!(state === 'error' && showLegacy) ? <Button
        type="button"
        className="h-14 w-full rounded-sm bg-[#e7b154] text-base font-extrabold text-[#18140e] hover:bg-[#f2c477]"
        onClick={startLogin}
        disabled={state !== 'ready'}
        aria-label="Продолжить через Telegram"
      >
        {state === 'loading' || state === 'verifying'
          ? <LoaderCircle aria-hidden="true" className="mr-2 size-4 animate-spin" />
          : null}
        Продолжить через Telegram
        <ArrowRight aria-hidden="true" className="ml-2 size-4" />
      </Button> : null}
      <p aria-live="polite" role="status" className="text-center text-xs text-[#b8babd]">
        {message}
      </p>
      <button type="button" className="w-full text-center text-xs text-[#dbb76d] underline underline-offset-4"
        onClick={() => setShowLegacy(current => !current)}
        aria-expanded={showLegacy}
      >
        {showLegacy ? 'Скрыть резервный способ' : 'Telegram не открылся? Другой способ входа'}
      </button>
      {showLegacy ? <LegacyTelegramWidget /> : null}
    </div>
  )
}

type BrowserProviderConfig = {
  ok?: boolean
  authenticated?: boolean
  studio_ready?: boolean
  providers?: { yandex?: boolean; google?: boolean; email?: boolean; telegram?: boolean }
}

export function BrowserProviderLogin({ onSessionDetected }: { onSessionDetected: (authenticated: boolean) => void }) {
  const [config, setConfig] = useState<BrowserProviderConfig | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        const response = await fetch('/mini-app/api/web-auth/config', {
          credentials: 'same-origin', cache: 'no-store',
          headers: { Accept: 'application/json' }, signal: controller.signal,
        })
        if (!response.ok) return
        const data = await response.json() as BrowserProviderConfig
        if (!controller.signal.aborted) {
          setConfig(data)
          onSessionDetected(Boolean(data.authenticated))
        }
        const query = new URLSearchParams(window.location.search)
        const linkIntent = query.get('link')
        const isExplicitLink = linkIntent === 'telegram' || linkIntent === 'email'
        if (data.authenticated && (query.has('linked') || query.has('manage'))) {
          window.location.replace('/account/')
          return
        }
        if (data.authenticated && !data.studio_ready && !isExplicitLink) {
          window.location.replace('/mini-app/')
          return
        }
        if (data.authenticated && data.studio_ready && !isExplicitLink) {
          const studio = await fetch('/mini-app/api/web-auth/studio', {
            method: 'POST', credentials: 'same-origin', cache: 'no-store',
            headers: { Accept: 'application/json' }, signal: controller.signal,
          })
          const session = await studio.json() as { ok?: boolean; init_data?: string }
          if (studio.ok && session.ok && session.init_data && !controller.signal.aborted) {
            window.location.replace(studioUrlWithSession(session.init_data))
          } else if (!controller.signal.aborted) {
            setError('Не получилось открыть студию. Попробуй ещё раз.')
          }
        }
      } catch {
        if (!controller.signal.aborted) setError('Не удалось проверить веб-авторизацию.')
      }
    }
    void load()
    return () => controller.abort()
  }, [onSessionDetected])

  if (!config?.providers?.yandex && !config?.providers?.google && !config?.providers?.email && !config?.authenticated) return null
  if (config.authenticated && !config.studio_ready
    && !['telegram', 'email'].includes(new URLSearchParams(window.location.search).get('link') || '')) {
    return <p role="status" className="text-sm text-[#d7b56f]">Вход подтверждён. Открываем веб-аккаунт…</p>
  }
  if (config.authenticated && new URLSearchParams(window.location.search).get('link') === 'email') {
    return <EmailCodeLogin intent="link" />
  }
  if (config.authenticated && !config.studio_ready) {
    return (
      <section className="space-y-3 border border-[#d5af60]/40 bg-[#d5af60]/[0.055] p-4" aria-label="Вход через Яндекс">
        <p className="font-semibold text-[#f3d392]">Веб-вход подтверждён</p>
        <p className="text-sm text-[#ddd6c8]">
          Привязка Telegram добровольная. Она нужна только для доступа к уже существующим
          работам и балансу Telegram; независимая веб-учётная запись не требует мессенджера.
        </p>
        <LegacyTelegramWidget linkYandex />
        {error ? <p role="status" className="text-xs text-amber-300">{error}</p> : null}
      </section>
    )
  }
  if (config.authenticated) return <p role="status" className="text-sm text-[#d7b56f]">Открываем студию… {error}</p>

  return (
    <div className="space-y-3">
      {config.providers?.yandex ? <a
        href="/mini-app/api/web-auth/start/yandex"
        onClick={event => {
          event.preventDefault()
          window.location.assign('/mini-app/api/web-auth/start/yandex?next=' +
            encodeURIComponent('/login' + window.location.search))
        }}
        className="flex min-h-12 items-center justify-center border border-[#e7b154]/50 bg-white/[0.03] px-4 text-sm font-semibold text-[#f3d392] hover:bg-[#e7b154]/10"
      >Продолжить с Яндекс ID</a> : null}
      {config.providers?.google ? <a
        href="/mini-app/api/web-auth/start/google"
        onClick={event => {
          event.preventDefault()
          window.location.assign('/mini-app/api/web-auth/start/google?next=' +
            encodeURIComponent('/login' + window.location.search))
        }}
        className="flex min-h-12 items-center justify-center border border-[#e7b154]/50 bg-white/[0.03] px-4 text-sm font-semibold text-[#f3d392] hover:bg-[#e7b154]/10"
      >Продолжить с Google</a> : null}
      {config.providers?.email ? <EmailCodeLogin intent="login" /> : null}
    </div>
  )
}

/** Email OTP is deliberately server-backed. The code/challenge stay in component
 * memory, never in URL, logs, sessionStorage or localStorage.
 */
export function EmailCodeLogin({ intent }: { intent: 'login' | 'link' }) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [challengeId, setChallengeId] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const active = useRef(false)

  const requestCode = async () => {
    if (active.current) return
    active.current = true
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/mini-app/api/web-auth/email/start', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), intent, next: '/login' + window.location.search }),
      })
      const result = await response.json() as { ok?: boolean; challenge_id?: string; message?: string }
      if (!response.ok || !result.ok || !result.challenge_id) throw new Error('send')
      setChallengeId(result.challenge_id)
      setMessage(result.message || 'Введите код из письма.')
    } catch {
      setError('Не удалось отправить код. Проверьте почту и попробуйте позже.')
    } finally {
      setBusy(false)
      active.current = false
    }
  }

  const verifyCode = async () => {
    if (active.current) return
    active.current = true
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/mini-app/api/web-auth/email/verify', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ challenge_id: challengeId, code }),
      })
      const result = await response.json() as { ok?: boolean; redirect?: string }
      if (!response.ok || !result.ok || !result.redirect?.startsWith('/') || result.redirect.startsWith('//')) throw new Error('verify')
      window.location.replace(result.redirect)
    } catch {
      setError('Код недействителен или срок его действия истёк. Попробуйте ещё раз.')
    } finally {
      setBusy(false)
      active.current = false
    }
  }

  return <section className="space-y-3 border border-[#9c814c]/40 p-4" aria-label="Вход по почте">
    <p className="font-semibold text-[#efd1a1]">{intent === 'link' ? 'Привязать почту' : 'Войти по почте'}</p>
    {!challengeId ? <form className="space-y-3" onSubmit={event => { event.preventDefault(); void requestCode() }}>
      <label className="block text-sm text-[#c5bead]" htmlFor="web-email">Адрес электронной почты</label>
      <input id="web-email" type="email" required autoComplete="email" value={email}
        onChange={event => setEmail(event.target.value)} disabled={busy} maxLength={254}
        className="min-h-12 w-full border border-[#c49b5a]/50 bg-black/30 px-3 text-white" />
      <button type="submit" disabled={busy || !email.trim()} className="min-h-11 w-full border border-[#e7b154]/70 text-[#f1c77a] disabled:opacity-50">
        {busy ? 'Отправляем…' : 'Получить код'}
      </button>
    </form> : <form className="space-y-3" onSubmit={event => { event.preventDefault(); void verifyCode() }}>
      <p role="status" className="text-xs text-[#c5bead]">{message}</p>
      <label className="block text-sm text-[#c5bead]" htmlFor="web-email-code">Код из письма</label>
      <input id="web-email-code" type="text" required inputMode="numeric" pattern="[0-9]{6}"
        autoComplete="one-time-code" value={code} maxLength={6}
        onChange={event => setCode(event.target.value.replace(/[^0-9]/g, ''))} disabled={busy}
        className="min-h-12 w-full border border-[#c49b5a]/50 bg-black/30 px-3 text-white" />
      <button type="submit" disabled={busy || code.length !== 6}
        className="min-h-11 w-full border border-[#e7b154]/70 text-[#f1c77a] disabled:opacity-50">
        {busy ? 'Проверяем…' : 'Подтвердить код'}
      </button>
      <button type="button" onClick={() => { setChallengeId(''); setCode(''); setMessage('') }}
        className="w-full py-2 text-xs text-[#d4b276] underline">Другой адрес</button>
    </form>}
    {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
  </section>
}

export function LoginPanel() {
  const [webAuthenticated, setWebAuthenticated] = useState(false)
  return (
    <main className="neuromix-login min-h-svh">
      <NoiseTexture className="login-noise" />
      <header className="login-header mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-5 py-5 sm:px-8">
        <a href="/" className="login-brand group flex items-center gap-3 text-[#f4ead6]" aria-label="NEUROMIX — на главную">
          <span className="login-brand-mark" aria-hidden="true">N</span>
          <span className="text-lg font-black tracking-[0.12em] sm:text-xl">NEUROMIX</span>
        </a>
        <Button variant="ghost" asChild className="rounded-none text-[#d6c6aa] hover:bg-white/5 hover:text-white">
          <a href="/"><ArrowLeft aria-hidden="true" className="size-4" /> На главную</a>
        </Button>
      </header>

      <div className="login-stage mx-auto grid w-full max-w-6xl items-center gap-10 px-5 pb-14 pt-6 sm:px-8 lg:grid-cols-[1.06fr_0.94fr] lg:gap-16 lg:py-20">
        <section className="login-illustration relative min-w-0" aria-labelledby="login-page-title">
          <Badge className="login-tape rounded-none border-0 bg-[#e1a847] px-5 py-2 text-xs font-black tracking-[0.13em] text-[#191511] shadow-none hover:bg-[#e1a847]">
            ТВОЯ AI-СТУДИЯ
          </Badge>
          <h1 id="login-page-title" className="login-headline mt-8 text-[#f0e9df]">
            <span>ИДЕИ</span>
            <span className="login-headline-gold">ЖДУТ</span>
            <span>ТЕБЯ.</span>
          </h1>
          <p className="mt-6 max-w-md border-l-2 border-[#dba64d] pl-5 text-base leading-relaxed text-[#c4c5c5]">
            Вернись к фото, видео и своим работам. Один вход — и ты снова в студии NEUROMIX.
          </p>
          <div className="login-artwork" aria-hidden="true" />
        </section>

        <Card className="login-card relative gap-0 overflow-hidden rounded-sm border-[#d4ac61]/50 bg-[#12191b]/95 py-0 text-[#f3ecdd] shadow-[14px_18px_0_rgba(0,0,0,0.32)]">
          <div className="h-1 w-full bg-gradient-to-r from-[#805d2d] via-[#f0bd62] to-[#926b35]" aria-hidden="true" />
          <CardHeader className="gap-3 px-6 pb-5 pt-7 sm:px-9 sm:pt-9">
            <Badge variant="outline" className="w-fit rounded-none border-[#b48a46]/60 px-3 py-1 text-[11px] tracking-[0.12em] text-[#f3be69]">
              <LockKeyhole aria-hidden="true" className="size-3" /> Вход в NEUROMIX
            </Badge>
            <CardTitle className="text-3xl font-black tracking-[-0.045em] text-[#f5eddd] sm:text-4xl">
              Продолжить создавать.
            </CardTitle>
            <CardDescription className="max-w-xs text-sm leading-relaxed text-[#b9b6af]">
              Выберите Яндекс ID или Telegram — система подтвердит ваш аккаунт.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6 px-6 pb-8 sm:px-9 sm:pb-9">
            {(!webAuthenticated || new URLSearchParams(
              typeof window === 'undefined' ? '' : window.location.search,
            ).get('link') === 'telegram')
              ? <TelegramOIDCLogin linkAccount={webAuthenticated} /> : null}
            <BrowserProviderLogin onSessionDetected={setWebAuthenticated} />
            <div className="flex items-start gap-3 border-t border-[#998054]/30 pt-5">
              <ShieldCheck aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-[#e5b25c]" />
              <p className="text-xs leading-relaxed text-[#a8a8a3]">
                Пароли сервисов не передаются NEUROMIX. Яндекс ID и Telegram подтверждают вход у своего провайдера.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
      <footer className="login-footer mx-auto flex max-w-6xl items-center justify-between gap-3 border-t border-[#b08f55]/25 px-5 py-5 text-[11px] text-[#99988e] sm:px-8">
        <span>NEUROMIX · Creative AI Studio</span>
        <a href="/mini-app/" className="inline-flex items-center gap-1 text-[#e2b768] hover:text-[#f7d48f]">
          Открыть студию <ArrowRight aria-hidden="true" className="size-3" />
        </a>
      </footer>
    </main>
  )
}
