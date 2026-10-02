'use client'

import { useEffect } from 'react'
import type { CSSProperties } from 'react'
import styles from './duration-select.module.css'
import { cn } from '@/lib/utils'
import { Banana } from 'lucide-react'

interface DurationSelectProps {
  durations: number[]
  value: number
  onChange: (value: number) => void
  costs: Record<string, number>
}

export function DurationSelect({ durations, value, onChange, costs }: DurationSelectProps) {
  const formatCost = (raw: number) => Number(raw.toFixed(2)).toString()
  const validDurations = Array.from(
    new Set(
      durations.filter(
        (duration) => Number.isFinite(duration) && duration > 0
      )
    )
  ).sort((a, b) => a - b)

  const selectedDuration =
    validDurations.length === 0
      ? null
      : validDurations.includes(value)
        ? value
        : validDurations.reduce((closest, duration) =>
            Math.abs(duration - value) < Math.abs(closest - value)
              ? duration
              : closest
          )

  useEffect(() => {
    if (selectedDuration !== null && selectedDuration !== value) {
      onChange(selectedDuration)
    }
  }, [onChange, selectedDuration, value])

  if (selectedDuration === null) {
    return null
  }

  const getPerSecondCost = (duration: number) => {
    const rawCost = costs[duration.toString()]

    if (typeof rawCost !== 'number' || !Number.isFinite(rawCost) || rawCost <= 0) {
      return null
    }

    const perSecondCost = rawCost / duration
    return Number.isFinite(perSecondCost) && perSecondCost > 0 ? perSecondCost : null
  }

  const useSlider = validDurations.length > 5

  if (!useSlider) {
    return (
      <div className="grid min-w-0 grid-cols-3 gap-2 sm:grid-cols-4">
        {validDurations.map((duration) => {
          const isSelected = duration === selectedDuration
          const perSecondCost = getPerSecondCost(duration)

          return (
            <button
              key={duration}
              type="button"
              aria-pressed={isSelected}
              onClick={() => onChange(duration)}
              className={cn(
                'min-w-0 justify-center flex items-center gap-1.5 px-2 py-2 rounded-lg',
                'border transition-all duration-200',
                isSelected
                  ? 'bg-cyan/15 border-cyan/50 text-cyan'
                  : 'bg-secondary/50 border-border/50 text-muted-foreground hover:bg-secondary hover:text-foreground'
              )}
            >
              <span className="shrink-0 text-xs font-medium">{duration}с</span>
              {perSecondCost !== null ? (
                <span
                  className={cn(
                    'min-w-0 flex items-center gap-0.5 text-[10px]',
                    isSelected ? 'text-gold' : 'text-gold/70'
                  )}
                >
                  <Banana className="h-3 w-3 shrink-0" />
                  <span className="truncate">{formatCost(perSecondCost)}/с</span>
                </span>
              ) : null}
            </button>
          )
        })}
      </div>
    )
  }

  const selectedIndex = Math.max(0, validDurations.indexOf(selectedDuration))
  const selectedPerSecondCost = getPerSecondCost(selectedDuration)

  return (
    <div className="min-w-0 space-y-3 rounded-xl border border-border/50 bg-secondary/30 p-3">
      <div className="flex min-w-0 items-end justify-between gap-3">
        <div className="text-lg font-semibold text-foreground">
          {selectedDuration} сек
        </div>
        {selectedPerSecondCost !== null ? (
          <span className="flex shrink-0 items-center gap-1 text-xs text-gold">
            <Banana className="h-3.5 w-3.5" />
            {formatCost(selectedPerSecondCost)}/с
          </span>
        ) : null}
      </div>

      <input
        type="range"
        min={0}
        max={validDurations.length - 1}
        step={1}
        value={selectedIndex}
        aria-label="Длительность видео"
        aria-valuetext={`${selectedDuration} секунд`}
        onChange={(event) => {
          const index = Number(event.target.value)
          const nextDuration = validDurations[index]

          if (typeof nextDuration === 'number') {
            onChange(nextDuration)
          }
        }}
        style={
          {
            '--duration-progress': `${(selectedIndex / (validDurations.length - 1)) * 100}%`,
          } as CSSProperties
        }
        className={styles.range}
      />

      <div className="flex min-w-0 justify-between text-[11px] text-muted-foreground">
        <span>{validDurations[0]} сек</span>
        <span>{validDurations[validDurations.length - 1]} сек</span>
      </div>
    </div>
  )
}
