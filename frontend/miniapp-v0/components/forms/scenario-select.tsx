'use client'

import type { ScenarioType } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Type, ImageIcon, Video } from 'lucide-react'

interface ScenarioSelectProps {
  scenarios: ScenarioType[]
  value: ScenarioType
  onChange: (value: ScenarioType) => void
}

const scenarioConfig: Record<ScenarioType, {
  label: string
  icon: typeof Type
  description: string
}> = {
  'text': {
    label: 'Текст → Видео',
    icon: Type,
    description: 'Генерация из текста',
  },
  'imgtxt': {
    label: 'Фото + Текст',
    icon: ImageIcon,
    description: 'Анимация изображения',
  },
  'video': {
    label: 'Видео + Текст',
    icon: Video,
    description: 'Стилизация видео',
  },
}

export function ScenarioSelect({ scenarios, value, onChange }: ScenarioSelectProps) {
  const allScenarios: ScenarioType[] = ['text', 'imgtxt', 'video']

  return (
    <div className="flex gap-2">
      {allScenarios.map((scenario) => {
        const config = scenarioConfig[scenario]
        const Icon = config.icon
        const isSelected = scenario === value
        const isAvailable = scenarios.includes(scenario)
        
        return (
          <button
            key={scenario}
            onClick={() => isAvailable && onChange(scenario)}
            disabled={!isAvailable}
            className={cn(
              "flex-1 flex flex-col items-center gap-1.5 p-3 rounded-xl",
              "border transition-all duration-200",
              isSelected 
                ? "bg-cyan/15 border-cyan/50 text-cyan" 
                : isAvailable
                  ? "bg-secondary/50 border-border/50 text-muted-foreground hover:bg-secondary hover:text-foreground"
                  : "bg-secondary/20 border-border/30 text-muted-foreground/40 cursor-not-allowed"
            )}
          >
            <Icon className="w-4 h-4" />
            <span className="text-[10px] font-medium text-center leading-tight">
              {config.label}
            </span>
          </button>
        )
      })}
    </div>
  )
}
