'use client'

import { useEffect, useState, type ReactNode } from 'react'
import { SharedAccountLinkPreview } from '@/components/shared-account-link-preview'
import { VkNativeWorkspace } from '@/components/vk-native-workspace'
import { hasVkLaunchData, incomingAccountLink } from '@/lib/account-platform'
import { reportVkLaunchStage } from '@/lib/vk-launch-telemetry'
import { WebAccountWorkspace } from '@/components/web-account-workspace'
import { browserEntryMode, hasExplicitTelegramLaunch } from '@/lib/web-account-entry'
import {
  startAccountAppSession,
  stopAccountAppSession,
  type AccountPreviewAccess,
} from '@/lib/shared-account-api'

/** The VK host handles sign-in and returns fresh signed launch credentials. */
function VkLoginLink() {
  return <a
    className="block rounded-xl bg-primary px-4 py-3 text-center font-semibold text-primary-foreground"
    href="/mini-app/api/account-preview/vk-login"
    target="_top"
    rel="noreferrer"
  >
    Войти через ВКонтакте
  </a>
}

function VkAccountGate({ children }: { children: ReactNode }) {
  const [access, setAccess] = useState<AccountPreviewAccess | null>(null)
  const [message, setMessage] = useState('Подтверждаем вход…')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    reportVkLaunchStage('vk-session-start')
    startAccountAppSession(controller.signal).then(result => {
      if (controller.signal.aborted) return
      reportVkLaunchStage('vk-session-ok')
      setAccess(result)
    }).catch(error => {
      if (!controller.signal.aborted) {
        reportVkLaunchStage('vk-session-failed')
        setMessage(error instanceof Error ? error.message : 'Не удалось подтвердить вход.')
      }
    })
    return () => {
      controller.abort()
      // Invalidate even a pending /session response: its server-side token
      // must not resurrect the previous VK actor after unmount or retry.
      void stopAccountAppSession()
    }
  }, [retry])

  if (!access) {
    return <main className="mx-auto min-h-dvh w-full max-w-lg space-y-5 p-6">
      <p role="status">{message}</p>
      {message !== 'Подтверждаем вход…' && <VkLoginLink />}
    </main>
  }
  // A complete native VK adapter unlocks independent parity. Preserve the
  // separately verified, voluntary linked-TG legacy studio while feature
  // gates remain OFF; never infer either capability from a link alone.
  if (access.full_app_ready === true || access.legacy_linked_studio_available === true) return children

  // A VK-only visitor already has a working native VK bot. Telegram linking
  // is optional; never spoof Telegram identity or imply shared wallet funds.
  const communityId = access.vk_community_id
  const nativeBotUrl = Number.isSafeInteger(communityId) && Number(communityId) > 0
    ? `https://vk.com/im?sel=-${communityId}`
    : null

  return <main className="mx-auto min-h-dvh w-full max-w-[1180px] space-y-5 px-3 py-4 sm:px-4" aria-label="Студия ВКонтакте">
    <h1 className="text-xl font-semibold">Создавайте в ВКонтакте</h1>
    <p className="text-sm text-muted-foreground">
      Telegram не обязателен. Фото, видео, пополнение и ваши работы доступны в боте ВКонтакте.
      Единая Mini App станет доступна после подтверждения полной совместимости сервером.
    </p>
    <VkNativeWorkspace verifiedVkCommunityId={communityId} linkedTelegram={access.telegram_linked} />
    {nativeBotUrl
      ? <a className="block rounded-xl bg-primary px-4 py-3 text-center font-semibold text-primary-foreground"
          href={nativeBotUrl} target="_blank" rel="noopener noreferrer">
          Генерировать в боте ВКонтакте
        </a>
      : <p role="status" className="text-sm text-muted-foreground">
          Диалог с ботом сейчас недоступен по прямой ссылке. Вернитесь в сообщения сообщества ВКонтакте.
        </p>}
    <details className="rounded-xl border border-border p-4 mb-[calc(7rem+env(safe-area-inset-bottom))]" open={Boolean(incomingAccountLink())}>
      <summary className="cursor-pointer font-medium">Связать Telegram (необязательно)</summary>
      <p className="my-3 text-sm text-muted-foreground">
        Привязка аккаунтов добровольная. Средства из прежнего VK-бота автоматически не переносятся.
        Доступ к единой студии включается только после проверки её готовности.
      </p>
      <SharedAccountLinkPreview
        vkAppId={access.vk_app_id}
        telegramBotUsername={access.telegram_bot_username}
        onCommitted={() => {
          setAccess(null)
          setMessage('Открываем общую студию…')
          setRetry(value => value + 1)
        }}
      />
    </details>
  </main>
}

