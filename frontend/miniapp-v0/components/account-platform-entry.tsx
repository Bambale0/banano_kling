'use client'

import { useEffect, useState, type ReactNode } from 'react'
import { SharedAccountLinkPreview } from '@/components/shared-account-link-preview'
import { AccountReferencePreview } from '@/components/account-reference-preview'
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

  return <main className="mx-auto min-h-dvh w-full max-w-lg space-y-4 p-4" aria-label="Связывание аккаунта ВК">
    <h1 className="text-xl font-semibold">Свяжите аккаунты ТГ и ВК</h1>
    <p className="text-sm text-muted-foreground">Это нужно один раз, чтобы в обеих апках были общий баланс, история и генерации.</p>
    <SharedAccountLinkPreview
      vkAppId={access.vk_app_id}
      telegramBotUsername={access.telegram_bot_username}
      onCommitted={() => {
        setAccess(null)
        setMessage('Открываем общую студию…')
        setRetry(value => value + 1)
      }}
    />
    <AccountReferencePreview />
  </main>
}

export function AccountPlatformEntry({ children }: { children: ReactNode }) {
  const [platform, setPlatform] = useState<'telegram' | 'vk' | 'vk-launch-required' | null>(null)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    setPlatform(params.has('vk_app_id') || params.has('vk_user_id') ? 'vk'
      : process.env.NEXT_PUBLIC_MINIAPP_PLATFORM === 'vk' ? 'vk-launch-required' : 'telegram')
  }, [])
  // Do not mount the shared application store before VK authentication finishes.
  if (platform === null) return null
  if (platform === 'vk-launch-required') {
    return <main className="mx-auto min-h-dvh w-full max-w-lg p-6"><p role="status">Откройте приложение из ВКонтакте.</p></main>
  }
  return platform === 'vk' ? <VkAccountGate>{children}</VkAccountGate> : children
}
