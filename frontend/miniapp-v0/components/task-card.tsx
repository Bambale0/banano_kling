'use client'

import { useApp } from '@/lib/app-context'
import type { Task } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Image, Video, Clock, CheckCircle2, XCircle, Banana, ChevronRight } from 'lucide-react'
import { motion } from 'framer-motion'

interface TaskCardProps {
  task: Task
  index: number
}

export function TaskCard({ task, index }: TaskCardProps) {
  const { selectTask } = useApp()

  const formatTime = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const minutes = Math.floor(diff / 60000)
    const hours = Math.floor(minutes / 60)

    if (minutes < 60) return `${minutes} мин. назад`
    if (hours < 24) return `${hours} ч. назад`
    return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
  }

  const statusConfig = {
    pending: {
      icon: Clock,
      label: 'В обработке',
      className: 'bg-gold/15 text-gold border-gold/30',
    },
    completed: {
      icon: CheckCircle2,
      label: 'Готово',
      className: 'bg-success/15 text-success border-success/30',
    },
    failed: {
      icon: XCircle,
      label: 'Ошибка',
      className: 'bg-destructive/15 text-destructive border-destructive/30',
    },
  }

  const status = statusConfig[task.status]
  const StatusIcon = status.icon
  const TypeIcon = task.type === 'image' ? Image : Video

  return (
    <motion.button
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, duration: 0.3 }}
      onClick={() => selectTask(task)}
      className={cn(
        "w-full group relative flex items-start gap-3 p-4 rounded-2xl",
        "bg-card/50 border border-border/50",
        "transition-all duration-300 ease-out",
        "hover:bg-card hover:border-border hover:shadow-lg hover:shadow-background/50",
        "active:scale-[0.99]",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "text-left"
      )}
    >
      {/* Thumbnail / Type indicator */}
      <div className={cn(
        "relative w-14 h-14 rounded-xl overflow-hidden flex-shrink-0",
        "bg-secondary/80 flex items-center justify-center",
        task.status === 'pending' && "pulse-soft"
      )}>
        {task.result_url && task.status === 'completed' ? (
          <img 
            src={task.result_url} 
            alt="" 
            className="w-full h-full object-cover"
          />
        ) : (
          <TypeIcon className={cn(
            "w-6 h-6",
            task.type === 'image' ? "text-gold/70" : "text-cyan/70"
          )} />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs font-medium text-muted-foreground truncate">
            {task.model_label}
          </span>
          <span className="w-1 h-1 rounded-full bg-border" />
          <span className="text-xs text-muted-foreground">
            {task.aspect_ratio}
          </span>
        </div>

        <p className="text-sm text-foreground line-clamp-2 mb-2">
          {task.prompt_preview}
        </p>

        <div className="flex items-center gap-3">
          {/* Status badge */}
          <span className={cn(
            "inline-flex items-center gap-1 px-2 py-0.5 rounded-full",
            "text-[10px] font-medium border",
            status.className,
            task.status === 'pending' && "animate-pulse"
          )}>
            <StatusIcon className="w-3 h-3" />
            {status.label}
          </span>

          {/* Cost */}
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Banana className="w-3 h-3 text-gold" />
            {task.cost}
          </span>

          {/* Time */}
          <span className="text-xs text-muted-foreground">
            {formatTime(task.created_at)}
          </span>
        </div>
      </div>

      {/* Arrow */}
      <ChevronRight className="w-5 h-5 text-muted-foreground/50 flex-shrink-0 transition-transform group-hover:translate-x-1" />
    </motion.button>
  )
}
