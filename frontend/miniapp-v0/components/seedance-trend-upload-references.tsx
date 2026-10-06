'use client'

import { useEffect, useRef, useState } from 'react'
import type { VideoModel } from '@/lib/types'
import { normalizeMiniAppMediaUrl, videoPreviewFrameUrl } from '@/lib/media-url'
import { uploadFile } from '@/lib/api'
import { uploadSeedance25Video } from '@/lib/seedance25-api'
import { Button } from '@/components/ui/button'

export type SeedanceReferenceMode = 'fixed' | 'replaceable' | 'excluded'
type MediaKind = 'image' | 'video' | 'audio'
export interface SeedanceUploadReference {
  url: string
  name: string
  mode: SeedanceReferenceMode
}
export interface SeedanceUploadReferences {
  images: SeedanceUploadReference[]
  videos: SeedanceUploadReference[]
  audios: SeedanceUploadReference[]
  identityImageIndex: number | null
}
export const emptySeedanceUploadReferences = (): SeedanceUploadReferences => ({
  images: [], videos: [], audios: [], identityImageIndex: null,
})

const MEDIA = [
  { kind: 'image', key: 'images', label: 'Фото', token: 'Image', accept: 'image/*,.heic,.heif' },
  { kind: 'video', key: 'videos', label: 'Видео', token: 'Video', accept: 'video/mp4,video/quicktime,video/webm' },
  { kind: 'audio', key: 'audios', label: 'Аудио', token: 'Audio', accept: 'audio/*,.mp3,.wav,.m4a' },
] as const

interface Props {
  value: SeedanceUploadReferences
  onChange: (value: SeedanceUploadReferences) => void
  onUploadingChange: (uploading: boolean) => void
  disabled: boolean
  model?: VideoModel
}

