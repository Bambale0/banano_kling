'use client'

import type { TrendUserField } from '@/lib/types'
import { Input } from '@/components/ui/input'
import { useEffect, useRef, useState } from 'react'
import { uploadFile } from '@/lib/api'
import { normalizeMiniAppMediaUrl } from '@/lib/media-url'
import { PersonalReferenceLibrary } from '@/components/personal-reference-library'

function ImageChoices({ field, value, onChange }: {
  field: TrendUserField
  value: string
  onChange: (value: string) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const alive = useRef(true)
  const uploadLock = useRef(false)
  const changeRef = useRef(onChange)
  changeRef.current = onChange
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const custom = value.startsWith('upload:') ? value.slice(7) : ''
  const tile = 'relative aspect-square min-w-0 overflow-hidden rounded-2xl border-2 bg-secondary/40 p-1 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan disabled:opacity-50'
  return <>
    <div className="grid grid-cols-3 gap-2" role="group" aria-label={field.label}>
      {field.image_choices?.map(choice => <button key={choice.id} type="button" aria-label={choice.label}
        aria-pressed={value === choice.id} disabled={busy} onClick={() => onChange(choice.id)}
        className={`${tile} ${value === choice.id ? 'border-cyan ring-1 ring-cyan/40' : 'border-border/60'}`}>
        {/* Catalog photographs must keep their entire outfit/object visible. */}
        <img src={normalizeMiniAppMediaUrl(choice.image_url)} alt={choice.label} loading="lazy"
          className="h-full w-full rounded-xl object-contain" />
      </button>)}
      {field.allow_custom_image ? <button type="button" aria-label={`Загрузить свой вариант: ${field.label}`}
        aria-pressed={Boolean(custom)} disabled={busy} onClick={() => input.current?.click()}
        className={`${tile} flex flex-col items-center justify-center gap-2 ${custom ? 'border-cyan' : 'border-border/60'}`}>
        {custom ? <img src={normalizeMiniAppMediaUrl(custom)} alt="Свой вариант" className="absolute inset-0 h-full w-full object-contain" />
          : <span aria-hidden="true" className="text-3xl text-muted-foreground">↑</span>}
        <span className="absolute inset-x-0 bottom-0 bg-background/90 px-1 py-2 text-center text-xs text-foreground">
          {busy ? 'Загрузка…' : 'Свой вариант'}
        </span>
      </button> : null}
    </div>
    {field.allow_custom_image ? <input ref={input} type="file" accept="image/*" className="sr-only"
      aria-label={`Свой вариант: ${field.label}`} disabled={busy} onChange={async event => {
        const file = event.target.files?.[0]
        event.target.value = ''
        if (!file || uploadLock.current) return
        uploadLock.current = true
        setBusy(true); setError(''); onChange('')
        try {
          const uploaded = await uploadFile('image_reference', file)
          if (alive.current) changeRef.current(`upload:${uploaded.url}`)
        } catch (cause) {
          if (alive.current) setError(cause instanceof Error ? cause.message : 'Не удалось загрузить изображение')
        } finally {
          uploadLock.current = false
          if (alive.current) setBusy(false)
        }
      }} /> : null}
    {field.allow_custom_image ? <PersonalReferenceLibrary kind="image" disabled={busy}
      onSelect={file => changeRef.current(`upload:${file.url}`)} /> : null}
    {error ? <p role="alert" className="text-xs text-destructive">{error}</p> : null}
  </>
}

export function RepeatPersonalizationFields({
  fields,
  values,
  onChange,
}: {
  fields: TrendUserField[]
  values: Record<string, string>
  onChange: (values: Record<string, string>) => void
}) {
  const currentValues = useRef(values)
  currentValues.current = values
  const changeValue = (key: string, value: string) => {
    const next = { ...currentValues.current, [key]: value }
    currentValues.current = next
    onChange(next)
  }
  if (!fields.length) return null
  return (
    <fieldset className="space-y-5">
      <legend className="sr-only">Персонализация</legend>
      {fields.map((field) => (
        <div key={field.key} className="block space-y-1.5 text-sm text-foreground">
          <span>{field.label}{field.required !== false ? ' *' : ''}</span>
          {field.image_choices?.length ? <ImageChoices key={JSON.stringify(field)} field={field}
            value={values[field.key] || ''} onChange={value => changeValue(field.key, value)} /> : field.choices?.length ? (
            <span className="flex flex-wrap gap-2" role="group" aria-label={field.label}>
              {field.choices.map((choice) => (
                <button
                  key={choice}
                  type="button"
                  aria-pressed={values[field.key] === choice}
                  onClick={() => changeValue(field.key, choice)}
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
              onChange={(event) => changeValue(field.key, event.target.value)}
            />
          )}
        </div>
      ))}
    </fieldset>
  )
}

export function repeatValuesComplete(fields: TrendUserField[], values: Record<string, string>) {
  return fields.every((field) => (field.required === false && !field.image_choices?.length) || Boolean(values[field.key]?.trim()))
}
