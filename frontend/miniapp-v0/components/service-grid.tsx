'use client'

import { cn } from '@/lib/utils'
import { 
  Wand2, 
  Pencil, 
  Play, 
  Layers, 
  HeadphonesIcon, 
  Users, 
  MoreHorizontal,
  Sparkles 
} from 'lucide-react'
import { motion } from 'framer-motion'
import { Button } from '@/components/ui/button'

const services = [
  {
    id: 'prompt-by-photo',
    icon: Wand2,
    title: 'Промпт по фото',
    description: 'Описание по референсу',
    color: 'gold',
  },
  {
    id: 'edit-photo',
    icon: Pencil,
    title: 'Изменить фото',
    description: 'Правки по исходнику',
    color: 'cyan',
  },
  {
    id: 'animate',
    icon: Play,
    title: 'Оживить',
    description: 'Анимация статичных фото',
    color: 'success',
  },
  {
    id: 'batch-edit',
    icon: Layers,
    title: 'Batch Edit',
    description: 'Серия изображений',
    color: 'accent',
  },
  {
    id: 'support',
    icon: HeadphonesIcon,
    title: 'Поддержка',
    description: 'Помощь и вопросы',
    color: 'muted',
  },
  {
    id: 'partners',
    icon: Users,
    title: 'Партнёрам',
    description: 'Партнёрская программа',
    color: 'muted',
  },
]

const colorClasses: Record<string, { bg: string; icon: string; border: string }> = {
  gold: {
    bg: 'bg-gold/10 group-hover:bg-gold/15',
    icon: 'text-gold',
    border: 'border-gold/20 group-hover:border-gold/40',
  },
  cyan: {
    bg: 'bg-cyan/10 group-hover:bg-cyan/15',
    icon: 'text-cyan',
    border: 'border-cyan/20 group-hover:border-cyan/40',
  },
  success: {
    bg: 'bg-success/10 group-hover:bg-success/15',
    icon: 'text-success',
    border: 'border-success/20 group-hover:border-success/40',
  },
  accent: {
    bg: 'bg-accent/10 group-hover:bg-accent/15',
    icon: 'text-accent',
    border: 'border-accent/20 group-hover:border-accent/40',
  },
  muted: {
    bg: 'bg-secondary/50 group-hover:bg-secondary',
    icon: 'text-muted-foreground',
    border: 'border-border/50 group-hover:border-border',
  },
}

interface ServiceGridProps {
  activeServiceId: string
  onServiceClick: (serviceId: string) => void
}

export function ServiceGrid({ activeServiceId, onServiceClick }: ServiceGridProps) {
  const selected = services.find((service) => service.id === activeServiceId) || services[0]

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {services.map((service, index) => {
          const Icon = service.icon
          const colors = colorClasses[service.color]
          
          return (
            <motion.button
              key={service.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.05 }}
              onClick={() => onServiceClick(service.id)}
              className={cn(
                "group relative flex flex-col items-start p-4 rounded-2xl",
                "bg-card/50 border",
                colors.border,
                "transition-all duration-300 ease-out",
                "hover:scale-[1.02] active:scale-[0.98]",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                selected.id === service.id && "ring-2 ring-gold/30"
              )}
            >
              <div className={cn(
                "w-10 h-10 rounded-xl flex items-center justify-center mb-3",
                colors.bg,
                "transition-colors duration-300"
              )}>
                <Icon className={cn("w-5 h-5", colors.icon)} />
              </div>
              <h3 className="text-sm font-semibold text-foreground mb-0.5 text-left">
                {service.title}
              </h3>
              <p className="text-xs text-muted-foreground text-left">
                {service.description}
              </p>
            </motion.button>
          )
        })}
        
        <motion.button
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: services.length * 0.05 }}
          onClick={() => onServiceClick('more')}
          className={cn(
            "group flex flex-col items-start p-4 rounded-2xl",
            "bg-secondary/30 border border-border/30",
            "transition-all duration-300 ease-out",
            "hover:bg-secondary/50 hover:border-border/50",
            "active:scale-[0.98]"
          )}
        >
          <div className="w-10 h-10 rounded-xl bg-secondary/50 flex items-center justify-center mb-3">
            <MoreHorizontal className="w-5 h-5 text-muted-foreground" />
          </div>
          <h3 className="text-sm font-semibold text-foreground mb-0.5 text-left">
            Ещё
          </h3>
          <p className="text-xs text-muted-foreground text-left">
            Дополнительные разделы
          </p>
        </motion.button>
      </div>

      <div className="glass rounded-2xl border border-border/50 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-cyan/80 mb-2">Подборка</p>
            <h3 className="font-serif text-lg text-foreground mb-1">{selected.title}</h3>
            <p className="text-sm text-muted-foreground max-w-xl">
              {selected.description}
            </p>
          </div>
          <div className="w-10 h-10 rounded-xl bg-gold/10 border border-gold/20 flex items-center justify-center">
            <Sparkles className="w-5 h-5 text-gold" />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {services.slice(0, 4).map((service) => (
            <span
              key={service.id}
              className="rounded-full border border-border/50 bg-secondary/50 px-3 py-1 text-xs text-secondary-foreground"
            >
              {service.title}
            </span>
          ))}
        </div>

        <Button onClick={() => onServiceClick(selected.id)} className="mt-4 w-full bg-gold hover:bg-gold/90 text-primary-foreground">
          Открыть
        </Button>
      </div>
    </div>
  )
}
