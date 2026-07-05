'use client'

import { Image, Video, Sparkles, Bot } from 'lucide-react'
import { cn } from '@/lib/utils'

interface QuickActionGridProps {
  onPhotoClick: () => void
  onVideoClick: () => void
  onMotionClick?: () => void
  onBalanceClick: () => void
  onAssistantClick: () => void
}

const actionStyles = [
  'from-gold/[0.18] to-gold/[0.04] border-gold/25',
  'from-cyan/[0.18] to-cyan/[0.04] border-cyan/25',
  'from-purple-500/[0.18] to-gold/[0.04] border-gold/20',
  'from-card/80 to-muted/30 border-border/60',
]

export function QuickActionGrid({
  onPhotoClick,
  onVideoClick,
  onMotionClick,
  onAssistantClick,
}: QuickActionGridProps) {
  const items = [
    {
      label: 'Создать фото',
      description: 'Изображения по описанию или референсам',
      icon: Image,
      onClick: onPhotoClick,
    },
    {
      label: 'Создать видео',
      description: 'Ролики из текста, фото или видео-референса',
      icon: Video,
      onClick: onVideoClick,
    },
    {
      label: 'Оживить фото',
      description: 'Перенести движение на персонажа или объект',
      icon: Sparkles,
      onClick: onMotionClick || onVideoClick,
    },
    {
      label: 'Помощник',
      description: 'Подскажет модель и поможет с запросом',
      icon: Bot,
      onClick: onAssistantClick,
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-3">
      {items.map((item, index) => {
        const Icon = item.icon

        return (
          <button
            key={item.label}
            type="button"
            onClick={item.onClick}
            className={cn(
              'group relative overflow-hidden rounded-3xl border p-4 text-left',
              'bg-gradient-to-br transition-all duration-300',
              'hover:scale-[1.015] active:scale-[0.99]',
              actionStyles[index]
            )}
          >
            <div className="absolute -right-8 -top-8 h-20 w-20 rounded-full bg-white/10 blur-2xl opacity-40 transition-opacity group-hover:opacity-100" />

            <div className="relative">
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-2xl border border-white/10 bg-background/55">
                <Icon className="h-5 w-5 text-gold" />
              </div>

              <p className="font-serif text-base text-foreground">{item.label}</p>

              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {item.description}
              </p>
            </div>
          </button>
        )
      })}
    </div>
  )
}
