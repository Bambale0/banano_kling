'use client'

import { useMemo, useState } from 'react'
import { useApp } from '@/lib/app-context'
import { ServiceGrid } from '../service-grid'
import { InfoBlock } from '../info-block'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { ArrowRight, HeadphonesIcon, Layers, MoreHorizontal, Pencil, Play, Users, Wand2 } from 'lucide-react'
import type { WorkspacePanel } from '@/lib/types'

type ServiceConfig = {
  title: string
  description: string
  actionText: string
  icon: typeof Wand2
  workspace?: WorkspacePanel
}

const serviceMap: Record<string, ServiceConfig> = {
  'prompt-by-photo': {
    title: 'Промпт по фото',
    description: 'Помогает собрать сильное описание по референсу.',
    workspace: 'photo-prompt',
    actionText: 'Откроется окно, где можно загрузить референс и собрать описание для генерации.',
    icon: Wand2,
  },
  'edit-photo': {
    title: 'Изменить фото',
    description: 'Переводит к редактированию с референсами и исходным изображением.',
    actionText: 'Откроется вкладка Фото с настройками для редактирования и замены деталей.',
    icon: Pencil,
  },
  'animate': {
    title: 'Оживить',
    description: 'Помогает превратить кадр в короткое видео.',
    actionText: 'Откроется вкладка Видео с режимом запуска по стартовому кадру.',
    icon: Play,
  },
  'batch-edit': {
    title: 'Batch Edit',
    description: 'Подходит для серии изображений с одинаковой задачей.',
    workspace: 'batch-edit',
    actionText: 'Откроется окно для подготовки серии и выбора общего сценария обработки.',
    icon: Layers,
  },
  support: {
    title: 'Поддержка',
    description: 'Подскажет, что проверить перед обращением и как быстро описать проблему.',
    workspace: 'support',
    actionText: 'Откроется окно с подсказками и готовым текстом для обращения.',
    icon: HeadphonesIcon,
  },
  partners: {
    title: 'Партнёрам',
    description: 'Показывает выгоду, условия и быстрый старт.',
    workspace: 'partners',
    actionText: 'Откроется партнёрский раздел с условиями и полезными материалами.',
    icon: Users,
  },
  more: {
    title: 'Ещё',
    description: 'Открывает дополнительные разделы и быстрые переходы.',
    workspace: 'more',
    actionText: 'Откроется подборка дополнительных действий.',
    icon: MoreHorizontal,
  },
} as const

export function ServicesTab() {
  const { setActiveTab, openWorkspace } = useApp()
  const [activeService, setActiveService] = useState<keyof typeof serviceMap>('prompt-by-photo')

  const current = useMemo(() => serviceMap[activeService], [activeService])
  const CurrentIcon = current.icon

  const runService = (serviceId: string) => {
    const key = (serviceId in serviceMap ? serviceId : 'prompt-by-photo') as keyof typeof serviceMap
    setActiveService(key)
    const config = serviceMap[key]

    if (key === 'edit-photo' || key === 'prompt-by-photo') {
      if (config.workspace) openWorkspace(config.workspace)
      else setActiveTab(1)
    }
    if (key === 'animate') {
      setActiveTab(2)
    }
    if (key === 'batch-edit' || key === 'support' || key === 'partners' || key === 'more') {
      if (config.workspace) openWorkspace(config.workspace)
    }
    toast.success(config.title, { description: config.actionText })
  }

  return (
    <div className="px-4 space-y-5">
      <div className="mb-5 text-center">
        <h2 className="font-serif text-xl font-semibold text-foreground mb-1">
          Сервисы
        </h2>
        <p className="text-sm text-muted-foreground">
          Дополнительные инструменты и функции
        </p>
      </div>

      <ServiceGrid activeServiceId={activeService} onServiceClick={runService} />

      <div className="glass rounded-2xl border border-border/50 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-gold/80 mb-2">Выбрано</p>
            <h3 className="font-serif text-xl text-foreground">{current.title}</h3>
            <p className="mt-2 text-sm text-muted-foreground max-w-xl">{current.description}</p>
          </div>
          <div className="rounded-2xl border border-gold/20 bg-gold/10 p-3">
            <CurrentIcon className="h-5 w-5 text-gold" />
          </div>
        </div>

        <div className="mt-4 rounded-2xl border border-border/50 bg-secondary/30 p-4">
          <p className="text-xs text-muted-foreground">Что произойдёт</p>
          <p className="mt-2 text-sm text-foreground">
            {current.actionText}
          </p>
        </div>

        <div className="mt-4 flex gap-3">
          <Button
            onClick={() => runService(activeService)}
            className="flex-1 bg-gold hover:bg-gold/90 text-primary-foreground"
          >
            Запустить сервис
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              if (activeService === 'animate') setActiveTab(2)
              else if (activeService === 'edit-photo') setActiveTab(1)
              else if (activeService === 'prompt-by-photo') openWorkspace('photo-prompt')
              else if (activeService === 'batch-edit') openWorkspace('batch-edit')
              else if (activeService === 'support') openWorkspace('support')
              else if (activeService === 'partners') openWorkspace('partners')
              else if (activeService === 'more') openWorkspace('more')
            }}
            disabled={false}
            className={cn("border-border/50 bg-secondary/20 text-foreground hover:bg-secondary/40")}
          >
            Открыть
          </Button>
        </div>
      </div>
      
      <InfoBlock />
    </div>
  )
}
