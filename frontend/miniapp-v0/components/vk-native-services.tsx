'use client'

import { useEffect, useState } from 'react'
import { fetchVkNativeState, fetchVkPublicDiscovery } from '@/lib/shared-account-api'
import { ServiceGrid } from './service-grid'

type NativeServiceId = 'edit-photo' | 'animate' | 'partners' | 'support'

/**
 * Same service cards as Telegram, but only actions backed by the currently
 * signed VK actor can be clicked. Never instantiate Telegram AppProvider.
 */
export function VkNativeServices({
  onNavigate, verifiedVkCommunityId,
}: {
  onNavigate: (tab: number) => void
  verifiedVkCommunityId?: number | null
}) {
  const [active, setActive] = useState('')
  const [enabled, setEnabled] = useState<ReadonlySet<string>>(
    () => new Set(['partners']),
  )
  const [error, setError] = useState('')
  const [showSupport, setShowSupport] = useState(false)
  const communityId = Number.isSafeInteger(verifiedVkCommunityId) && Number(verifiedVkCommunityId) > 0
    ? Number(verifiedVkCommunityId) : null
  const supportUrl = communityId ? `https://vk.com/im?sel=-${communityId}` : null

  useEffect(() => {
    const controller = new AbortController()
    Promise.allSettled([
      fetchVkNativeState(controller.signal),
      fetchVkPublicDiscovery('trends', controller.signal),
    ]).then(([nativeResult, discoveryResult]) => {
      if (controller.signal.aborted) return
      const allowed: string[] = ['partners']
      if (supportUrl) allowed.push('support')
      if (nativeResult.status === 'fulfilled') {
        const native = nativeResult.value
        if (native.registered && !native.is_blocked) {
          if (native.video_generation_enabled === true) allowed.push('animate')
          if (discoveryResult.status === 'fulfilled' && discoveryResult.value.can_generate_in_app) {
            allowed.push('edit-photo')
          }
        }
      } else {
        setError('Доступность сервисов ВКонтакте не подтверждена. Откройте приложение заново.')
      }
      setEnabled(new Set(allowed))
    })
    return () => controller.abort()
  }, [supportUrl])

  function chooseService(serviceId: string) {
    if (!enabled.has(serviceId)) return
    setActive(serviceId)
    setShowSupport(false)
    const routes: Partial<Record<NativeServiceId, number>> = {
      'edit-photo': 1,
      animate: 2,
      partners: 7,
    }
    const destination = routes[serviceId as NativeServiceId]
    if (typeof destination === 'number') {
      onNavigate(destination)
    } else if (serviceId === 'support' && supportUrl) {
      setShowSupport(true)
    }
  }

  return <section aria-label="Сервисы ВКонтакте" className="space-y-3">
    <ServiceGrid activeServiceId={active} onServiceClick={chooseService}
      enabledServiceIds={enabled} />
    {showSupport && supportUrl && (
      <aside role="status" className="rounded-2xl border border-border/60 bg-card p-4 text-sm">
        Поддержка NEUROMIX
        <a className="mt-2 block text-primary underline" href={supportUrl}
          target="_blank" rel="noopener noreferrer">
          Открыть диалог с поддержкой ВКонтакте
        </a>
      </aside>
    )}
    {error && <p role="alert" className="text-sm text-muted-foreground">{error}</p>}
    <p className="px-4 text-xs text-muted-foreground">
      Инструменты, для которых ещё нет безопасного VK-контракта, пока недоступны.
      Все доступные операции работают с вашим VK-аккаунтом без Telegram.
    </p>
  </section>
}