export function SeedanceTrendUploadReferences({ value, onChange, onUploadingChange, disabled, model }: Props) {
  const attemptRef = useRef(0)
  const activeRef = useRef(true)
  const busyRef = useRef(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    activeRef.current = true
    return () => {
      activeRef.current = false
      attemptRef.current += 1
    }
  }, [])

  const limits = { image: model?.max_image_references, video: model?.max_video_references, audio: model?.max_audio_references }

  const upload = async (kind: MediaKind, files: File[]) => {
    if (disabled || busyRef.current || !files.length) return
    const media = MEDIA.find((item) => item.kind === kind)!
    const limit = limits[kind]
    if (typeof limit === 'number' && value[media.key].length + files.length > limit) {
      setError(`${media.label}: максимум ${limit}. Выберите меньше файлов или очистите референсы.`)
      return
    }
    const attempt = ++attemptRef.current
    const currentAttempt = () => activeRef.current && attemptRef.current === attempt
    busyRef.current = true
    setUploading(true)
    onUploadingChange(true)
    setError(null)
    let next = value
    try {
      for (const file of files) {
        if (!currentAttempt()) return
        const uploaded = model?.id === 'seedance_2_5' && kind === 'video'
          ? await uploadSeedance25Video(file)
          : await uploadFile(`${kind}_reference`, file)
        if (!currentAttempt()) return
        const key = kind === 'image' ? 'images' : kind === 'video' ? 'videos' : 'audios'
        const firstIdentity = kind === 'image' && next.identityImageIndex === null
        next = {
          ...next,
          [key]: [...next[key], { url: uploaded.url, name: file.name, mode: firstIdentity ? 'excluded' : 'fixed' }],
          identityImageIndex: firstIdentity ? next.images.length + 1 : next.identityImageIndex,
        }
        onChange(next)
      }
    } catch (cause) {
      if (currentAttempt()) setError(cause instanceof Error ? cause.message : 'Не удалось загрузить референс')
    } finally {
      if (currentAttempt()) {
        busyRef.current = false
        setUploading(false)
        onUploadingChange(false)
      }
    }
  }

  const busy = disabled || uploading
  const count = value.images.length + value.videos.length + value.audios.length
  return (
    <section aria-label="Референсы шаблона" className="min-w-0 space-y-3 rounded-2xl border border-cyan/25 bg-secondary/25 p-3">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Референсы шаблона</h3>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          Необязательно: загрузите свои исходные фото, видео и аудио. Они скрыты от пользователей и не заменяют публичную обложку выше.
        </p>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          Для шаблона достаточно одного фото для замены лица. Другие референсы можно добавить по желанию. Закреплённые файлы применятся автоматически; заменяемые пользователь загрузит сам. «Не использовать» исключает файл из шаблона.
        </p>
      </div>
      {value.images.length > 0 && (
        <label className="block space-y-2 text-xs text-muted-foreground">
          <span>Фото для замены лица</span>
          <select
            value={value.identityImageIndex ?? ''}
            disabled={busy}
            onChange={(event) => {
              const index = Number(event.target.value)
              onChange({ ...value, identityImageIndex: index, images: value.images.map((item, offset) => offset + 1 === index ? { ...item, mode: 'excluded' } : item) })
            }}
            className="h-11 w-full min-w-0 rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground"
          >
            {value.images.map((item, index) => <option key={item.url} value={index + 1}>@Image{index + 1} · {item.name}</option>)}
          </select>
        </label>
      )}
      {MEDIA.map(({ kind, key, label, token, accept }) => (
        <div key={kind} className="min-w-0 space-y-2">
          <label className="block min-w-0 space-y-2">
            <span className="text-xs font-medium text-foreground">{label}-референсы · {value[key].length}{typeof limits[kind] === 'number' ? ` / ${limits[kind]}` : ''}</span>
            <input
              type="file"
              multiple
              accept={accept}
              aria-label={`${label}-референсы тренда`}
              disabled={busy}
              onChange={(event) => {
                const files = Array.from(event.target.files || [])
                event.target.value = ''
                void upload(kind, files)
              }}
              className="block w-full min-w-0 max-w-full rounded-xl border border-border/50 bg-background/55 p-2 text-xs text-foreground file:mr-2 file:rounded-lg file:border-0 file:bg-secondary file:px-2 file:py-2 disabled:opacity-50"
            />
          </label>
          <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
            {value[key].map((item, offset) => {
              const index = offset + 1
              const identity = kind === 'image' && value.identityImageIndex === index
              return (
                <div key={`${index}-${item.url}`} className="min-w-0 space-y-2 overflow-hidden rounded-xl border border-border/50 bg-background/35 p-2">
                  {kind === 'image' ? <img src={normalizeMiniAppMediaUrl(item.url)} alt={`Исходный @${token}${index}`} className="aspect-video w-full rounded-lg object-contain" />
                    : kind === 'video' ? <video src={videoPreviewFrameUrl(item.url)} controls playsInline preload="metadata" aria-label={`Исходный @${token}${index}`} className="aspect-video w-full rounded-lg bg-black object-contain" />
                    : <audio src={normalizeMiniAppMediaUrl(item.url)} controls preload="metadata" aria-label={`Исходный @${token}${index}`} className="w-full min-w-0 max-w-full" />}
                  <p className="break-words text-xs text-foreground"><strong>@{token}{index}</strong> · {item.name}</p>
                  {identity ? <p className="rounded-lg bg-cyan/10 p-2 text-xs text-cyan">Лицо: пользователь загрузит своё фото</p> : (
                    <div className="space-y-1.5">
                    <select
                      aria-label={`Режим @${token}${index}`}
                      value={item.mode}
                      disabled={busy}
                      onChange={(event) => onChange({ ...value, [key]: value[key].map((current, position) => position === offset ? { ...current, mode: event.target.value as SeedanceReferenceMode } : current) })}
                      className="h-11 w-full min-w-0 rounded-lg border border-border/50 bg-secondary/70 px-2 text-xs text-foreground"
                    >
                      <option value="fixed">Скрыт, без замены</option>
                      <option value="replaceable">Пользователь заменяет</option>
                      <option value="excluded">Не использовать</option>
                    </select>
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      {item.mode === 'replaceable' ? 'Исходник скрыт. Пользователь загрузит свой файл.' : item.mode === 'fixed' ? 'Исходник скрыт и применяется автоматически, без замены.' : 'Файл не войдёт в шаблон.'}
                    </p>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}
      {uploading && <p role="status" className="text-xs text-muted-foreground">Загружаю референсы…</p>}
      {error && <p role="alert" className="break-words text-xs text-destructive">{error}</p>}
      {count > 0 && <>
        <p className="text-xs leading-relaxed text-muted-foreground">В скрытом prompt используйте номера исходников: @Image1, @Video1, @Audio1. Не ссылайтесь на исключённые файлы.</p>
        <Button type="button" variant="secondary" size="sm" disabled={busy} onClick={() => { onChange(emptySeedanceUploadReferences()); setError(null) }}>Очистить референсы</Button>
      </>}
    </section>
  )
}
