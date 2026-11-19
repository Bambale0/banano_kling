'use client'

import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, ExternalLink, LoaderCircle, LockKeyhole, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { NoiseTexture } from '@/components/magicui/noise-texture'

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
  const url = new URL('/mini-app/', window.location.origin)
  const startapp = browserStartParam()
  if (startapp) url.searchParams.set('startapp', startapp)
  url.hash = new URLSearchParams({ tgWebAppData: initData }).toString()
  return url.toString()
}

function LegacyTelegramWidget() {
  const widgetRef = useRef<HTMLDivElement>(null)
  const activeRequest = useRef(false)
  const [botUsername, setBotUsername] = useState('')
  const [state, setState] = useState<LoginState>('loading-config')
  const [message, setMessage] = useState('Получаем настройки безопасного входа…')

  useEffect(() => {
    // Legacy signed Telegram launches must continue to the existing Mini App;
    // never parse, log or persist their credentials on the marketing page.
    const query = new URLSearchParams(window.location.search)
    const hash = new URLSearchParams(window.location.hash.slice(1))
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
        const response = await fetch('/mini-app/api/browser-auth', {
          method: 'POST',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          cache: 'no-store',
          signal: controller.signal,
          body: JSON.stringify({ telegram_auth: user }),
        })
        const data = await response.json() as {
          ok?: boolean
          init_data?: string
        }
        if (!response.ok || !data.ok || typeof data.init_data !== 'string' || !data.init_data) {
          throw new Error('verification-failed')
        }
        if (!cancelled) window.location.replace(studioUrlWithSession(data.init_data))
      } catch {
        if (!cancelled) {
          setState('error')
          setMessage('Не удалось подтвердить вход. Попробуйте ещё раз или войдите из студии.')
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
  }, [botUsername])

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
        <a href="/mini-app/">
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
function TelegramOIDCLogin() {
  const [config, setConfig] = useState<{ clientId: number; nonce: string } | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'verifying' | 'error'>('loading')
  const [message, setMessage] = useState('Готовим быстрый вход через Telegram…')
  const [showLegacy, setShowLegacy] = useState(false)
  const activeRequest = useRef(false)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    const query = new URLSearchParams(window.location.search)
    const hash = new URLSearchParams(window.location.hash.slice(1))
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
            setMessage('Быстрый вход сейчас недоступен. Попробуйте резервный способ.')
          }
        }
        script.onerror = () => {
          if (mounted.current) {
            setState('error')
            setMessage('Не удалось открыть быстрый вход через Telegram.')
          }
        }
        document.head.appendChild(script)
      } catch {
        if (mounted.current && !controller.signal.aborted) {
          setState('error')
          setMessage('Не удалось подготовить Telegram-вход. Повторите попытку.')
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
            const response = await fetch('/mini-app/api/browser-auth', {
              method: 'POST',
              headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
              credentials: 'same-origin',
              cache: 'no-store',
              body: JSON.stringify({ id_token: result.id_token }),
            })
            const data = await response.json() as { ok?: boolean; init_data?: string }
            if (!response.ok || !data.ok || !data.init_data) throw new Error('auth-failed')
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
      <Button
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
      </Button>
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

export function LoginPanel() {
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
              Нажми «Продолжить через Telegram», подтверди вход в приложении — и вернёшься в студию без ввода номера.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6 px-6 pb-8 sm:px-9 sm:pb-9">
            <TelegramOIDCLogin />
            <div className="flex items-center gap-3">
              <Separator className="flex-1 bg-[#6f6554]/50" />
              <span className="shrink-0 text-xs text-[#a19c90]">Другие способы входа</span>
              <Separator className="flex-1 bg-[#6f6554]/50" />
            </div>
            <div className="grid grid-cols-3 gap-2" aria-label="Другие способы входа пока недоступны">
              {['Почта', 'Google', 'Яндекс ID'].map(method => (
                <div key={method} className="flex min-h-18 flex-col items-center justify-center gap-1 border border-white/10 bg-white/[0.025] px-2 text-center">
                  <span className="text-xs font-semibold text-[#ddd7cc]">{method}</span>
                  <span className="text-[11px] text-[#959186]">скоро</span>
                </div>
              ))}
            </div>
            <div className="flex items-start gap-3 border-t border-[#998054]/30 pt-5">
              <ShieldCheck aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-[#e5b25c]" />
              <p className="text-xs leading-relaxed text-[#a8a8a3]">
                Вход подтверждается Telegram. Мы не запрашиваем пароль и не создаём отдельный аккаунт без подтверждения.
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
