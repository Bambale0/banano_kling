'use client'

import { useState } from 'react'
import { useApp } from '@/lib/app-context'
import { ServiceGrid } from '../service-grid'
import { TrendRunnerDialog } from '@/components/trend-runner-dialog'
import { fetchPrompts } from '@/lib/api'
import { toast } from 'sonner'
import type { PromptItem, WorkspacePanel } from '@/lib/types'
import { setStorageItem } from '@/hooks/browser-storage'

type ServiceConfig = {
  title: string
  workspace?: WorkspacePanel
  tab?: number
  message: string
}

const PINTEREST_SERVICE_TAGS = new Set(['pinterest', 'pinterest-repeat', 'repeat-pinterest'])

function isPinterestServicePrompt(prompt: PromptItem) {
  const tags = new Set((prompt.tags || []).map((tag) => String(tag || '').trim().toLowerCase()))
  const title = String(prompt.title || '').trim().toLowerCase()
  return title.includes('pinterest') || [...PINTEREST_SERVICE_TAGS].some((tag) => tags.has(tag))
}

const serviceMap: Record<string, ServiceConfig> = {
  'pinterest-ai': {
    title: 'Pinterest AI',
    message: 'Открываю новый сервис: трендовая сцена + ваша внешность.',
  },
  'prompt-by-photo': {
    title: 'Промпт по фото',
    workspace: 'photo-prompt',
    message: 'Загрузите референс, чтобы собрать точный prompt.',
  },
  avatar: {
    title: 'Avatar',
    tab: 2,
    message: 'Открываю Avatar: фото персонажа + аудио.',
  },
  'edit-photo': {
    title: 'Изменить фото',
    tab: 1,
    message: 'Открываю фото-сценарии и работу с исходниками.',
  },
  animate: {
    title: 'Оживить фото',
    tab: 2,
    message: 'Открываю видео-сценарии для анимации.',
  },
  support: {
    title: 'Поддержка',
    workspace: 'support',
    message: 'Открываю помощь и обращение в поддержку.',
  },
  partners: {
    title: 'Партнёрам',
    workspace: 'partners',
    message: 'Открываю партнёрский раздел.',
  },
  more: {
    title: 'Ещё',
    workspace: 'more',
    message: 'Открываю дополнительные разделы.',
  },
}

export function ServicesTab() {
  const { setActiveTab, openWorkspace } = useApp()
  const [activeService, setActiveService] = useState('pinterest-ai')
  const [pinterestTrend, setPinterestTrend] = useState<PromptItem | null>(null)
  const [loadingPinterest, setLoadingPinterest] = useState(false)

  async function openPinterestAi() {
    if (loadingPinterest) return
    setLoadingPinterest(true)
    try {
      const trends = await fetchPrompts({ source: 'tag', tag: 'trend', limit: 80 })
      const trend = trends.find(isPinterestServicePrompt)
      if (!trend) {
        toast.error('Pinterest AI недоступен', {
          description: 'Не найден опубликованный сервисный шаблон Pinterest.',
        })
        return
      }
      setPinterestTrend(trend)
      toast.success('Pinterest AI', {
        description: serviceMap['pinterest-ai'].message,
      })
    } catch (error) {
      toast.error('Не удалось открыть Pinterest AI', {
        description: error instanceof Error ? error.message : 'Повторите попытку позже.',
      })
    } finally {
      setLoadingPinterest(false)
    }
  }

  function runService(serviceId: string) {
    const config = serviceMap[serviceId] || serviceMap['prompt-by-photo']
    setActiveService(serviceId)

    if (serviceId === 'pinterest-ai') {
      void openPinterestAi()
      return
    }

    if (serviceId === 'avatar' && typeof window !== 'undefined') {
      setStorageItem('miniapp_requested_video_model', 'avatar_pro')
      setStorageItem('miniapp_requested_video_scenario', 'avatar')
    }

    if (typeof config.tab === 'number') {
      setActiveTab(config.tab)
    }

    if (config.workspace) {
      openWorkspace(config.workspace)
    }

    toast.success(config.title, { description: config.message })
  }

  return (
    <div className="px-4 space-y-5 pb-28">
      <ServiceGrid activeServiceId={activeService} onServiceClick={runService} />
      <TrendRunnerDialog
        trend={pinterestTrend}
        open={Boolean(pinterestTrend)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setPinterestTrend(null)
        }}
      />
    </div>
  )
}
