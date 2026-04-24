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
      label: 'Photo Canvas',
      description: 'Nano Banana, Seedream, GPT Image',
      icon: Image,
      onClick: onPhotoClick,
    },
    {
      label: 'Video Canvas',
      description: 'Kling, Veo, Grok video flows',
      icon: Video,
      onClick: onVideoClick,
    },
    {
      label: 'Motion Control',
      description: 'Перенос движения по видео',
      icon: Sparkles,
      onClick: onMotionClick || onVideoClick,
    },
    {
      label: 'AI Assistant',
      description: 'Помощь с промптами и моделями',
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
            <div className="absolute -right-8 -top-8 h-20 w-20 rounded-full bg-white/10 blur-2xl transition-opacity group-hover:opacity-100 opacity-40" />
            <div className="relative">
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-2xl bg-background/55 border border-white/10">
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
