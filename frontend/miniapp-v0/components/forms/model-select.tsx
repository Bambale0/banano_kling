'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Check, ChevronDown, Banana } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

interface Model {
  id: string
  label: string
  description: string
  cost: number
}

interface ModelSelectProps {
  models: Model[]
  value: string
  onChange: (value: string) => void
}

export function ModelSelect({ models, value, onChange }: ModelSelectProps) {
  const [isOpen, setIsOpen] = useState(false)
  const selected = models.find(m => m.id === value)

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          "w-full flex items-center justify-between gap-3 p-4 rounded-xl",
          "bg-secondary/50 border border-border/50",
          "transition-all duration-200",
          "hover:bg-secondary hover:border-border",
          isOpen && "ring-2 ring-gold/30 border-gold/50"
        )}
      >
        <div className="flex-1 text-left">
          <p className="text-sm font-medium text-foreground">{selected?.label}</p>
          <p className="text-xs text-muted-foreground line-clamp-1">{selected?.description}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 text-xs text-gold">
            <Banana className="w-3.5 h-3.5" />
            {selected?.cost}
          </span>
          <ChevronDown className={cn(
            "w-4 h-4 text-muted-foreground transition-transform",
            isOpen && "rotate-180"
          )} />
        </div>
      </button>

      <AnimatePresence>
        {isOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-40"
              onClick={() => setIsOpen(false)}
            />
            <motion.div
              initial={{ opacity: 0, y: -8, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.95 }}
              transition={{ duration: 0.15 }}
              className={cn(
                "absolute z-50 w-full mt-2 py-2 rounded-xl",
                "glass-strong border border-border/50 shadow-xl"
              )}
            >
              {models.map((model) => (
                <button
                  key={model.id}
                  onClick={() => {
                    onChange(model.id)
                    setIsOpen(false)
                  }}
                  className={cn(
                    "w-full flex items-center gap-3 px-4 py-3",
                    "transition-colors",
                    "hover:bg-secondary/50",
                    model.id === value && "bg-gold/10"
                  )}
                >
                  <div className="flex-1 text-left">
                    <p className="text-sm font-medium text-foreground">{model.label}</p>
                    <p className="text-xs text-muted-foreground line-clamp-1">{model.description}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="flex items-center gap-1 text-xs text-gold">
                      <Banana className="w-3.5 h-3.5" />
                      {model.cost}
                    </span>
                    {model.id === value && (
                      <Check className="w-4 h-4 text-gold" />
                    )}
                  </div>
                </button>
              ))}
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}
