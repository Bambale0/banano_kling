'use client'

import { useState } from 'react'
import { useApp } from '@/lib/app-context'
import { ServiceGrid } from '../service-grid'
import { toast } from 'sonner'
import type { WorkspacePanel } from '@/lib/types'

type ServiceConfig = {
  title: string
  workspace?: WorkspacePanel
  tab?: number
  message: string
}

const serviceMap: Record<string, ServiceConfig> = {
  'prompt-by-photo': {
    title: 'Промпт по фото',
    workspace: 'photo-prompt',
    message: 'Загрузите референс, чтобы собрать точный prompt.',
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
  'batch-edit': {
    title: 'Batch Edit',
    workspace: 'batch-edit',
    message: 'Открываю подготовку серии изображений.',
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
  const [activeService, setActiveService] = useState('prompt-by-photo')

  function runService(serviceId: string) {
    const config = serviceMap[serviceId] || serviceMap['prompt-by-photo']
    setActiveService(serviceId)

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
    </div>
  )
}
