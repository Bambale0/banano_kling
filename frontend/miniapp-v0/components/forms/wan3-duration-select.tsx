'use client'

import { useEffect, useId, useRef, type CSSProperties } from 'react'
import styles from './duration-select.module.css'

interface Wan3DurationSelectProps {
  value: number
  disabled?: boolean
  onChange: (value: number) => void
}

export function Wan3DurationSelect({ value, disabled, onChange }: Wan3DurationSelectProps) {
  const id = useId()
  const automatic = value === -1
  const lastManual = useRef(automatic ? 5 : value)
  useEffect(() => {
    if (value !== -1) lastManual.current = value
  }, [value])
  const seconds = automatic ? lastManual.current : value

  return <div className="col-span-2 min-w-0 space-y-1 text-xs">
    <div className="flex items-center justify-between gap-3">
      <label htmlFor={id}>Длительность</label>
      <output htmlFor={id} className="text-sm font-semibold tabular-nums">{automatic ? 'Auto' : `${seconds} сек`}</output>
    </div>
    <label className="flex min-h-10 w-fit items-center gap-2">
      <input type="checkbox" role="switch" aria-label="Auto: длительность Wan" checked={automatic} disabled={disabled}
        onChange={event => onChange(event.target.checked ? -1 : lastManual.current)} />
      Auto — выбирает модель
    </label>
    <input id={id} type="range" aria-label="Длительность Wan" aria-valuetext={`${seconds} секунд`}
      min={2} max={30} step={1} value={seconds} disabled={disabled || automatic}
      onChange={event => {
        const next = Number(event.target.value)
        if (Number.isInteger(next) && next >= 2 && next <= 30) onChange(next)
      }}
      style={{ '--duration-progress': `${((seconds - 2) / 28) * 100}%` } as CSSProperties}
      className={`${styles.range} disabled:cursor-not-allowed disabled:opacity-40`} />
    <div className="flex justify-between text-muted-foreground"><span>2 сек</span><span>30 сек</span></div>
  </div>
}
