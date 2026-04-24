'use client'

import { cn } from '@/lib/utils'
import { Banana } from 'lucide-react'

interface DurationSelectProps {
  durations: number[]
  value: number
  onChange: (value: number) => void
  costs: Record<string, number>
}

export function DurationSelect({ durations, value, onChange, costs }: DurationSelectProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {durations.map((duration) => {
        const isSelected = duration === value
        const cost = costs[duration.toString()] || 0
        
        return (
          <button
            key={duration}
            onClick={() => onChange(duration)}
            className={cn(
              "flex items-center gap-2 px-3 py-2 rounded-lg",
              "border transition-all duration-200",
              isSelected 
                ? "bg-cyan/15 border-cyan/50 text-cyan" 
                : "bg-secondary/50 border-border/50 text-muted-foreground hover:bg-secondary hover:text-foreground"
            )}
          >
            <span className="text-xs font-medium">{duration}с</span>
            <span className={cn(
              "flex items-center gap-0.5 text-[10px]",
              isSelected ? "text-gold" : "text-gold/70"
            )}>
              <Banana className="w-3 h-3" />
              {cost}
            </span>
          </button>
        )
      })}
    </div>
  )
}
