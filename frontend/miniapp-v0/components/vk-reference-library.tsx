'use client'

import { useEffect, useRef, useState } from 'react'
import {
  fetchVkSavedReferences,
  forgetVkSavedReference,
  saveVkSavedReference,
  uploadVkImage,
  type VkSavedReference,
} from '@/lib/shared-account-api'

/** Private owner-only reference bookmarks over actual VK S3 uploads. */
export function VkReferenceLibrary({ canUpload = true }: { canUpload?: boolean }) {
  const [references, setReferences] = useState<VkSavedReference[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [pending, setPending] = useState<{ url: string; name: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const busyRef = useRef(false)

  async function refresh(signal?: AbortSignal) {
    const value = await fetchVkSavedReferences(signal)
    if (!signal?.aborted) setReferences(value)
  }

  useEffect(() => {
    const controller = new AbortController()
    void refresh(controller.signal).catch(cause => {
      if (!controller.signal.aborted) setError(cause instanceof Error
        ? cause.message : 'Не удалось загрузить библиотеку ВКонтакте.')
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => controller.abort()
  }, [])

  async function save() {
    if (busyRef.current || (!file && !pending)) return
    busyRef.current = true
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const chosen = pending || {
        url: await uploadVkImage(file!),
        name: (file!.name.trim().slice(0, 80) || 'Моё фото'),
      }
      // If the first request uploaded successfully but the metadata write
      // timed out, retrying must reuse the SAME uploaded object, not upload
      // the image a second time.
      setPending(chosen)
      const saved = await saveVkSavedReference(chosen.url, chosen.name)
      setReferences(previous => [saved, ...previous.filter(item => item.reference_id !== saved.reference_id)])
      setPending(null)
      setFile(null)
      setMessage('Фото добавлено в библиотеку ВКонтакте.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось сохранить фото.')
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  async function forget(referenceId: string) {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await forgetVkSavedReference(referenceId)
      // A missing row is already forgotten; deletion is idempotent.
      setReferences(previous => previous.filter(item => item.reference_id !== referenceId))
      setMessage('Фото убрано из сохранённых. Исходный файл не удалён.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось убрать фото.')
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  return <section aria-label="Сохранённые VK-референсы"
    className="space-y-3 rounded-2xl border border-border/70 bg-card p-4">
    <h3 className="text-base font-semibold">Мои сохранённые фото</h3>
    <p className="text-xs text-muted-foreground">
      Только ваши референсы ВКонтакте. Используйте их снова при создании фото и видео.
    </p>
    {loading && <p role="status">Загружаем ваши референсы…</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {message && <p role="status" className="text-sm">{message}</p>}
    {canUpload && <div className="space-y-2">
      <label className="block space-y-1 text-sm">Добавить фото
        <input type="file" aria-label="Фото в VK-библиотеку" accept="image/*"
          disabled={busy} className="block w-full rounded-lg border border-border p-2"
          onChange={event => {
            setFile(event.currentTarget.files?.[0] ?? null)
            setPending(null)
            setError('')
          }} />
      </label>
      <button type="button" disabled={busy || (!file && !pending)}
        onClick={() => void save()}
        className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground">
        {busy ? 'Сохраняем…' : pending ? 'Повторить сохранение' : 'Сохранить фото'}
      </button>
    </div>}
    {!loading && references.length === 0 && <p className="text-sm text-muted-foreground">
      Пока нет сохранённых референсов.
    </p>}
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {references.map(item => <article key={item.reference_id}
        className="space-y-2 rounded-xl border border-border/70 p-2">
        <img src={item.url} alt={item.name} loading="lazy"
          className="aspect-square w-full rounded-lg object-cover" />
        <p className="truncate text-xs" title={item.name}>{item.name}</p>
        <button type="button" disabled={busy}
          onClick={() => void forget(item.reference_id)}
          className="rounded-lg border border-border px-2 py-1 text-xs">
          Убрать из сохранённых
        </button>
      </article>)}
    </div>
  </section>
}
