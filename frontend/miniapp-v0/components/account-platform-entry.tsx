'use client'

import { useEffect, useState, type ReactNode } from 'react'
import { SharedAccountLinkPreview } from '@/components/shared-account-link-preview'
import { VkStandaloneDiscovery } from '@/components/vk-standalone-discovery'
import { incomingAccountLink } from '@/lib/account-platform'
import {
  startAccountAppSession,
  stopAccountAppSession,
  type AccountPreviewAccess,
} from '@/lib/shared-account-api'

function VkAccountGate({ children }: { children: ReactNode }) {
  const [access, setAccess] = useState<AccountPreviewAccess | null>(null)
  const [message, setMessage] = useState('Подтверждаем вход…')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let sessionStarted = false
    startAccountAppSession(controller.signal).then(result => {
      if (controller.signal.aborted) return
      sessionStarted = result.telegram_linked
      setAccess(result)
    }).catch(error => {
      if (!controller.signal.aborted) {
        setMessage(error instanceof Error ? error.message : 'Не удалось подтвердить вход.')
      }
    })
    return () => {
      controller.abort()
      if (sessionStarted) void stopAccountAppSession()
    }
  }, [retry])

  if (!access) {
    return <main className="mx-auto min-h-dvh w-full max-w-lg p-6"><p role="status">{message}</p></main>
  }
  if (access.telegram_linked) return children

  // A VK-only visitor already has a working native VK bot. Telegram linking
  // is optional; never spoof Telegram identity or imply shared wallet funds.
  const communityId = access.vk_community_id
  const nativeBotUrl = Number.isSafeInteger(communityId) && Number(communityId) > 0
    ? `https://vk.com/im?sel=-${communityId}`
    : null

  return <main className="mx-auto min-h-dvh w-full max-w-lg space-y-5 p-4" aria-label="Студия ВКонтакте">
    <h1 className="text-xl font-semibold">Создавайте в ВКонтакте</h1>
    <p className="text-sm text-muted-foreground">
      Telegram не обязателен. Фото, видео, пополнение и ваши работы доступны в боте ВКонтакте.
      Общая Mini App с Telegram пока работает после привязки аккаунтов.
    </p>
    <VkStandaloneDiscovery />
    {nativeBotUrl
      ? <a className="block rounded-xl bg-primary px-4 py-3 text-center font-semibold text-primary-foreground"
          href={nativeBotUrl} target="_blank" rel="noopener noreferrer">
          Генерировать в боте ВКонтакте
        </a>
      : <p role="status" className="text-sm text-muted-foreground">
          Диалог с ботом сейчас недоступен по прямой ссылке. Вернитесь в сообщения сообщества ВКонтакте.
        </p>}
    <details className="rounded-xl border border-border p-4" open={Boolean(incomingAccountLink())}>
      <summary className="cursor-pointer font-medium">Связать Telegram (необязательно)</summary>
      <p className="my-3 text-sm text-muted-foreground">
        После привязки откроется общая студия с балансом, историей и генерациями Telegram.
        Средства из прежнего VK-бота автоматически не переносятся.
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
  const [platform, setPlatform] = useState<'telegram' | 'vk' | 'vk-launch-required' | null>(null)
  const [telegramInvitation, setTelegramInvitation] = useState(false)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const vkSigned = params.has('vk_app_id') || params.has('vk_user_id')
    setPlatform(vkSigned ? 'vk'
      : process.env.NEXT_PUBLIC_MINIAPP_PLATFORM === 'vk' ? 'vk-launch-required' : 'telegram')
    if (!vkSigned && process.env.NEXT_PUBLIC_MINIAPP_PLATFORM !== 'vk') {
      setTelegramInvitation(Boolean(incomingAccountLink()))
    }
  }, [])
  // Do not mount the shared application store before VK authentication finishes.
  if (platform === null) return null
  if (platform === 'vk-launch-required') {
    return <main className="mx-auto min-h-dvh w-full max-w-lg p-6"><p role="status">Откройте приложение из ВКонтакте.</p></main>
  }
  if (platform === 'telegram' && telegramInvitation) {
    return <main className="mx-auto min-h-dvh w-full max-w-lg space-y-4 p-4" aria-label="Подтверждение Telegram">
      <h1 className="text-xl font-semibold">Привязка Telegram и ВКонтакте</h1>
      <SharedAccountLinkPreview vkAppId={null} onCommitted={() => setTelegramInvitation(false)} />
    </main>
  }
  return platform === 'vk' ? <VkAccountGate>{children}</VkAccountGate> : children
}
