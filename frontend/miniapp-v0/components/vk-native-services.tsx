'use client'

import { useEffect, useState } from 'react'
import { ServiceGrid } from './service-grid'
import { fetchVkNativeState, fetchVkPublicDiscovery } from '@/lib/shared-account-api'

/** Same service-card UI as TG, but each live action is a signed native VK path. */
export function VkNativeServices({
  onTabChange, communityId, linkedTelegram = false,
}: {
  onTabChange: (tab: number) => void
  communityId?: number | null
  linkedTelegram?: boolean
}) {
  const [photoAvailable, setPhotoAvailable] = useState(false)
  const [videoAvailable, setVideoAvailable] = useState(false)
  const [nativeLoading, setNativeLoading] = useState(true)
  const [showSupport, setShowSupport] = useState(false)
  const [active, setActive] = useState('more')

  useEffect(() => {
    const controller = new AbortController()
    setNativeLoading(true)
    setPhotoAvailable(false)
    setVideoAvailable(false)
    if (linkedTelegram) {
      setNativeLoading(false)
      return () => controller.abort()
    }
    void Promise.all([
      fetchVkNativeState(controller.signal),
      fetchVkPublicDiscovery('trends', controller.signal),
    ]).then(([state, catalog]) => {
      if (controller.signal.aborted) return
      const canWrite = state.registered === true && state.is_blocked === false
      setPhotoAvailable(canWrite && catalog.can_generate_in_app === true)
      setVideoAvailable(canWrite && state.video_generation_enabled === true)
    }).catch(() => {
      // Unavailable authorization/network means we must not expose a paid
      // action or borrow Telegram credits while the signed VK read fails.
      if (!controller.signal.aborted) {
        setPhotoAvailable(false)
        setVideoAvailable(false)
      }
    }).finally(() => {
      if (!controller.signal.aborted) setNativeLoading(false)
    })
    return () => controller.abort()
  }, [linkedTelegram])

  const hasVerifiedCommunity = typeof communityId === 'number'
    && Number.isSafeInteger(communityId) && communityId > 0

  function activate(serviceId: string) {
    setActive(serviceId)
    if (serviceId === 'edit-photo' && photoAvailable) {
      onTabChange(1)
    } else if (serviceId === 'animate' && videoAvailable) {
      onTabChange(2)
    } else if (serviceId === 'partners') {
      onTabChange(7)
    } else if (serviceId === 'more') {
      onTabChange(0)
    } else if (serviceId === 'support') {
      setShowSupport(true)
    }
  }

  const disabled = [
    'pinterest-ai', 'prompt-by-photo', 'avatar',
    ...(photoAvailable ? [] : ['edit-photo']),
    ...(videoAvailable ? [] : ['animate']),
    ...(hasVerifiedCommunity ? [] : ['support']),
  ]

  return <section aria-label="Сервисы NEUROMIX" className="space-y-4">
    {nativeLoading && <p role="status" className="text-xs text-muted-foreground">
      Проверяем доступные сервисы ВКонтакте…
    </p>}
    <ServiceGrid
      activeServiceId={active}
      unavailableServiceIds={disabled}
      badgeOverrides={{ 'edit-photo': 'Создать с VK-баланса', animate: 'Фото в видео · VK' }}
      onServiceClick={activate}
    />
    {showSupport && hasVerifiedCommunity && <div className="space-y-2 rounded-xl border border-border p-4">
      <h3 className="font-semibold">Поддержка ВКонтакте</h3>
      <a href={`https://vk.com/im?sel=-${communityId}`} target="_blank"
        rel="noopener noreferrer" className="block rounded-xl bg-primary p-3 text-center text-sm text-primary-foreground">
        Написать в поддержку сообщества
      </a>
    </div>}
    <p className="px-4 text-xs text-muted-foreground">
      Неподключённые VK-сервисы пока нельзя оплачивать через Mini App.
      Telegram-кошелёк не используется.
    </p>
  </section>
}
