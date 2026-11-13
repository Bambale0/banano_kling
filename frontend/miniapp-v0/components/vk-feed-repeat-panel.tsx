'use client'

import { useRef, useState } from 'react'
import {
  fetchVkGenerationClaim,
  repeatVkFeed,
  uploadVkImage,
  type VkFeedRepeatRequest,
} from '@/lib/shared-account-api'

function newNativeVkClaim(): string {
  if (typeof crypto === 'undefined' || typeof crypto.getRandomValues !== 'function') {
    throw new Error('Защищённая генерация идентификаторов недоступна. Обновите приложение.')
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return 'vk_' + Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}

/** Public FEED source, not editorial trend. Only the signed VK BFF knows recipe. */
export function VkFeedRepeatPanel({
  feedId, onClose, onFinished,
}: {
  feedId: number
  onClose: () => void
  onFinished?: () => void
}) {
  const [files, setFiles] = useState<File[]>([])
  const [quoted, setQuoted] = useState<VkFeedRepeatRequest | null>(null)
  const [price, setPrice] = useState<number | null>(null)
  const [claim, setClaim] = useState('')
  const [task, setTask] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const operation = useRef(false)
  const epoch = useRef(0)

  function invalidate() {
    epoch.current += 1
    setQuoted(null)
    setPrice(null)
    setClaim('')
    setTask(null)
    setError('')
  }

  async function quote() {
    if (operation.current) return
    operation.current = true
    const seq = ++epoch.current
    setBusy(true)
    setError('')
    setPrice(null)
    setQuoted(null)
    setTask(null)
    try {
      const references: string[] = []
      for (const file of files) {
        references.push(await uploadVkImage(file))
      }
      const payload: VkFeedRepeatRequest = {
        feed_gen_id: feedId, reference_urls: references, quote_only: true,
      }
      const result = await repeatVkFeed(payload)
      if (epoch.current !== seq) return
      if (typeof result.cost !== 'number' || !Number.isFinite(result.cost) || result.cost <= 0) {
        throw new Error('Сервер не подтвердил стоимость повтора.')
      }
      setQuoted(payload)
      setPrice(result.cost)
      setClaim(newNativeVkClaim())
    } catch (reason) {
      if (epoch.current === seq) setError(reason instanceof Error ? reason.message : 'Не удалось рассчитать повтор.')
    } finally {
      operation.current = false
      if (epoch.current === seq) setBusy(false)
    }
  }

  async function submit() {
    if (operation.current || !quoted || price === null || !claim || task !== null) return
    operation.current = true
    const seq = epoch.current
    setBusy(true)
    setError('')
    try {
      const answer = await repeatVkFeed({
        ...quoted, quote_only: false,
        client_request_id: claim, expected_cost: price,
      })
      if (seq !== epoch.current) return
      if (!Number.isSafeInteger(answer.task_id) || answer.task_id < 1) {
        throw new Error('Задача не подтверждена')
      }
      setTask(answer.task_id)
      setPrice(null)
      onFinished?.()
    } catch {
      if (seq !== epoch.current) return
      try {
        const saved = await fetchVkGenerationClaim(claim)
        if (seq !== epoch.current) return
        if (saved.found && saved.task_type === 'photo'
          && Number.isSafeInteger(saved.task_id) && (saved.task_id || 0) > 0) {
          setTask(saved.task_id!)
          setPrice(null)
          onFinished?.()
          return
        }
      } catch {
        // A failed claim lookup does not prove the native VK wallet was
        // untouched. Never issue a new key or an automatic second POST.
      }
      if (seq === epoch.current) setError(
        'Статус операции неизвестен. Проверьте «Мои работы». '
        + 'Повторная попытка использует тот же идентификатор списания.',
      )
    } finally {
      operation.current = false
      if (seq === epoch.current) setBusy(false)
    }
  }

  return <section aria-label="Повтор публикации из ленты" className="space-y-3 rounded-2xl border border-primary/30 bg-card p-4">
    <div className="flex items-center justify-between">
      <h4 className="font-semibold">Повтор публикации #{feedId}</h4>
      <button type="button" disabled={busy} className="text-sm underline" onClick={onClose}>Закрыть</button>
    </div>
    <p className="text-sm text-muted-foreground">
      Загрузите свои референсы. Промпт и параметры публикации проверяет сервер.
      Референсы автора не передаются другому пользователю.
    </p>
    {task === null && <label className="block space-y-2 text-sm">
      Ваши фото-референсы (по возможностям модели)
      <input type="file" aria-label="Фото для повтора публикации" accept="image/*" multiple
        disabled={busy} onChange={event => {
          invalidate()
          setFiles(Array.from(event.target.files || []))
        }} className="block w-full rounded-lg border border-border p-2" />
    </label>}
    {price !== null && task === null && <p role="status" className="text-sm">
      Подтверждённая стоимость: {price} 🍌 из VK-баланса
    </p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {task !== null ? <p role="status" className="text-sm">
      Задача #{task} создана. Результат появится в «Мои работы» ВКонтакте.
    </p> : <div className="flex gap-2">
      <button type="button" disabled={busy} onClick={() => void quote()}
        className="rounded-xl border border-border px-4 py-2 text-sm">
        {busy ? 'Проверяем…' : 'Рассчитать стоимость'}
      </button>
      <button type="button" disabled={busy || price === null || !claim} onClick={() => void submit()}
        className="rounded-xl bg-primary px-4 py-2 text-sm text-primary-foreground">
        Создать с VK-баланса
      </button>
    </div>}
  </section>
}
