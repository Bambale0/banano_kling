'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Wan3PrimeForm, type Wan3DraftState } from '@/components/forms/wan3-prime-form'
import type { Wan3PrimeRecipe } from '@/lib/wan3-prime-api'

export interface Wan3TrendDraft extends Wan3DraftState {
  replacementKeys: string[]
}

// Mirrors source_slots in wan3_prime_repeat.py: frame keys stay named; arrays are zero-based.
function sourceSlots(recipe: Wan3PrimeRecipe) {
  const slots: Array<{ key: string; label: string; url: string }> = []
  if (recipe.first_frame_url) slots.push({ key: 'first_frame_url', label: 'Первый кадр', url: recipe.first_frame_url })
  if (recipe.last_frame_url) slots.push({ key: 'last_frame_url', label: 'Последний кадр', url: recipe.last_frame_url })
  const groups = [
    ['image', 'Image', recipe.reference_image_urls], ['video', 'Video', recipe.reference_video_urls],
    ['audio', 'Audio', recipe.reference_audio_urls], ['file', 'Документ ', recipe.reference_file_urls],
  ] as const
  for (const [kind, label, urls] of groups) {
    urls?.forEach((url, index) => {
      if (url) slots.push({ key: `${kind}:${index}`, url, label: `${label}${index + 1}${kind === 'video' && index === 0 && recipe.scenario === 'edit' ? ' · исходное видео' : ''}` })
    })
  }
  return slots
}

export function Wan3TrendDraftEditor({ model, disabled, onChange }: {
  model: Wan3PrimeRecipe['model']; disabled?: boolean; onChange: (draft: Wan3TrendDraft) => void
}) {
  const [draft, setDraft] = useState<Wan3DraftState | null>(null)
  // A selection belongs to the exact material at that numbered position. Removing
  // or reordering materials must not make another private material fixed by accident.
  const [fixed, setFixed] = useState<Record<string, string>>({})
  const slots = useMemo(() => draft ? sourceSlots(draft.recipe) : [], [draft])
  useEffect(() => {
    setFixed(old => {
      const retained = Object.fromEntries(slots.filter(slot => old[slot.key] === slot.url).map(slot => [slot.key, slot.url]))
      return Object.keys(retained).length === Object.keys(old).length ? old : retained
    })
  }, [slots])
  const captureDraft = useCallback((value: Wan3DraftState) => setDraft(value), [])
  useEffect(() => {
    if (draft) onChange({ ...draft, replacementKeys: slots.filter(slot => fixed[slot.key] !== slot.url).map(slot => slot.key) })
  }, [draft, fixed, onChange, slots])
  return <div className="space-y-3" aria-label="Рецепт тренда Wan">
    <Wan3PrimeForm model={model} credits={0} draftOnly onDraftChange={captureDraft}
      disabledReason={disabled ? 'Сохраняю тренд…' : undefined} />
    <section className="space-y-2 rounded-xl border border-border/50 p-3" aria-label="Замена материалов Wan">
      <h3 className="text-sm font-semibold">Материалы при повторе</h3>
      <p className="text-xs text-muted-foreground">Заменяемые материалы пользователь загрузит сам. Закреплённые материалы автора сохранятся в скрытом рецепте.</p>
      {slots.length ? slots.map(slot => <label key={`${slot.key}:${slot.url}`} className="block space-y-1 text-xs">
        <span>{slot.label}</span>
        <select aria-label={`При повторе: ${slot.label}`} className="w-full rounded-lg border border-border bg-background p-2"
          disabled={disabled || draft?.busy} value={fixed[slot.key] === slot.url ? 'fixed' : 'replaceable'}
          onChange={event => setFixed(old => { const next = { ...old }; if (event.target.value === 'fixed') next[slot.key] = slot.url; else delete next[slot.key]; return next })}>
          <option value="replaceable">Пользователь загружает свой файл</option>
          <option value="fixed">Материал автора, без замены</option>
        </select>
      </label>) : <p className="text-xs text-muted-foreground">В рецепте пока нет материалов для замены.</p>}
    </section>
    <p className="text-xs text-muted-foreground">Поля шаблона и веб-страницы для ручных трендов Wan пока недоступны. Промпт сохраняется целиком.</p>
  </div>
}
