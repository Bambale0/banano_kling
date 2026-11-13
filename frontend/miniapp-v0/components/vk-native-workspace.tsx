'use client'

import { useEffect, useState } from 'react'
import { BRAND_NAME } from '@/lib/brand'
import { parseMiniAppStartParam, startParamFromLocation } from '@/lib/start-params'
import { AppTabBar } from './tab-nav'
import { VkNativeServices } from './vk-native-services'
import { VkStandaloneDiscovery, type VkNativeSurface } from './vk-standalone-discovery'

/** Native VK route selection. No Telegram user ID, AppProvider or wallet fallback. */
function tabFromVkLocation(): number {
  if (typeof window === 'undefined') return 0
  const target = parseMiniAppStartParam(
    startParamFromLocation(window.location.search, window.location.hash),
  )
  if (target?.kind === 'feed' || target?.kind === 'remix') return 4
  if (target?.kind === 'prompt' || target?.kind === 'genjutsu_recipe') return 5
  if (target?.kind === 'profile') return 7
  if (target?.kind === 'task') return 7
  return 0
}

const vkSurfaces: Record<number, VkNativeSurface> = {
  0: 'studio', 1: 'photo', 2: 'video', 4: 'feed',
  5: 'trends', 7: 'profile',
}

const titles: Record<number, string> = {
  0: 'Студия', 1: 'Фото', 2: 'Видео',
  4: 'Лента', 5: 'Тренды', 6: 'Сервисы', 7: 'Профиль',
}

/**
 * Temporary signed-native actor transition into the SAME shared tab chrome.
 * The complete common TabContent mounts only after all ten VK domains are
 * verified by the server; a visual tab never unlocks a Telegram API.
 */
export function VkNativeWorkspace({ verifiedVkCommunityId, linkedTelegram = false }: {
  verifiedVkCommunityId?: number | null
  linkedTelegram?: boolean
} = {}) {
  const [activeTab, setActiveTab] = useState(tabFromVkLocation)

  useEffect(() => {
    const navigate = () => {
      const target = parseMiniAppStartParam(
        startParamFromLocation(window.location.search, window.location.hash),
      )
      // Do not reset a user-selected tab on an unrelated history event.
      if (target) setActiveTab(tabFromVkLocation())
    }
    window.addEventListener('hashchange', navigate)
    window.addEventListener('popstate', navigate)
    return () => {
      window.removeEventListener('hashchange', navigate)
      window.removeEventListener('popstate', navigate)
    }
  }, [])

  const selectTab = (nextTab: number) => {
    if (nextTab !== activeTab && typeof window !== 'undefined') {
      const start = startParamFromLocation(window.location.search, window.location.hash)
      const target = parseMiniAppStartParam(start)
      // The signed VK launch query is preserved. Only an already-consumed
      // public navigation fragment is removed; never remove a link invite.
      const hasPublicFragment = /^#(?:prompt|feed|remix|profile|posts|task|genjutsu_recipe)_/.test(
        window.location.hash,
      )
      if (target && hasPublicFragment) {
        window.history.replaceState(
          window.history.state, '', window.location.pathname + window.location.search,
        )
      }
    }
    setActiveTab(nextTab)
  }

  const surface = vkSurfaces[activeTab]

  return <section aria-label="Разделы NEUROMIX ВКонтакте" className="min-w-0 space-y-4 pb-[calc(7rem+env(safe-area-inset-bottom))]">
    <header className="rounded-2xl border border-border/50 bg-card/55 p-3">
      <p className="text-xs font-black tracking-[0.16em] text-gold">{BRAND_NAME}</p>
      <h2 className="mt-2 text-lg font-semibold">{titles[activeTab] || 'Студия'}</h2>
    </header>
    {surface ? (
      <VkStandaloneDiscovery key={activeTab} surface={surface} />
    ) : (
      <VkNativeServices onNavigate={selectTab} verifiedVkCommunityId={verifiedVkCommunityId} linkedTelegram={linkedTelegram} />
    )}
    <AppTabBar activeTab={activeTab} onTabChange={selectTab} isVk />
  </section>
}
