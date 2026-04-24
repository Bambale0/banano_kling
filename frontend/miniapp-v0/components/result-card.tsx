'use client'

import type { Task } from '@/lib/types'
import { cn } from '@/lib/utils'
import { CheckCircle2, Clock, X, ExternalLink, Copy, AlertCircle } from 'lucide-react'
import { motion } from 'framer-motion'
import { Button } from '@/components/ui/button'

interface ResultCardProps {
  task: Task
  onClose: () => void
}

export function ResultCard({ task, onClose }: ResultCardProps) {
  const isPending = task.status === 'pending'
  const isCompleted = task.status === 'completed'
  const isFailed = task.status === 'failed'

  const handleCopy = async () => {
    if (typeof navigator === 'undefined') return
    try {
      await navigator.clipboard.writeText(task.task_id)
    } catch {
      // Ignore clipboard failures in constrained webviews.
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 20, scale: 0.95 }}
      className={cn(
        "relative p-5 rounded-2xl",
        "glass border",
        isPending ? "border-gold/30" : isCompleted ? "border-success/30" : "border-destructive/30"
      )}
    >
      {/* Close button */}
      <button
        onClick={onClose}
        className="absolute top-3 right-3 w-8 h-8 rounded-full bg-secondary/80 flex items-center justify-center hover:bg-secondary transition-colors"
      >
        <X className="w-4 h-4 text-muted-foreground" />
      </button>

      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <div className={cn(
          "w-10 h-10 rounded-xl flex items-center justify-center",
          isPending ? "bg-gold/15" : isCompleted ? "bg-success/15" : "bg-destructive/15"
        )}>
          {isPending ? (
            <Clock className="w-5 h-5 text-gold animate-pulse" />
          ) : isFailed ? (
            <AlertCircle className="w-5 h-5 text-destructive" />
          ) : (
            <CheckCircle2 className="w-5 h-5 text-success" />
          )}
        </div>
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            {isPending ? 'Задача принята' : isFailed ? 'Ошибка запуска' : 'Результат готов'}
          </h3>
          <p className="text-xs text-muted-foreground">
            {isPending 
              ? 'Результат придёт в чат и появится в истории'
              : isFailed
                ? 'Проверьте prompt, файлы и попробуйте снова'
              : 'Нажмите чтобы открыть в полном размере'
            }
          </p>
        </div>
      </div>

      {/* Task ID */}
      <div className="flex items-center gap-2 p-3 rounded-xl bg-secondary/50 mb-4">
        <span className="text-xs text-muted-foreground">ID:</span>
        <code className="text-xs text-foreground font-mono flex-1 truncate">
          {task.task_id}
        </code>
        <button
          onClick={handleCopy}
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          <Copy className="w-4 h-4" />
        </button>
      </div>

      {/* Preview if completed */}
      {isCompleted && task.result_url && task.type === 'image' && (
        <div className="relative aspect-square rounded-xl overflow-hidden mb-4">
          <img
            src={task.result_url}
            alt="Generated result"
            className="w-full h-full object-cover"
          />
        </div>
      )}

      {isCompleted && task.result_url && task.type === 'video' && (
        <div className="relative aspect-video rounded-xl overflow-hidden mb-4">
          <video
            src={task.result_url}
            className="w-full h-full object-cover"
            controls
            playsInline
          />
        </div>
      )}

      {/* Pending animation */}
      {isPending && (
        <div className="relative aspect-video rounded-xl overflow-hidden bg-secondary/50 flex flex-col items-center justify-center mb-4">
          <div className="relative w-16 h-16">
            <div className="absolute inset-0 rounded-full border-2 border-gold/20" />
            <div className="absolute inset-0 rounded-full border-2 border-gold border-t-transparent animate-spin" />
          </div>
          <p className="text-xs text-muted-foreground mt-4">
            Статус обновляется автоматически
          </p>
        </div>
      )}

      {/* Action button */}
      {isCompleted && task.result_url && (
        <Button
          asChild
          className="w-full bg-gold hover:bg-gold/90 text-primary-foreground"
        >
          <a href={task.result_url} target="_blank" rel="noreferrer">
            <ExternalLink className="w-4 h-4 mr-2" />
            Открыть оригинал
          </a>
        </Button>
      )}
    </motion.div>
  )
}
