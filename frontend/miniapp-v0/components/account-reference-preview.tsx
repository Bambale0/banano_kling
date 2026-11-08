'use client'

import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  fetchAccountReferencePhotos, removeAccountReferencePhoto, saveAccountReferencePhoto,
  type AccountReferencePhoto,
} from '@/lib/shared-account-api'

type Photo = AccountReferencePhoto & { url: string | null }

export function AccountReferencePreview() {
  const inputId = useId()
  const [open, setOpen] = useState(false)
  const [photos, setPhotos] = useState<Photo[]>([])
  const [nextOffset, setNextOffset] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const mounted = useRef(true)
  const opened = useRef(false)
  const locked = useRef(false)
  const sequence = useRef(0)
  const current = useRef<Photo[]>([])
  const urls = useRef(new Set<string>())
  const loader = useRef<AbortController | null>(null)
  const mutation = useRef<AbortController | null>(null)

  const release = useCallback(() => {
    for (const url of urls.current) URL.revokeObjectURL(url)
    urls.current.clear()
    current.current = []
  }, [])

  const load = useCallback(async (offset = 0) => {
    loader.current?.abort()
    const controller = new AbortController()
    loader.current = controller
    const version = ++sequence.current
    if (offset === 0) {
      setLoaded(false)
      release()
      setPhotos([])
      setNextOffset(null)
    }
    setLoading(true)
    try {
      const page = await fetchAccountReferencePhotos(offset, controller.signal)
      if (!mounted.current || !opened.current || controller.signal.aborted || version !== sequence.current) return
      const result = offset ? [...current.current] : []
      const seen = new Set(result.map(photo => photo.id))
      for (const photo of page.references) {
        if (seen.has(photo.id)) continue
        const url = photo.thumbnail ? URL.createObjectURL(photo.thumbnail) : null
        if (url) urls.current.add(url)
        const { thumbnail: _thumbnail, ...metadata } = photo
        result.push({ ...metadata, url })
        seen.add(photo.id)
      }
      current.current = result
      setPhotos(result)
      setNextOffset(page.next_offset)
      setLoaded(true)
      setError('')
    } catch (failure) {
      if (!mounted.current || !opened.current || controller.signal.aborted || version !== sequence.current) return
      release()
      setPhotos([])
      setNextOffset(null)
      setLoaded(false)
      setError(failure instanceof Error ? failure.message : 'Не удалось загрузить фото. Попробуйте ещё раз.')
    } finally {
      if (mounted.current && opened.current && version === sequence.current) setLoading(false)
    }
  }, [release])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      opened.current = false
      // This counter invalidates async responses; it is not a DOM element ref.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      ++sequence.current
      loader.current?.abort()
      mutation.current?.abort()
      release()
    }
  }, [release])

  useEffect(() => { if (open) void load() }, [open, load])

  function toggle() {
    if (locked.current) return
    opened.current = !opened.current
    setOpen(opened.current)
    if (!opened.current) {
      ++sequence.current
      loader.current?.abort()
      release()
      setPhotos([])
      setNextOffset(null)
      setLoading(false)
      setLoaded(false)
      setMessage('')
      setError('')
    }
  }

  async function mutate(action: (signal: AbortSignal) => Promise<unknown>, success: string) {
    if (locked.current) return
    locked.current = true
    setBusy(true)
    setMessage('')
    setError('')
    const controller = new AbortController()
    mutation.current = controller
    let failureMessage = ''
    try {
      await action(controller.signal)
      if (mounted.current && opened.current) setMessage(success)
    } catch (failure) {
      failureMessage = controller.signal.aborted ? 'Запрос прерван. Проверьте обновлённый список фото.'
        : failure instanceof Error ? failure.message : 'Не удалось выполнить запрос фото.'
    } finally {
      // A failed response does not prove the server rolled back an upload or
      // removal. Always reread persisted metadata while this view is active.
      if (mounted.current && opened.current) {
        await load()
        if (mounted.current && opened.current && failureMessage) setError(failureMessage)
      }
      locked.current = false
      if (mounted.current) setBusy(false)
    }
  }

  function failedThumbnail(id: string) {
    const photo = current.current.find(item => item.id === id)
    if (photo?.url) {
      URL.revokeObjectURL(photo.url)
      urls.current.delete(photo.url)
    }
    current.current = current.current.map(item => item.id === id ? { ...item, url: null } : item)
    setPhotos(current.current)
  }

  return <section className="space-y-3 rounded-2xl border border-border/60 p-4" aria-label="Личные фото аккаунта">
    <Button type="button" variant="outline" aria-expanded={open} disabled={busy} onClick={toggle}>Фото аккаунта</Button>
    {open ? <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Сохраняйте личные фото. После привязки они доступны с обеих площадок.</p>
      <fieldset disabled={busy || loading} className="space-y-2">
        <label htmlFor={inputId} className="text-sm">Добавить фото</label>
        <Input id={inputId} type="file" accept="image/*" onChange={event => {
          const file = event.currentTarget.files?.[0]
          event.currentTarget.value = ''
          if (file) void mutate(signal => saveAccountReferencePhoto(file, signal), 'Фото сохранено.')
        }} />
        <Button type="button" variant="outline" size="sm" onClick={() => void load()}>Обновить фото</Button>
      </fieldset>
      {busy ? <div><p role="status">Сохраняем изменения…</p>
        <Button type="button" variant="outline" size="sm" onClick={() => mutation.current?.abort()}>Прервать запрос</Button></div> : null}
      {loading ? <p role="status">Загрузка фото…</p> : null}
      {message ? <p role="status" className="text-sm">{message}</p> : null}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
      {loaded && !loading && !photos.length ? <p className="text-sm text-muted-foreground">Пока нет сохранённых фото.</p> : null}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {photos.map((photo, index) => <div key={photo.id} className="min-w-0 space-y-2 rounded-xl border border-border/60 p-2">
          {photo.url ? <img src={photo.url} alt={`Фото ${index + 1}`} onError={() => failedThumbnail(photo.id)}
            className="aspect-square w-full rounded-lg object-cover" />
            : <p className="flex aspect-square items-center rounded-lg bg-secondary/40 p-2 text-sm text-muted-foreground">Превью временно недоступно.</p>}
          <Button type="button" variant="outline" size="sm" disabled={busy || loading}
            className="h-auto w-full whitespace-normal py-2" onClick={() => void mutate(
              signal => removeAccountReferencePhoto(photo.id, signal), 'Фото убрано из библиотеки.',
            )}>Убрать из библиотеки</Button>
        </div>)}
      </div>
      {!loading && photos.some(photo => !photo.url) ? <Button type="button" variant="outline" disabled={busy}
        onClick={() => void load()}>Повторить загрузку превью</Button> : null}
      {nextOffset !== null ? <Button type="button" variant="outline" disabled={busy || loading}
        onClick={() => void load(nextOffset)}>Показать ещё фото</Button> : null}
    </div> : null}
  </section>
}
