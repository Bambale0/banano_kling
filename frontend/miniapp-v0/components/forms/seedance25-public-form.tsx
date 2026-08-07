'use client'

import { useMemo, useState } from 'react'
import { uploadFile } from '@/lib/api'
import {
  generateSeedance25,
  uploadSeedance25Video,
  type Seedance25GenerateResponse,
  type Seedance25OutputFormat,
  type Seedance25Resolution,
  type Seedance25Scenario,
} from '@/lib/seedance25-api'
import type { UploadedFile, VideoModel } from '@/lib/types'

const RATIOS = ['adaptive', '16:9', '9:16', '1:1', '4:3', '3:4', '21:9'] as const
const IMAGE_EXTS = new Set(['jpg', 'jpeg', 'png', 'webp', 'bmp', 'tiff', 'tif', 'gif'])
const VIDEO_EXTS = new Set(['mp4', 'mov'])
const AUDIO_EXTS = new Set(['wav', 'mp3'])

interface Props {
  model?: VideoModel
  credits: number
  isAdmin: boolean
  onQueued?: (result: Seedance25GenerateResponse) => void | Promise<void>
  onSavedReference?: (file: UploadedFile) => void
}

interface RefItem {
  file: UploadedFile
  duration?: number
}

function ext(name: string) {
  return String(name || '').split('.').pop()?.toLowerCase() || ''
}

function splitSources(raw: string, limit: number) {
  const values = raw
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
  const unique = [...new Set(values)]
  if (unique.length > limit) throw new Error(`Максимум ${limit} ссылок/asset ID`)
  for (const value of unique) {
    if (!value.startsWith('asset://') && !/^https?:\/\//i.test(value)) {
      throw new Error(`Некорректный URL/asset: ${value}`)
    }
  }
  return unique
}

function fileDuration(file: File, kind: 'video' | 'audio'): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const media = document.createElement(kind)
    media.preload = 'metadata'
    media.onloadedmetadata = () => {
      const duration = Number(media.duration || 0)
      URL.revokeObjectURL(url)
      resolve(duration || null)
    }
    media.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(null)
    }
    media.src = url
  })
}