export function AccountPlatformEntry({ children }: { children: ReactNode }) {
  const [platform, setPlatform] = useState<'telegram' | 'vk' | 'vk-launch-required' | 'web' | 'web-error' | null>(null)
  const [telegramInvitation, setTelegramInvitation] = useState(false)
  useEffect(() => {
    const vkSigned = hasVkLaunchData()
    if (vkSigned) {
      reportVkLaunchStage('vk-react-mounted')
      setPlatform('vk')
      return
    }
    if (process.env.NEXT_PUBLIC_MINIAPP_PLATFORM === 'vk') {
      setPlatform('vk-launch-required')
      return
    }
    const invitation = Boolean(incomingAccountLink())
    setTelegramInvitation(invitation)

    // A real Telegram Mini App launch takes precedence over a browser cookie.
    // Cached browser initData is NOT evidence of a native Telegram launch.
    if (invitation || hasExplicitTelegramLaunch()) {
      setPlatform('telegram')
      return
    }
    const controller = new AbortController()
    void (async () => {
      try {
        const response = await fetch('/mini-app/api/web-auth/config', {
          credentials: 'same-origin', cache: 'no-store',
          headers: { Accept: 'application/json' }, signal: controller.signal,
        })
        if (!response.ok) throw new Error('Web authentication unavailable')
        const config = await response.json() as {
          ok?: boolean; authenticated?: boolean; studio_ready?: boolean
        }
        if (controller.signal.aborted) return
        if (config.ok !== true) throw new Error('Invalid web auth config')
        const mode = browserEntryMode(Boolean(config.authenticated), Boolean(config.studio_ready))
        if (mode === 'web') {
          setPlatform('web')
          return
        }
        if (mode === 'linked') {
          // Only a real, *verified* Telegram link may enter the legacy studio.
          const studio = await fetch('/mini-app/api/web-auth/studio', {
            method: 'POST', credentials: 'same-origin', cache: 'no-store',
            headers: { Accept: 'application/json' }, signal: controller.signal,
          })
          const result = await studio.json() as { ok?: boolean; init_data?: string }
          if (!studio.ok || result.ok !== true || !result.init_data) throw new Error('Studio unavailable')
          if (!controller.signal.aborted) {
            const url = new URL('/mini-app/', window.location.origin)
            url.hash = new URLSearchParams({ tgWebAppData: result.init_data }).toString()
            window.location.replace(url.toString())
          }
          return
        }
        setPlatform('telegram')
      } catch {
        if (!controller.signal.aborted) setPlatform('web-error')
      }
    })()
    return () => controller.abort()
  }, [])

  // Do not mount the shared application store before VK authentication finishes.
  // The first HTML response must also be useful when an older VK WebView fails
  // to execute/hydrate the JS bundle. Returning null here produces an indefinite
  // white screen with no way back to VK.
  if (platform === null) {
    if (process.env.NEXT_PUBLIC_MINIAPP_PLATFORM !== 'vk') return null
    return <main className="mx-auto min-h-dvh w-full max-w-lg space-y-5 p-6" aria-label="Загрузка ВКонтакте">
      <h1 className="text-xl font-semibold">Открываем приложение ВКонтакте…</h1>
      <p role="status" className="text-sm text-muted-foreground">
        Если этот экран не меняется, откройте приложение из ВКонтакте ещё раз.
        Telegram для входа не нужен.
      </p>
      <VkLoginLink />
    </main>
  }
  if (platform === 'web') return <WebAccountWorkspace />
  if (platform === 'web-error') {
    return <main className="mx-auto flex min-h-dvh max-w-lg flex-col justify-center gap-4 p-6">
      <h1 className="text-xl font-bold">Не удалось подтвердить веб-сессию</h1>
      <p role="alert" className="text-sm text-muted-foreground">Проверьте соединение и попробуйте ещё раз.</p>
      <a href="/mini-app/" className="underline">Повторить</a>
      <a href="/login" className="underline">Открыть вход</a>
    </main>
  }
  if (platform === 'vk-launch-required') {
    return <main className="mx-auto min-h-dvh w-full max-w-lg space-y-5 p-6" aria-label="Вход через ВКонтакте">
      <h1 className="text-xl font-semibold">Вход в NEUROMIX</h1>
      <p className="text-sm text-muted-foreground">
        Войдите через ВКонтакте, чтобы открыть Mini App. Если вы ещё не авторизованы в ВК,
        он предложит войти в аккаунт. Telegram привязывать не нужно.
      </p>
      <VkLoginLink />
    </main>
  }
  if (platform === 'telegram' && telegramInvitation) {
    return <main className="mx-auto min-h-dvh w-full max-w-lg space-y-4 p-4" aria-label="Подтверждение Telegram">
      <h1 className="text-xl font-semibold">Привязка Telegram и ВКонтакте</h1>
      <SharedAccountLinkPreview vkAppId={null} onCommitted={() => setTelegramInvitation(false)} />
    </main>
  }
  return platform === 'vk' ? <VkAccountGate>{children}</VkAccountGate> : children
}
