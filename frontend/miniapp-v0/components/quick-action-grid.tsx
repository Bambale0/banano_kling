'use client'

import { cn } from '@/lib/utils'
import { Image, Video, Wallet, Bot } from 'lucide-react'

interface QuickActionGridProps {
  onPhotoClick: () => void
  onVideoClick: () => void
  onBalanceClick: () => void
  onAssistantClick: () => void
}

const actions = [
  {
    id: 'photo',
    icon: Image,
    title: 'Создать фото',
    description: 'AI-генерация изображений',
    gradient: 'from-gold/20 to-gold/5',
    iconColor: 'text-gold',
    action: 'photo',
  },
  {
    id: 'video',
    icon: Video,
    title: 'Создать видео',
    description: 'AI-генерация видео',
    gradient: 'from-cyan/20 to-cyan/5',
    iconColor: 'text-cyan',
    action: 'video',
  },
  {
    id: 'balance',
    icon: Wallet,
    title: 'Баланс и пакеты',
    description: 'Управление бананами',
    gradient: 'from-success/20 to-success/5',
    iconColor: 'text-success',
    action: 'balance',
  },
  {
    id: 'assistant',
    icon: Bot,
    title: 'AI-помощник',
    description: 'Советы и подсказки',
    gradient: 'from-accent/20 to-accent/5',
    iconColor: 'text-accent',
    action: 'assistant',
  },
]

export function QuickActionGrid({
  onPhotoClick,
  onVideoClick,
  onBalanceClick,
  onAssistantClick,
}: QuickActionGridProps) {
  const handleClick = (actionId: string) => {
    if (actionId === 'photo') onPhotoClick()
    else if (actionId === 'video') onVideoClick()
    else if (actionId === 'balance') onBalanceClick()
    else if (actionId === 'assistant') onAssistantClick()
  }

  return (
    <div className="grid grid-cols-2 gap-3">
      {actions.map((action, index) => {
        const Icon = action.icon
        return (
          <button
            key={action.id}
            onClick={() => handleClick(action.id)}
            className={cn(
              "group relative flex flex-col items-start p-4 rounded-2xl",
              "bg-card/50 border border-border/50",
              "transition-all duration-300 ease-out",
              "hover:bg-card hover:border-border hover:scale-[1.02]",
              "active:scale-[0.98]",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            )}
            style={{
              animationDelay: `${index * 50}ms`,
            }}
          >
            {/* Gradient overlay */}
            <div className={cn(
              "absolute inset-0 rounded-2xl opacity-0",
              "bg-gradient-to-br",
              action.gradient,
              "transition-opacity duration-300",
              "group-hover:opacity-100"
            )} />

            {/* Content */}
            <div className="relative z-10">
              <div className={cn(
                "w-10 h-10 rounded-xl flex items-center justify-center mb-3",
                "bg-secondary/80 transition-all duration-300",
                "group-hover:bg-secondary"
              )}>
                <Icon className={cn("w-5 h-5 transition-colors", action.iconColor)} />
              </div>
              <h3 className="text-sm font-semibold text-foreground mb-0.5 text-left">
                {action.title}
              </h3>
              <p className="text-xs text-muted-foreground text-left">
                {action.description}
              </p>
            </div>
          </button>
        )
      })}
    </div>
  )
}
