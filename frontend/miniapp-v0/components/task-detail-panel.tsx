'use client'

import { useApp } from '@/lib/app-context'
import { cn } from '@/lib/utils'
import { 
  X, Image, Video, Clock, CheckCircle2, XCircle, 
  Banana, ExternalLink, Copy, RefreshCw 
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { Button } from '@/components/ui/button'

export function TaskDetailPanel() {
  const { taskDetail, isTaskDetailOpen, closeTaskDetail } = useApp()

  const handleCopy = async () => {
    if (!taskDetail || typeof navigator === 'undefined') return
    try {
      await navigator.clipboard.writeText(taskDetail.task_id)
    } catch {
      // Ignore clipboard failures in constrained webviews
    }
  }

  return (
    <AnimatePresence>
      {isTaskDetailOpen && taskDetail && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={closeTaskDetail}
            className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50"
          />

          {/* Panel */}
          <motion.div
            initial={{ opacity: 0, y: '100%' }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: '100%' }}
            transition={{ 
              type: 'spring', 
              damping: 30, 
              stiffness: 300,
              mass: 0.8,
            }}
            className={cn(
              "fixed bottom-0 left-0 right-0 z-50",
              "max-h-[85vh] overflow-auto",
              "glass-strong rounded-t-3xl border-t border-border/50",
              "safe-bottom"
            )}
          >
            {/* Handle */}
            <div className="sticky top-0 z-10 flex justify-center pt-3 pb-2 bg-inherit">
              <div className="w-10 h-1 rounded-full bg-border" />
            </div>

            {/* Header */}
            <div className="flex items-center justify-between px-5 pb-4">
              <h2 className="font-serif text-xl font-semibold text-foreground">
                Детали задачи
              </h2>
              <button
                onClick={closeTaskDetail}
                className="w-8 h-8 rounded-full bg-secondary/80 flex items-center justify-center hover:bg-secondary transition-colors"
              >
                <X className="w-4 h-4 text-muted-foreground" />
              </button>
            </div>

            {/* Content */}
            <div className="px-5 pb-6 space-y-5">
              {/* Preview */}
              {taskDetail.result_url && taskDetail.status === 'completed' && taskDetail.type === 'image' && (
                <div className="relative aspect-square rounded-2xl overflow-hidden bg-secondary/50">
                  <img
                    src={taskDetail.result_url}
                    alt="Result"
                    className="w-full h-full object-cover"
                  />
                </div>
              )}

              {taskDetail.result_url && taskDetail.status === 'completed' && taskDetail.type === 'video' && (
                <div className="relative aspect-video rounded-2xl overflow-hidden bg-secondary/50">
                  <video
                    src={taskDetail.result_url}
                    className="w-full h-full object-cover"
                    controls
                    playsInline
                  />
                </div>
              )}

              {/* Pending state */}
              {taskDetail.status === 'pending' && (
                <div className="relative aspect-video rounded-2xl overflow-hidden bg-secondary/50 flex flex-col items-center justify-center">
                  <div className="w-16 h-16 rounded-2xl bg-gold/10 flex items-center justify-center mb-4">
                    <RefreshCw className="w-8 h-8 text-gold animate-spin" />
                  </div>
                  <p className="text-sm font-medium text-foreground mb-1">
                    Генерация в процессе
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Статус обновляется автоматически
                  </p>
                </div>
              )}

              {/* Info grid */}
              <div className="grid grid-cols-2 gap-3">
                <InfoItem 
                  label="Модель" 
                  value={taskDetail.model_label} 
                />
                <InfoItem 
                  label="Тип" 
                  value={taskDetail.type === 'image' ? 'Фото' : 'Видео'}
                  icon={taskDetail.type === 'image' ? Image : Video}
                />
                <InfoItem 
                  label="Формат" 
                  value={taskDetail.aspect_ratio} 
                />
                <InfoItem 
                  label="Статус" 
                  value={
                    taskDetail.status === 'pending' ? 'В обработке' :
                    taskDetail.status === 'completed' ? 'Готово' : 'Ошибка'
                  }
                  icon={
                    taskDetail.status === 'pending' ? Clock :
                    taskDetail.status === 'completed' ? CheckCircle2 : XCircle
                  }
                  statusColor={
                    taskDetail.status === 'pending' ? 'text-gold' :
                    taskDetail.status === 'completed' ? 'text-success' : 'text-destructive'
                  }
                />
                <InfoItem 
                  label="Стоимость" 
                  value={`${taskDetail.cost}`}
                  icon={Banana}
                  statusColor="text-gold"
                />
                <InfoItem
                  label="Референсы"
                  value={`${taskDetail.request_data?.reference_images?.length || 0}`}
                />
                {taskDetail.request_data?.v_reference_videos && (
                  <InfoItem
                    label="Видео-референсы"
                    value={`${taskDetail.request_data.v_reference_videos.length}`}
                  />
                )}
                {taskDetail.duration && (
                  <InfoItem 
                    label="Длительность" 
                    value={`${taskDetail.duration} сек.`} 
                  />
                )}
              </div>

              {/* Task ID */}
              <div className="flex items-center gap-2 p-3 rounded-xl bg-secondary/50">
                <span className="text-xs text-muted-foreground">ID:</span>
                <code className="text-xs text-foreground font-mono flex-1 truncate">
                  {taskDetail.task_id}
                </code>
                <button
                  onClick={handleCopy}
                  className="text-muted-foreground hover:text-foreground transition-colors"
                >
                  <Copy className="w-4 h-4" />
                </button>
              </div>

              {/* Prompt */}
              <div>
                <h3 className="text-sm font-medium text-foreground mb-2">Промпт</h3>
                <p className="text-sm text-muted-foreground leading-relaxed p-3 rounded-xl bg-secondary/50">
                  {taskDetail.prompt}
                </p>
              </div>

              {/* References */}
              {taskDetail.request_data?.reference_images && taskDetail.request_data.reference_images.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-foreground mb-2">
                    Референсы ({taskDetail.request_data.reference_images.length})
                  </h3>
                  <div className="flex gap-2 overflow-x-auto pb-2">
                    {taskDetail.request_data.reference_images.map((url, i) => (
                      <div 
                        key={i}
                        className="w-20 h-20 rounded-xl overflow-hidden flex-shrink-0 bg-secondary/50"
                      >
                        <img src={url} alt="" className="w-full h-full object-cover" />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Actions */}
              {taskDetail.status === 'completed' && taskDetail.result_url && (
                <Button
                  asChild
                  className="w-full bg-gold hover:bg-gold/90 text-primary-foreground"
                  size="lg"
                >
                  <a href={taskDetail.result_url} target="_blank" rel="noreferrer">
                    <ExternalLink className="w-4 h-4 mr-2" />
                    Открыть оригинал
                  </a>
                </Button>
              )}

              {/* Time */}
              <p className="text-center text-xs text-muted-foreground">
                Создано: {new Date(taskDetail.created_at).toLocaleString('ru-RU')}
              </p>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

function InfoItem({ 
  label, 
  value, 
  icon: Icon,
  statusColor,
}: { 
  label: string
  value: string
  icon?: React.ComponentType<{ className?: string }>
  statusColor?: string
}) {
  return (
    <div className="p-3 rounded-xl bg-secondary/50">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <div className="flex items-center gap-1.5">
        {Icon && <Icon className={cn("w-4 h-4", statusColor || "text-foreground")} />}
        <span className={cn("text-sm font-medium", statusColor || "text-foreground")}>
          {value}
        </span>
      </div>
    </div>
  )
}
