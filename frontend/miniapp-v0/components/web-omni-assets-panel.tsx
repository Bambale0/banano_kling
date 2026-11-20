'use client'

import { useEffect, useRef, useState } from 'react'

type Asset = {
  asset_id: string
  kind: 'audio' | 'character'
  name: string
  created_at_epoch: number
}
type AssetTask = {
  task_id: string
  status: 'pending' | 'completed' | 'failed'
  asset_id?: string | null
  asset_kind?: string | null
  error_code?: string | null
}
const ROOT = '/mini-app/api/web-auth/web-omni/assets'

export function WebOmniAssetsPanel({ onBalanceChanged, onTaskChanged }: {
  onBalanceChanged: () => void
  onTaskChanged: () => void
}) {
  const [assets, setAssets] = useState<Asset[]>([])
  const [voices, setVoices] = useState<string[]>([])
  const [kind, setKind] = useState<'audio' | 'character'>('audio')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [dialogue, setDialogue] = useState('')
  const [baseVoice, setBaseVoice] = useState('achernar')
  const [linkedAudio, setLinkedAudio] = useState('')
  const [reference, setReference] = useState<{ id: string; name: string } | null>(null)
  const [uploading, setUploading] = useState(false)
  const [quote, setQuote] = useState<{ key: string; price: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [activeTask, setActiveTask] = useState<AssetTask | null>(null)
  const [error, setError] = useState('')
  const key = useRef('')

  const fetchAssets = async (signal?: AbortSignal) => {
    const response = await fetch(ROOT, {
      cache: 'no-store', credentials: 'same-origin', signal,
    })
    if (!response.ok) throw new Error('Failed to load Omni assets')
    const result = await response.json() as {
      ok?: boolean; assets?: Asset[]; base_voices?: string[]
    }
    if (!result.ok || !Array.isArray(result.assets)) throw new Error('Invalid assets')
    if (!signal?.aborted) {
      setAssets(result.assets)
      setVoices(result.base_voices || [])
      window.dispatchEvent(new Event('neuromix:omni-assets-updated'))
    }
  }
  useEffect(() => {
    const controller = new AbortController()
    void fetchAssets(controller.signal).catch(() => {
      if (!controller.signal.aborted) setError('Не удалось загрузить Audio ID и Character ID.')
    })
    return () => controller.abort()
  }, [])

  const assetPayload = kind === 'audio'
    ? {
      kind, name: name.trim(), base_voice: baseVoice,
      voice_description: description, example_dialogue: dialogue,
    }
    : {
      kind, character_name: name.trim(), description: description.trim(),
      image_reference_id: reference?.id,
      ...(linkedAudio ? { audio_asset_ids: [linkedAudio] } : {}),
    }
  const quoteKey = JSON.stringify(assetPayload)
  const quoted = quote !== null && quote.key === quoteKey

  useEffect(() => {
    if (!name.trim() || (kind === 'character' && (!reference || !description.trim()))) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      void fetch(ROOT + '/quote', {
        method: 'POST', cache: 'no-store', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal, body: quoteKey,
      }).then(async response => {
        const result = await response.json() as {
          ok?: boolean; price?: string; error?: string
        }
        if (!response.ok || !result.ok || !result.price) {
          throw new Error(result.error || 'Не удалось рассчитать цену.')
        }
        if (!controller.signal.aborted) {
          setQuote({ key: quoteKey, price: result.price })
          setError('')
        }
      }).catch(() => {
        if (!controller.signal.aborted) setError('Не удалось рассчитать стоимость Audio/Character ID.')
      })
    }, 250)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [quoteKey, name, reference?.id, kind, description])

  const uploadImage = async (file: File) => {
    setUploading(true)
    setError('')
    try {
      const body = new FormData()
      body.append('image', file)
      const response = await fetch('/mini-app/api/web-auth/web-generation/reference', {
        method: 'POST', cache: 'no-store', credentials: 'same-origin', body,
      })
      const result = await response.json() as {
        ok?: boolean; reference_id?: string; error?: string
      }
      if (!response.ok || !result.ok || !result.reference_id) {
        throw new Error(result.error || 'Ошибка загрузки изображения.')
      }
      setReference({ id: result.reference_id, name: file.name })
      key.current = ''
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Ошибка загрузки изображения.')
    } finally {
      setUploading(false)
    }
  }

  const checkTask = async (taskId: string) => {
    try {
      const response = await fetch(
        '/mini-app/api/web-auth/task/' + encodeURIComponent(taskId), {
          credentials: 'same-origin', cache: 'no-store',
        },
      )
      if (!response.ok) return
      const data = await response.json() as { ok?: boolean; task?: AssetTask }
      if (!data.ok || !data.task) return
      setActiveTask(data.task)
      if (data.task.status !== 'pending') {
        onBalanceChanged()
        onTaskChanged()
        if (data.task.status === 'completed') {
          await fetchAssets()
        }
      }
    } catch {
      // Network faults cannot settle or re-issue a paid task.
    }
  }
  useEffect(() => {
    if (!activeTask || activeTask.status !== 'pending') return
    const timer = window.setInterval(() => void checkTask(activeTask.task_id), 7000)
    return () => window.clearInterval(timer)
  }, [activeTask?.task_id, activeTask?.status])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (busy || uploading || !quoted) return
    setBusy(true)
    setError('')
    if (!key.current) key.current = crypto.randomUUID().replace(/-/g, '')
    try {
      const response = await fetch(ROOT + '/create', {
        method: 'POST', cache: 'no-store', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...assetPayload,
          request_key: key.current, expected_price: quote!.price,
        }),
      })
      const result = await response.json() as {
        ok?: boolean; task_id?: string; error?: string
      }
      if (!response.ok || !result.ok || !result.task_id) {
        throw new Error(result.error || 'Не удалось создать идентификатор.')
      }
      setActiveTask({ task_id: result.task_id, status: 'pending' })
      key.current = ''
      onBalanceChanged()
      onTaskChanged()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Ошибка создания.')
    } finally {
      setBusy(false)
    }
  }

  return <section className="space-y-5 border border-[#a48350]/40 bg-[#141919] p-5"
    aria-label="Gemini Omni Audio ID и Character ID">
    <h2 className="text-xl font-bold text-[#f0c779]">Gemini Omni — Audio ID и Character ID</h2>
    <p className="text-sm text-[#bcb7af]">
      Создавайте голоса и персонажей для видеогенераций. Оплата и доступ к ID привязаны
      к текущему веб-аккаунту, а не к Telegram.
    </p>
    <form onSubmit={event => void submit(event)} className="space-y-3">
      <label className="block space-y-1 text-sm text-[#d7c0a2]">
        Тип идентификатора
        <select value={kind} disabled={busy}
          onChange={event => {
            setKind(event.target.value as 'audio' | 'character')
            setQuote(null)
            key.current = ''
          }} className="mt-1 min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white">
          <option value="audio">Audio ID — собственный голос</option>
          <option value="character">Character ID — персонаж</option>
        </select>
      </label>
      <label className="block space-y-1 text-sm text-[#d7c0a2]">
        {kind === 'audio' ? 'Имя голоса' : 'Имя персонажа'}
        <input value={name} maxLength={20} required disabled={busy}
          onChange={event => { setName(event.target.value); key.current = '' }}
          className="mt-1 min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white" />
      </label>
      {kind === 'audio' ? <label className="block space-y-1 text-sm text-[#d7c0a2]">
        Базовый голос
        <select value={baseVoice} disabled={busy}
          onChange={event => { setBaseVoice(event.target.value); key.current = '' }}
          className="mt-1 min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white">
          {(voices.length ? voices : ['achernar']).map(voice =>
            <option value={voice} key={voice}>{voice}</option>)}
        </select>
      </label> : null}
      <label className="block space-y-1 text-sm text-[#d7c0a2]">
        {kind === 'audio' ? 'Описание голоса' : 'Описание персонажа'}
        <textarea value={description} rows={3} maxLength={2000}
          required={kind === 'character'} disabled={busy}
          onChange={event => { setDescription(event.target.value); key.current = '' }}
          className="mt-1 w-full border border-[#a48350] bg-[#151b1b] p-3 text-white" />
      </label>
      {kind === 'audio' ? <label className="block space-y-1 text-sm text-[#d7c0a2]">
        Пример диалога (необязательно)
        <textarea value={dialogue} rows={2} maxLength={2000} disabled={busy}
          onChange={event => { setDialogue(event.target.value); key.current = '' }}
          className="mt-1 w-full border border-[#a48350] bg-[#151b1b] p-3 text-white" />
      </label> : <>
        <label className="block space-y-1 text-sm text-[#d7c0a2]">
          Изображение персонажа
          <input type="file" accept="image/png,image/jpeg,image/webp"
            disabled={busy || uploading} onChange={event => {
              const file = event.target.files?.[0]
              if (file) void uploadImage(file)
              event.target.value = ''
            }} className="mt-1 block max-w-full text-xs text-[#d9c7ae]" />
        </label>
        {reference ? <p className="text-xs text-[#efd09a]">Загружено: {reference.name}</p> : null}
        <label className="block space-y-1 text-sm text-[#d7c0a2]">
          Связанный Audio ID (необязательно)
          <select value={linkedAudio} disabled={busy}
            onChange={event => { setLinkedAudio(event.target.value); key.current = '' }}
            className="mt-1 min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white">
            <option value="">Без голоса</option>
            {assets.filter(item => item.kind === 'audio').map(item =>
              <option key={item.asset_id} value={item.asset_id}>{item.name}</option>)}
          </select>
        </label>
      </>}
      <button type="submit" disabled={busy || uploading || !quoted}
        className="min-h-11 w-full bg-[#d5ab63] p-2 font-bold text-[#17120d] disabled:opacity-50">
        {busy ? 'Создаём ID…'
          : quoted ? 'Создать за ' + quote!.price + ' кредитов'
            : 'Ожидаем расчёта цены'}
      </button>
    </form>
    {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
    {activeTask ? <div className="space-y-2 border border-[#a48350]/40 p-3">
      <p role="status" className="text-sm">{activeTask.status === 'pending' ? 'Создаём ID…'
        : activeTask.status === 'completed' ? 'ID готов и привязан к аккаунту'
          : 'Не удалось создать ID; резерв возвращён'}</p>
      {activeTask.status === 'pending' ? <button type="button"
        className="min-h-11 border border-[#a48350]/60 px-3 text-sm text-white"
        onClick={() => void checkTask(activeTask.task_id)}>Проверить статус</button> : null}
    </div> : null}
    <div className="space-y-2">
      <h3 className="font-semibold">Мои идентификаторы</h3>
      {assets.length === 0 ? <p className="text-sm text-[#ada89e]">Пока нет Audio ID и Character ID.</p> : null}
      {assets.map(asset => <p key={asset.asset_id} className="text-sm text-[#d9c7ae]">
        {asset.kind === 'audio' ? 'Голос' : 'Персонаж'}: {asset.name}
        <span className="ml-2 text-xs text-[#9c9d98]">({asset.asset_id.slice(0, 12)}…)</span>
      </p>)}
    </div>
  </section>
}
