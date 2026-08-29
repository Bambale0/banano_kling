'use client'

import { Headphones, Image, Sparkles, UserRound, Video } from 'lucide-react'
import { motion, useReducedMotion } from 'framer-motion'
import type { TaskType } from '@/lib/types'

interface GenerationPendingVisualProps {
  type: TaskType
}

export function GenerationPendingVisual({ type }: GenerationPendingVisualProps) {
  const reduceMotion = useReducedMotion()
  const TypeIcon = type === 'image'
    ? Image
    : type === 'audio'
      ? Headphones
      : type === 'character'
        ? UserRound
        : Video

  return (
    <div
      className="relative flex h-full w-full flex-col items-center justify-center overflow-hidden bg-secondary/70 px-3"
      role="status"
      aria-label="Генерация выполняется"
    >
      <motion.div
        aria-hidden="true"
        className="absolute h-24 w-24 rounded-full border border-gold/20"
        animate={reduceMotion ? undefined : { rotate: 360 }}
        transition={{ duration: 8, ease: 'linear', repeat: Infinity }}
      >
        <span className="absolute left-1/2 top-[-3px] h-2 w-2 -translate-x-1/2 rounded-full bg-gold" />
      </motion.div>

      <motion.div
        aria-hidden="true"
        className="absolute h-16 w-16 rounded-full border border-foreground/10"
        animate={reduceMotion ? undefined : { rotate: -360, scale: [1, 1.08, 1] }}
        transition={{ duration: 5, ease: 'linear', repeat: Infinity }}
      >
        <span className="absolute bottom-[-2px] right-2 h-1.5 w-1.5 rounded-full bg-foreground/60" />
      </motion.div>

      <motion.div
        className="relative z-10 grid h-11 w-11 place-items-center rounded-2xl border border-gold/25 bg-background/80 text-gold backdrop-blur"
        animate={reduceMotion ? undefined : { scale: [1, 1.06, 1], y: [0, -2, 0] }}
        transition={{ duration: 2.1, ease: 'easeInOut', repeat: Infinity }}
      >
        <TypeIcon className="h-5 w-5" />
        <motion.span
          aria-hidden="true"
          className="absolute -right-1 -top-1"
          animate={reduceMotion ? undefined : { rotate: [0, 18, -12, 0], scale: [0.9, 1.15, 0.9] }}
          transition={{ duration: 1.8, repeat: Infinity }}
        >
          <Sparkles className="h-3.5 w-3.5" />
        </motion.span>
      </motion.div>

      <div className="relative z-10 mt-5 w-full max-w-28 overflow-hidden rounded-full bg-background/55 p-0.5">
        <motion.div
          aria-hidden="true"
          className="h-1.5 w-2/5 rounded-full bg-gold"
          animate={reduceMotion ? undefined : { x: ['-110%', '250%'] }}
          transition={{ duration: 1.5, ease: 'easeInOut', repeat: Infinity }}
        />
      </div>
      <span className="relative z-10 mt-2 text-[10px] font-medium text-muted-foreground">
        Создаём результат…
      </span>
    </div>
  )
}