function Option({ active, children, onClick }: { active?: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-xl border px-3 py-2 text-xs font-medium transition ${
        active
          ? 'border-cyan/60 bg-cyan/15 text-cyan'
          : 'border-border/50 bg-secondary/40 text-muted-foreground hover:text-foreground'
      }`}
    >
      {children}
    </button>
  )
}

function Toggle({ value, label, onChange }: { value: boolean; label: string; onChange: (value: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      className={`flex items-center justify-between rounded-xl border px-3 py-2 text-xs ${
        value ? 'border-cyan/50 bg-cyan/10 text-foreground' : 'border-border/50 bg-secondary/30 text-muted-foreground'
      }`}
    >
      <span>{label}</span>
      <span className="ml-3 font-mono">{value ? 'ON' : 'OFF'}</span>
    </button>
  )
}

function FileRow({ item, onRemove }: { item: RefItem; onRemove: () => void }) {
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-lg border border-border/40 bg-background/40 px-2 py-1.5 text-xs">
      <span className="min-w-0 flex-1 truncate">{item.file.name}</span>
      {item.duration ? <span className="text-muted-foreground">{item.duration.toFixed(1)}с</span> : null}
      <button type="button" onClick={onRemove} className="text-destructive">×</button>
    </div>
  )
}

export function Seedance25PublicForm({ model, credits, isAdmin, onQueued, onSavedReference }: Props) {
  const [scenario, setScenario] = useState<Seedance25Scenario>('text')
  const [resolution, setResolution] = useState<Seedance25Resolution>('720p')
  const [ratio, setRatio] = useState<(typeof RATIOS)[number]>('adaptive')
  const [duration, setDuration] = useState(5)
  const [outputFormat, setOutputFormat] = useState<Seedance25OutputFormat>('mp4')
  const [generateAudio, setGenerateAudio] = useState(true)
  const [returnLastFrame, setReturnLastFrame] = useState(false)
  const [webSearch, setWebSearch] = useState(false)
  const [nsfwChecker, setNsfwChecker] = useState(false)
  const [prompt, setPrompt] = useState('')

  const [firstFrame, setFirstFrame] = useState<RefItem | null>(null)
  const [lastFrame, setLastFrame] = useState<RefItem | null>(null)
  const [images, setImages] = useState<RefItem[]>([])
  const [videos, setVideos] = useState<RefItem[]>([])
  const [audios, setAudios] = useState<RefItem[]>([])

  const [firstSource, setFirstSource] = useState('')
  const [lastSource, setLastSource] = useState('')
  const [imageSources, setImageSources] = useState('')
  const [videoSources, setVideoSources] = useState('')
  const [audioSources, setAudioSources] = useState('')

  const [uploading, setUploading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [queued, setQueued] = useState<Seedance25GenerateResponse | null>(null)

  const price = useMemo(() => {
    const seconds = duration === -1 ? 5 : duration
    const perSecond = Number(model?.quality_costs?.[resolution] || 0)
    return perSecond ? Math.round(perSecond * seconds * 2) / 2 : 0
  }, [duration, model?.quality_costs, resolution])
  const canAfford = isAdmin || !price || credits >= price
  const knownVideoSeconds = useMemo(
    () => videos.reduce((sum, item) => sum + (item.duration || 0), 0),
    [videos],
  )

  const runUpload = async (fn: () => Promise<void>) => {
    setUploading(true)
    setError(null)
    try {
      await fn()
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Не удалось загрузить файл')
    } finally {
      setUploading(false)
    }
  }

  const uploadImage = async (file: File, target: 'first' | 'last' | 'refs') => {
    if (!IMAGE_EXTS.has(ext(file.name))) throw new Error('Фото: JPEG/PNG/WEBP/BMP/TIFF/GIF')
    if (file.size > 30 * 1024 * 1024) throw new Error('Фото — максимум 30 MB')
    const uploaded = await uploadFile('seedance25_image_reference' as any, file)
    onSavedReference?.(uploaded)
    const item = { file: uploaded }
    if (target === 'first') setFirstFrame(item)
    else if (target === 'last') setLastFrame(item)
    else setImages((current) => [...current, item].slice(0, 30))
  }

  const uploadVideo = async (file: File) => {
    if (!VIDEO_EXTS.has(ext(file.name))) throw new Error('Видео: MP4 или MOV')
    if (file.size > 200 * 1024 * 1024) throw new Error('Видео — максимум 200 MB')
    if (videos.length >= 10) throw new Error('Максимум 10 видео-референсов')
    const seconds = await fileDuration(file, 'video')
    if (seconds && (seconds < 2 || seconds > 30)) throw new Error('Видео должно быть 2–30 секунд')
    if (seconds && knownVideoSeconds + seconds > 30.01) throw new Error('Суммарно видео-референсы — максимум 30 секунд')
    const uploaded = await uploadSeedance25Video(file)
    onSavedReference?.(uploaded)
    setVideos((current) => [...current, { file: uploaded, duration: seconds || undefined }].slice(0, 10))
  }

  const uploadAudio = async (file: File) => {
    if (!AUDIO_EXTS.has(ext(file.name))) throw new Error('Аудио: WAV или MP3')
    if (file.size > 15 * 1024 * 1024) throw new Error('Аудио — максимум 15 MB')
    if (audios.length >= 10) throw new Error('Максимум 10 аудио-референсов')
    const seconds = await fileDuration(file, 'audio')
    if (seconds && (seconds < 2 || seconds > 30)) throw new Error('Аудио должно быть 2–30 секунд')
    const uploaded = await uploadFile('seedance25_audio_reference' as any, file)
    onSavedReference?.(uploaded)
    setAudios((current) => [...current, { file: uploaded, duration: seconds || undefined }].slice(0, 10))
  }

  const chooseScenario = (next: Seedance25Scenario) => {
    setScenario(next)
    setError(null)
    if (next === 'text') {
      setFirstFrame(null); setLastFrame(null); setImages([]); setVideos([]); setAudios([])
    } else if (next === 'first_frame') {
      setLastFrame(null); setImages([]); setVideos([]); setAudios([])
    } else if (next === 'first_last') {
      setImages([]); setVideos([]); setAudios([])
    } else {
      setFirstFrame(null); setLastFrame(null)
    }
  }

  const submit = async () => {
    setError(null)
    setQueued(null)
    try {
      if (prompt.length > 5000) throw new Error('Промпт — максимум 5000 символов')
      if (duration === -1 && !isAdmin) throw new Error('Auto-длительность пока только для администратора')

      const first = firstSource.trim() || firstFrame?.file.url || null
      const last = lastSource.trim() || lastFrame?.file.url || null
      const refImages = [...images.map((item) => item.file.url), ...splitSources(imageSources, 30)]
      const refVideos = [...videos.map((item) => item.file.url), ...splitSources(videoSources, 10)]
      const refAudios = [...audios.map((item) => item.file.url), ...splitSources(audioSources, 10)]

      if (scenario === 'text' && !prompt.trim()) throw new Error('Для Text-to-Video нужен промпт')
      if (scenario === 'first_frame' && !first) throw new Error('Добавьте первый кадр')
      if (scenario === 'first_last' && (!first || !last)) throw new Error('Добавьте первый и последний кадры')
      if (scenario === 'multimodal' && !refImages.length && !refVideos.length && !refAudios.length) {
        throw new Error('Добавьте хотя бы один референс')
      }
      if (!canAfford) throw new Error(`Недостаточно бананов. Нужно ${price}🍌`)

      setSubmitting(true)
      const result = await generateSeedance25({
        scenario,
        prompt: prompt.trim(),
        ratio,
        duration,
        resolution,
        outputFormat,
        generateAudio,
        returnLastFrame,
        webSearch,
        nsfwChecker,
        firstFrameUrl: scenario === 'first_frame' || scenario === 'first_last' ? first : null,
        lastFrameUrl: scenario === 'first_last' ? last : null,
        referenceImages: scenario === 'multimodal' ? [...new Set(refImages)].slice(0, 30) : [],
        referenceVideos: scenario === 'multimodal' ? [...new Set(refVideos)].slice(0, 10) : [],
        referenceAudios: scenario === 'multimodal' ? [...new Set(refAudios)].slice(0, 10) : [],
      })
      setQueued(result)
      await onQueued?.(result)
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Не удалось запустить Seedance 2.5')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="glass min-w-0 space-y-5 overflow-hidden rounded-2xl border border-cyan/30 p-3 sm:p-4">
      <div className="rounded-xl border border-cyan/30 bg-cyan/5 p-3">
        <div className="flex items-center gap-2">
          <span className="rounded-full border border-gold/40 bg-gold/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.14em] text-gold">NEW</span>
          <h3 className="font-serif text-lg font-semibold text-foreground">Seedance 2.5</h3>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          Bytedance: текст → видео, первый/последний кадр и мультимодальные фото/видео/аудио референсы. Камеру и lens lock описывайте в промпте.
        </p>
      </div>

      <section className="space-y-2">
        <label className="text-sm font-medium">Сценарий</label>
        <div className="grid grid-cols-2 gap-2">
          <Option active={scenario === 'text'} onClick={() => chooseScenario('text')}>✍️ Текст</Option>
          <Option active={scenario === 'first_frame'} onClick={() => chooseScenario('first_frame')}>🖼 Первый кадр</Option>
          <Option active={scenario === 'first_last'} onClick={() => chooseScenario('first_last')}>🎞 Первый + последний</Option>
          <Option active={scenario === 'multimodal'} onClick={() => chooseScenario('multimodal')}>🧩 Референсы</Option>
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <label className="text-sm font-medium">Качество</label>
          <div className="grid grid-cols-2 gap-2">
            {(['480p', '720p'] as Seedance25Resolution[]).map((value) => (
              <Option key={value} active={resolution === value} onClick={() => setResolution(value)}>{value}</Option>
            ))}
          </div>
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium">Файл</label>
          <div className="grid grid-cols-2 gap-2">
            {(['mp4', 'mov'] as Seedance25OutputFormat[]).map((value) => (
              <Option key={value} active={outputFormat === value} onClick={() => setOutputFormat(value)}>{value.toUpperCase()}</Option>
            ))}
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <label className="text-sm font-medium">Формат кадра</label>
        <div className="flex flex-wrap gap-2">
          {RATIOS.map((value) => <Option key={value} active={ratio === value} onClick={() => setRatio(value)}>{value}</Option>)}
        </div>
      </section>

      <section className="space-y-2">
        <div className="flex items-center justify-between"><label className="text-sm font-medium">Длительность</label><span className="text-xs text-muted-foreground">{duration === -1 ? 'Auto' : `${duration}с`}</span></div>
        <div className="flex items-center gap-2">
          {isAdmin ? <Option active={duration === -1} onClick={() => setDuration(-1)}>Auto</Option> : null}
          <button type="button" className="rounded-xl border border-border/50 px-3 py-2" onClick={() => setDuration((value) => Math.max(4, value === -1 ? 5 : value - 1))}>−</button>
          <input type="range" min={4} max={30} value={duration === -1 ? 5 : duration} onChange={(event) => setDuration(Number(event.target.value))} className="min-w-0 flex-1" />
          <button type="button" className="rounded-xl border border-border/50 px-3 py-2" onClick={() => setDuration((value) => Math.min(30, value === -1 ? 5 : value + 1))}>+</button>
        </div>
      </section>

      <section className="grid gap-2 sm:grid-cols-2">
        <Toggle value={generateAudio} onChange={setGenerateAudio} label="🔊 Генерировать аудио" />
        <Toggle value={returnLastFrame} onChange={setReturnLastFrame} label="🖼 Вернуть последний кадр" />
        <Toggle value={webSearch} onChange={setWebSearch} label="🌐 Web search" />
        <Toggle value={nsfwChecker} onChange={setNsfwChecker} label="🛡 NSFW checker" />
      </section>

      {(scenario === 'first_frame' || scenario === 'first_last') ? (
        <section className="space-y-4 rounded-xl border border-border/50 p-3">
          <div className="space-y-2">
            <label className="text-sm font-medium">Первый кадр</label>
            <input type="file" accept="image/*,.jpg,.jpeg,.png,.webp,.bmp,.tiff,.gif" disabled={uploading} onChange={(event) => { const file = event.target.files?.[0]; if (file) void runUpload(() => uploadImage(file, 'first')); event.currentTarget.value = '' }} className="block w-full text-xs" />
            {firstFrame ? <FileRow item={firstFrame} onRemove={() => setFirstFrame(null)} /> : null}
            <input value={firstSource} onChange={(event) => setFirstSource(event.target.value)} placeholder="или https://... / asset://..." className="w-full rounded-xl border border-border/50 bg-background/40 px-3 py-2 text-xs" />
          </div>
          {scenario === 'first_last' ? (
            <div className="space-y-2">
              <label className="text-sm font-medium">Последний кадр</label>
              <input type="file" accept="image/*,.jpg,.jpeg,.png,.webp,.bmp,.tiff,.gif" disabled={uploading} onChange={(event) => { const file = event.target.files?.[0]; if (file) void runUpload(() => uploadImage(file, 'last')); event.currentTarget.value = '' }} className="block w-full text-xs" />
              {lastFrame ? <FileRow item={lastFrame} onRemove={() => setLastFrame(null)} /> : null}
              <input value={lastSource} onChange={(event) => setLastSource(event.target.value)} placeholder="или https://... / asset://..." className="w-full rounded-xl border border-border/50 bg-background/40 px-3 py-2 text-xs" />
            </div>
          ) : null}
        </section>
      ) : null}

      {scenario === 'multimodal' ? (
        <section className="space-y-4 rounded-xl border border-border/50 p-3">
          <div className="space-y-2">
            <div className="flex justify-between"><label className="text-sm font-medium">Фото</label><span className="text-xs text-muted-foreground">{images.length}/30</span></div>
            <input type="file" multiple accept="image/*,.jpg,.jpeg,.png,.webp,.bmp,.tiff,.gif" disabled={uploading || images.length >= 30} onChange={(event) => { const files = Array.from(event.target.files || []).slice(0, 30 - images.length); if (files.length) void runUpload(async () => { for (const file of files) await uploadImage(file, 'refs') }); event.currentTarget.value = '' }} className="block w-full text-xs" />
            <div className="space-y-1">{images.map((item, index) => <FileRow key={`${item.file.id}-${index}`} item={item} onRemove={() => setImages((current) => current.filter((_, i) => i !== index))} />)}</div>
            <textarea rows={2} value={imageSources} onChange={(event) => setImageSources(event.target.value)} placeholder="Доп. image URL/asset:// по одному на строку" className="w-full rounded-xl border border-border/50 bg-background/40 px-3 py-2 text-xs" />
          </div>

          <div className="space-y-2">
            <div className="flex justify-between"><label className="text-sm font-medium">Видео</label><span className="text-xs text-muted-foreground">{videos.length}/10 · {knownVideoSeconds.toFixed(1)}/30с</span></div>
            <input type="file" multiple accept=".mp4,.mov,video/mp4,video/quicktime" disabled={uploading || videos.length >= 10} onChange={(event) => { const files = Array.from(event.target.files || []).slice(0, 10 - videos.length); if (files.length) void runUpload(async () => { for (const file of files) await uploadVideo(file) }); event.currentTarget.value = '' }} className="block w-full text-xs" />
            <p className="text-[11px] text-muted-foreground">До 200 MB на файл. Большие файлы загружаются частями; сервер повторно проверяет формат, FPS, размеры и длительность.</p>
            <div className="space-y-1">{videos.map((item, index) => <FileRow key={`${item.file.id}-${index}`} item={item} onRemove={() => setVideos((current) => current.filter((_, i) => i !== index))} />)}</div>
            <textarea rows={2} value={videoSources} onChange={(event) => setVideoSources(event.target.value)} placeholder="Доп. video URL/asset:// по одному на строку" className="w-full rounded-xl border border-border/50 bg-background/40 px-3 py-2 text-xs" />
          </div>

          <div className="space-y-2">
            <div className="flex justify-between"><label className="text-sm font-medium">Аудио</label><span className="text-xs text-muted-foreground">{audios.length}/10</span></div>
            <input type="file" multiple accept=".wav,.mp3,audio/wav,audio/mpeg" disabled={uploading || audios.length >= 10} onChange={(event) => { const files = Array.from(event.target.files || []).slice(0, 10 - audios.length); if (files.length) void runUpload(async () => { for (const file of files) await uploadAudio(file) }); event.currentTarget.value = '' }} className="block w-full text-xs" />
            <div className="space-y-1">{audios.map((item, index) => <FileRow key={`${item.file.id}-${index}`} item={item} onRemove={() => setAudios((current) => current.filter((_, i) => i !== index))} />)}</div>
            <textarea rows={2} value={audioSources} onChange={(event) => setAudioSources(event.target.value)} placeholder="Доп. audio URL/asset:// по одному на строку" className="w-full rounded-xl border border-border/50 bg-background/40 px-3 py-2 text-xs" />
          </div>
        </section>
      ) : null}

      <section className="space-y-2">
        <div className="flex justify-between"><label className="text-sm font-medium">Промпт</label><span className={`text-xs ${prompt.length > 5000 ? 'text-destructive' : 'text-muted-foreground'}`}>{prompt.length}/5000</span></div>
        <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={7} placeholder="Сцена, движение персонажей и камеры..." className="w-full resize-y rounded-xl border border-border/50 bg-background/40 px-3 py-3 text-sm" />
      </section>

      <div className="rounded-xl border border-gold/20 bg-gold/5 p-3 text-xs">
        <div className="flex items-center justify-between gap-3"><span className="text-muted-foreground">Стоимость</span><strong>{isAdmin ? `${price || 0}🍌 · для админа бесплатно` : `${price || 0}🍌`}</strong></div>
        {!isAdmin ? <div className="mt-1 text-muted-foreground">Баланс: {credits}🍌</div> : null}
      </div>

      {error ? <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</div> : null}
      {queued ? (
        <div className="rounded-xl border border-cyan/30 bg-cyan/5 p-3 text-sm">
          <strong>✅ Seedance 2.5 поставлена в очередь</strong>
          <div className="mt-1 break-all font-mono text-xs text-muted-foreground">{queued.task_id}</div>
          <div className="mt-1 text-xs text-muted-foreground">{queued.admin_free ? 'Для администратора без списания.' : `Списано ${queued.cost}🍌.`} Результат придёт в Telegram.</div>
        </div>
      ) : null}

      <button type="button" disabled={submitting || uploading || !canAfford || prompt.length > 5000} onClick={() => void submit()} className="w-full rounded-xl border border-cyan/50 bg-cyan/15 px-4 py-3 text-sm font-semibold text-cyan disabled:cursor-not-allowed disabled:opacity-50">
        {submitting ? 'Запускаю Seedance 2.5…' : uploading ? 'Загружаю медиа…' : !canAfford ? `Нужно ${price}🍌` : '🚀 Запустить Seedance 2.5'}
      </button>
    </div>
  )
}
