'use client'

import type { TrendUserField } from '@/lib/types'
import { Input } from '@/components/ui/input'

export function RepeatPersonalizationFields({
  fields,
  values,
  onChange,
}: {
  fields: TrendUserField[]
  values: Record<string, string>
  onChange: (values: Record<string, string>) => void
}) {
  if (!fields.length) return null
  return (
    <fieldset className="space-y-3 rounded-2xl border border-gold/30 bg-gold/10 p-4">
      <legend className="px-1 text-sm font-medium text-foreground">Что заменить в работе</legend>
      <p className="text-xs leading-5 text-muted-foreground">
        Сценарий, камера и скрытый промпт автора сохранятся. Заполните только разрешённые автором детали.
      </p>
      {fields.map((field) => (
        <div key={field.key} className="block space-y-1.5 text-sm text-foreground">
          <span>{field.label}{field.required !== false ? ' *' : ''}</span>
          {field.choices?.length ? (
            <span className="flex flex-wrap gap-2" role="group" aria-label={field.label}>
              {field.choices.map((choice) => (
                <button
                  key={choice}
                  type="button"
                  aria-pressed={values[field.key] === choice}
                  onClick={() => onChange({ ...values, [field.key]: choice })}
                  className={`rounded-full border px-3 py-2 text-xs transition-colors ${
                    values[field.key] === choice
                      ? 'border-gold bg-gold/20 text-gold'
                      : 'border-border/60 bg-background/50 text-muted-foreground'
                  }`}
                >
                  {choice}
                </button>
              ))}
            </span>
          ) : (
            <Input
              aria-label={field.label}
              type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'}
              value={values[field.key] || ''}
              maxLength={field.max_length}
              placeholder={field.placeholder || `Введите: ${field.label.toLowerCase()}`}
              required={field.required !== false}
              onChange={(event) => onChange({ ...values, [field.key]: event.target.value })}
            />
          )}
        </div>
      ))}
    </fieldset>
  )
}

export function repeatValuesComplete(fields: TrendUserField[], values: Record<string, string>) {
  return fields.every((field) => field.required === false || Boolean(values[field.key]?.trim()))
}
