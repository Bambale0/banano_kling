'use client'

import { useEffect, useState, type ReactNode } from 'react'
import { SharedAccountLinkPreview } from '@/components/shared-account-link-preview'
import { SharedWalletPreview } from '@/components/shared-wallet-preview'
import { SharedCommercialPreview } from '@/components/shared-commercial-preview'
import { fetchAccountPreviewAccess } from '@/lib/shared-account-api'

function VkAccountPreview() {
  const [access, setAccess] = useState<{ revision: number; vk_app_id: number | null } | null>(null)
  const [message, setMessage] = useState('Подтверждаем вход…')
  useEffect(() => {
    const controller = new AbortController()
    fetchAccountPreviewAccess(controller.signal).then(setAccess).catch(error => {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : 'Не удалось подтвердить вход.')
    })
    return () => controller.abort()
  }, [])
  if (!access) return <main className="mx-auto min-h-dvh w-full max-w-lg p-6"><p role="status">{message}</p></main>
  return <main className="mx-auto min-h-dvh w-full max-w-lg space-y-4 p-4" aria-label="Проверка аккаунта ВК">
    <h1 className="text-xl font-semibold">Общие аккаунты ТГ и ВК</h1>
    <p className="text-sm text-muted-foreground">Доступ для администраторов. Здесь можно проверить связь аккаунтов и тестовый баланс.</p>
    <SharedAccountLinkPreview vkAppId={access.vk_app_id} />
    <SharedWalletPreview />
    <SharedCommercialPreview />
  </main>
}

export function AccountPlatformEntry({ children }: { children: ReactNode }) {
  const [platform, setPlatform] = useState<'telegram' | 'vk' | 'vk-launch-required' | null>(null)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    setPlatform(params.has('vk_app_id') || params.has('vk_user_id') ? 'vk'
      : process.env.NEXT_PUBLIC_MINIAPP_PLATFORM === 'vk' ? 'vk-launch-required' : 'telegram')
  }, [])
  // Do not mount the Telegram store/bootstrap while deciding a VK launch.
  if (platform === null) return null
  if (platform === 'vk-launch-required') return <main className="mx-auto min-h-dvh w-full max-w-lg p-6"><p role="status">Откройте приложение из ВКонтакте.</p></main>
  return platform === 'vk' ? <VkAccountPreview /> : children
}
