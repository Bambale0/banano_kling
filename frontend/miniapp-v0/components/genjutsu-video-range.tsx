'use client'

import { Button } from '@/components/ui/button'
import type { Asset, Capability } from '@/lib/genjutsu-api'

export type VideoRange = { start: string; end: string }
export const videoSeconds = (milliseconds: number) => String(milliseconds / 1000)
export function fullVideoRange(asset?: Asset | null): VideoRange {
  const duration = asset?.duration_ms
  return { start: '0', end: duration && Number.isFinite(duration) && duration > 0 ? videoSeconds(duration) : '' }
}

export function inspectVideoRange(asset: Asset | undefined | null, range: VideoRange, capability?: Capability) {
  const sourceMs = asset?.duration_ms || 0
  const known = Number.isFinite(sourceMs) && sourceMs > 0
  const numbers = range.start.trim() !== '' && range.end.trim() !== ''
    && Number.isFinite(Number(range.start)) && Number.isFinite(Number(range.end))
  const startSeconds = Number(range.start)
  const endSeconds = Number(range.end)
  const rawStartMs = startSeconds * 1000
  const rawEndMs = endSeconds * 1000
  const startMs = Math.round(rawStartMs)
  const endMs = Math.round(rawEndMs)
  const precise = Math.abs(rawStartMs - startMs) < 0.000001 && Math.abs(rawEndMs - endMs) < 0.000001
  const durationMs = endMs - startMs
  const changed = !numbers || startMs !== 0 || endMs !== sourceMs
  let error = ''
  if (!known) error = 'Не удалось определить длительность видео. Загрузите его ещё раз.'
  else if (!numbers || startSeconds < 0 || endSeconds <= startSeconds || endSeconds > sourceMs / 1000) {
    error = 'Укажите начало и конец внутри видео: конец должен быть позже начала.'
  } else if (!precise) error = 'Укажите секунды с точностью не больше трёх знаков после запятой.'
  else if (!capability) error = 'Параметры режима ещё загружаются.'
  else if (durationMs < capability.minimum_video_ms || durationMs > capability.maximum_video_ms) {
    error = `Для этого режима нужен фрагмент от ${videoSeconds(capability.minimum_video_ms)} до ${videoSeconds(capability.maximum_video_ms)} с. Измените начало или конец.`
  }
  return { sourceMs, known, startMs, endMs, durationMs, changed, error }
}

export function GenjutsuVideoRange({ asset, range, capability, disabled, onChange, onApply }: {
  asset: Asset; range: VideoRange; capability?: Capability; disabled: boolean
  onChange: (range: VideoRange) => void; onApply: () => void
}) {
  const state = inspectVideoRange(asset, range, capability)
  const input = 'min-w-0 w-full rounded-2xl border border-white/10 bg-white/[0.035] px-3 py-3 text-[15px] text-foreground'
  return <fieldset className="min-w-0 space-y-3 rounded-[22px] border border-white/[0.06] bg-white/[0.02] p-3" disabled={disabled || !state.known} aria-label="Длительность видео">
    <div><h4 className="text-sm font-semibold">Длительность видео</h4><p className="mt-1 text-xs text-muted-foreground">По умолчанию используется видео целиком. Начало и конец можно изменить вручную.</p></div>
    <p className="text-sm">{state.known ? `Фактическая длительность: ${videoSeconds(state.sourceMs)} с` : 'Длительность видео не определена'}</p>
    <div className="grid min-w-0 grid-cols-2 gap-2">
      <label className="min-w-0 space-y-2 text-xs text-muted-foreground">Начало, сек.<input className={input} type="number" step="0.001" min="0" max={state.sourceMs / 1000} value={range.start} onChange={event => onChange({ ...range, start: event.target.value })} /></label>
      <label className="min-w-0 space-y-2 text-xs text-muted-foreground">Конец, сек.<input className={input} type="number" step="0.001" min="0" max={state.sourceMs / 1000} value={range.end} onChange={event => onChange({ ...range, end: event.target.value })} /></label>
    </div>
    {state.error ? <p role="alert" className="text-sm text-destructive">{state.error}</p>
      : <p className="text-sm">{state.changed ? 'Выбранный фрагмент' : 'К генерации'}: {videoSeconds(state.durationMs)} с</p>}
    {state.changed && <div className="space-y-2">
      <p className="text-xs text-muted-foreground">Примените выбранный фрагмент перед расчётом. Предыдущая стоимость сброшена.</p>
      <Button type="button" variant="outline" className="h-auto min-h-11 w-full whitespace-normal" disabled={Boolean(state.error)} onClick={onApply}>Применить фрагмент</Button>
    </div>}
    <p className="text-xs text-muted-foreground">Точную стоимость и оплачиваемые секунды покажем перед запуском.</p>
  </fieldset>
}
