from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected pattern not found in {relative}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def write(relative: str, content: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# Backend: persist a structured, extensible settings snapshot with each prompt/trend.
replace_once(
    "bot/database.py",
    """    tags: Optional[list[str]] = None
    likes: int = 0
""",
    """    tags: Optional[list[str]] = None
    generation_settings: Optional[dict[str, Any]] = None
    likes: int = 0
""",
)
replace_once(
    "bot/database.py",
    """        tags=[str(tag) for tag in _parse_json_list(row["tags"])],
        likes=int(row["likes"] or 0),
""",
    """        tags=[str(tag) for tag in _parse_json_list(row["tags"])],
        generation_settings=(
            _parse_json_dict(row["generation_settings"])
            if "generation_settings" in row.keys()
            else {}
        ),
        likes=int(row["likes"] or 0),
""",
)
replace_once(
    "bot/database.py",
    """        "tags": prompt.tags or [],
        "likes": prompt.likes,
""",
    """        "tags": prompt.tags or [],
        "generation_settings": prompt.generation_settings or {},
        "likes": prompt.likes,
""",
)
replace_once(
    "bot/database.py",
    """            tags TEXT DEFAULT '[]',
            likes INTEGER DEFAULT 0,
""",
    """            tags TEXT DEFAULT '[]',
            generation_settings TEXT DEFAULT '{}',
            likes INTEGER DEFAULT 0,
""",
)
replace_once(
    "bot/database.py",
    """    try:
        await db.execute("ALTER TABLE user_prompts ADD COLUMN source_generation_id INTEGER")
    except db_backend.OperationalError:
        pass
""",
    """    try:
        await db.execute("ALTER TABLE user_prompts ADD COLUMN source_generation_id INTEGER")
    except db_backend.OperationalError:
        pass
    try:
        await db.execute(
            "ALTER TABLE user_prompts ADD COLUMN generation_settings TEXT DEFAULT '{}'"
        )
    except db_backend.OperationalError:
        pass
""",
)
replace_once(
    "bot/database.py",
    """    tags: Optional[list[str]] = None,
    is_public: bool = True,
""",
    """    tags: Optional[list[str]] = None,
    generation_settings: Optional[dict[str, Any]] = None,
    is_public: bool = True,
""",
)
replace_once(
    "bot/database.py",
    """                model, tags, is_public, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
""",
    """                model, tags, generation_settings, is_public, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
""",
)
replace_once(
    "bot/database.py",
    """                json.dumps(inferred_tags, ensure_ascii=False),
                1 if is_public else 0,
""",
    """                json.dumps(inferred_tags, ensure_ascii=False),
                json.dumps(generation_settings or {}, ensure_ascii=False),
                1 if is_public else 0,
""",
)

replace_once(
    "bot/miniapp.py",
    """        active_count = await count_active_prompts_by_author(user.id)
""",
    """        raw_generation_settings = body.get("generation_settings")
        generation_settings = (
            dict(raw_generation_settings)
            if isinstance(raw_generation_settings, dict)
            else {}
        )
        if not config.is_admin(telegram_id):
            generation_settings = {}
        if len(json.dumps(generation_settings, ensure_ascii=False)) > 12_000:
            return web.json_response(
                {"ok": False, "error": "Слишком много настроек тренда"},
                status=400,
            )

        active_count = await count_active_prompts_by_author(user.id)
""",
)
replace_once(
    "bot/miniapp.py",
    """            tags=[str(item) for item in list(body.get("tags", []) or [])],
            is_public=True,
""",
    """            tags=[str(item) for item in list(body.get("tags", []) or [])],
            generation_settings=generation_settings,
            is_public=True,
""",
)

# Shared frontend contract.
replace_once(
    "frontend/miniapp-v0/lib/types.ts",
    """export interface PromptItem {
""",
    """export interface TrendGenerationSettings {
  kind: 'image' | 'video'
  user_input: 'photo'
  model: string
  ratio: string
  quality?: string
  count?: number
  nsfw_checker?: boolean
  nsfw_enabled?: boolean
  scenario?: ScenarioType
  duration?: number
  grok_mode?: string
  grok_resolution?: string
  veo_generation_type?: string
  veo_translation?: boolean
  veo_resolution?: string
  veo_seed?: number | null
  veo_watermark?: string
  kling_negative_prompt?: string
  kling_cfg_scale?: number
  omni_resolution?: string
  omni_seed?: number | null
  omni_audio_ids?: string[]
  omni_character_ids?: string[]
  omni_base_voice?: string
  omni_voice_name?: string
  omni_voice_description?: string
  omni_example_dialogue?: string
  omni_character_name?: string
  omni_character_audio_ids?: string[]
}

export interface PromptItem {
""",
)
replace_once(
    "frontend/miniapp-v0/lib/types.ts",
    """  model?: string | null
  author_id: number
""",
    """  model?: string | null
  generation_settings?: TrendGenerationSettings | null
  author_id: number
""",
)

replace_once(
    "frontend/miniapp-v0/lib/api.ts",
    """  TaskDetail,
  UploadedFile,
""",
    """  TaskDetail,
  TrendGenerationSettings,
  UploadedFile,
""",
)
replace_once(
    "frontend/miniapp-v0/lib/api.ts",
    """  model?: string
  tags?: string[]
}): Promise<PromptItem> {
""",
    """  model?: string
  tags?: string[]
  generationSettings?: TrendGenerationSettings
}): Promise<PromptItem> {
""",
)
replace_once(
    "frontend/miniapp-v0/lib/api.ts",
    """    model: payload.model || '',
    tags: payload.tags || [],
""",
    """    model: payload.model || '',
    tags: payload.tags || [],
    generation_settings: payload.generationSettings || {},
""",
)

# Trend settings resolver: structured settings first, legacy tags only as fallback.
write(
    "frontend/miniapp-v0/lib/trend-settings.ts",
    """import type {
  ImageModel,
  PromptItem,
  ScenarioType,
  TrendGenerationSettings,
  VideoModel,
} from './types'

const SCENARIOS = new Set<ScenarioType>([
  'text',
  'imgtxt',
  'video',
  'avatar',
  'audio',
  'character',
])

function legacyTagValue(tags: string[], key: string): string {
  const normalizedKey = key.toLowerCase()
  for (const rawTag of tags) {
    const tag = String(rawTag || '').trim().toLowerCase()
    if (tag.startsWith(`${normalizedKey}:`)) return tag.slice(normalizedKey.length + 1)
    if (tag.startsWith(`${normalizedKey}-`)) return tag.slice(normalizedKey.length + 1)
  }
  return ''
}

function firstImageQuality(model?: ImageModel): string {
  if (!model) return 'basic'
  if (model.id === 'banana_pro' || model.id === 'banana_2') return '2K'
  return model.qualities?.[0] || 'basic'
}

function finiteNumber(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function isVideoTrendItem(
  trend: PromptItem,
  videoModels: VideoModel[],
): boolean {
  const settings = trend.generation_settings
  if (settings?.kind === 'video') return true
  const tags = new Set((trend.tags || []).map((tag) => String(tag).toLowerCase()))
  return (
    trend.category === 'video' ||
    tags.has('trend-video') ||
    videoModels.some((model) => model.id === trend.model)
  )
}

export function resolveTrendSettings(
  trend: PromptItem,
  imageModels: ImageModel[],
  videoModels: VideoModel[],
): TrendGenerationSettings {
  const stored = trend.generation_settings || ({} as Partial<TrendGenerationSettings>)
  const tags = trend.tags || []
  const video = isVideoTrendItem(trend, videoModels)

  if (!video) {
    const model =
      imageModels.find((item) => item.id === stored.model) ||
      imageModels.find((item) => item.id === trend.model) ||
      imageModels[0]
    const ratio =
      model?.ratios.includes(String(stored.ratio || ''))
        ? String(stored.ratio)
        : model?.ratios[0] || '1:1'
    const allowedQualities =
      model?.id === 'banana_pro' || model?.id === 'banana_2'
        ? ['1K', '2K', '4K']
        : model?.qualities || []
    const configuredQuality = String(stored.quality || '')
    const quality = allowedQualities.includes(configuredQuality)
      ? configuredQuality
      : firstImageQuality(model)
    const configuredCount = finiteNumber(stored.count)

    return {
      kind: 'image',
      user_input: 'photo',
      model: model?.id || String(stored.model || trend.model || 'banana_pro'),
      ratio,
      quality,
      count: Math.min(6, Math.max(1, Math.trunc(configuredCount || 1))),
      nsfw_checker: Boolean(stored.nsfw_checker),
      nsfw_enabled: Boolean(stored.nsfw_enabled),
    }
  }

  const model =
    videoModels.find((item) => item.id === stored.model) ||
    videoModels.find((item) => item.id === trend.model) ||
    videoModels.find((item) => item.supports.includes('imgtxt')) ||
    videoModels[0]
  const legacyScenario = legacyTagValue(tags, 'trend-scenario')
  const rawScenario = String(stored.scenario || legacyScenario || 'imgtxt') as ScenarioType
  const configuredScenario = SCENARIOS.has(rawScenario) ? rawScenario : 'imgtxt'
  const scenario = model?.supports.includes('imgtxt')
    ? 'imgtxt'
    : model?.supports.includes(configuredScenario)
      ? configuredScenario
      : model?.supports[0] || 'text'
  const ratio =
    model?.ratios.includes(String(stored.ratio || ''))
      ? String(stored.ratio)
      : model?.ratios[0] || '16:9'
  const legacyDuration = finiteNumber(legacyTagValue(tags, 'trend-duration'))
  const configuredDuration = finiteNumber(stored.duration) || legacyDuration
  const duration =
    configuredDuration && model?.durations.includes(configuredDuration)
      ? configuredDuration
      : model?.durations[0] || 5
  const imageGenerationType =
    model?.veo_generation_types?.find((value) => value.toUpperCase().includes('IMAGE')) ||
    model?.veo_generation_types?.[0] ||
    'IMAGE_2_VIDEO'

  return {
    kind: 'video',
    user_input: 'photo',
    model: model?.id || String(stored.model || trend.model || 'v3_pro'),
    scenario,
    ratio,
    duration,
    grok_mode: String(stored.grok_mode || model?.grok_modes?.[0] || 'normal'),
    grok_resolution: String(stored.grok_resolution || model?.grok_resolutions?.[0] || '480p'),
    veo_generation_type: String(stored.veo_generation_type || imageGenerationType),
    veo_translation: stored.veo_translation ?? true,
    veo_resolution: String(stored.veo_resolution || model?.veo_resolutions?.[0] || '720p'),
    veo_seed: finiteNumber(stored.veo_seed),
    veo_watermark: String(stored.veo_watermark || ''),
    kling_negative_prompt: String(stored.kling_negative_prompt || ''),
    kling_cfg_scale: finiteNumber(stored.kling_cfg_scale) ?? 0.5,
    omni_resolution: String(stored.omni_resolution || model?.omni_resolutions?.[0] || '720p'),
    omni_seed: finiteNumber(stored.omni_seed),
    omni_audio_ids: Array.isArray(stored.omni_audio_ids) ? stored.omni_audio_ids : [],
    omni_character_ids: Array.isArray(stored.omni_character_ids) ? stored.omni_character_ids : [],
    omni_base_voice: String(stored.omni_base_voice || model?.omni_base_voices?.[0] || 'achernar'),
    omni_voice_name: String(stored.omni_voice_name || ''),
    omni_voice_description: String(stored.omni_voice_description || ''),
    omni_example_dialogue: String(stored.omni_example_dialogue || ''),
    omni_character_name: String(stored.omni_character_name || ''),
    omni_character_audio_ids: Array.isArray(stored.omni_character_audio_ids)
      ? stored.omni_character_audio_ids
      : [],
  }
}
""",
)

write(
    "frontend/miniapp-v0/components/trend-runner-dialog.tsx",
    """'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { ImagePlus, Loader2, RefreshCcw, Sparkles } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { generateImage, generateVideo, uploadFile } from '@/lib/api'
import { resolveTrendSettings } from '@/lib/trend-settings'
import type { PromptItem, Task } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'

type RunnerPhase = 'idle' | 'uploading' | 'generating' | 'error'

interface TrendRunnerDialogProps {
  trend: PromptItem | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif', 'avif'])

export function TrendRunnerDialog({
  trend,
  open,
  onOpenChange,
}: TrendRunnerDialogProps) {
  const {
    state,
    addTask,
    setCredits,
    setTaskDetail,
    selectTask,
    addSavedReference,
  } = useApp()
  const inputRef = useRef<HTMLInputElement>(null)
  const previewRef = useRef<string>('')
  const [phase, setPhase] = useState<RunnerPhase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState('')

  const settings = useMemo(
    () =>
      trend
        ? resolveTrendSettings(trend, state.imageModels, state.videoModels)
        : null,
    [state.imageModels, state.videoModels, trend],
  )
  const busy = phase === 'uploading' || phase === 'generating'

  useEffect(() => {
    if (open) return
    setPhase('idle')
    setError(null)
    if (previewRef.current.startsWith('blob:')) {
      URL.revokeObjectURL(previewRef.current)
    }
    previewRef.current = ''
    setPreviewUrl('')
    if (inputRef.current) inputRef.current.value = ''
  }, [open])

  useEffect(
    () => () => {
      if (previewRef.current.startsWith('blob:')) {
        URL.revokeObjectURL(previewRef.current)
      }
    },
    [],
  )

  const runImageTrend = async (uploadedUrl: string): Promise<Task> => {
    if (!trend || !settings || settings.kind !== 'image') {
      throw new Error('Настройки фото-тренда недоступны')
    }

    let lastTask: Task | null = null
    let credits = state.user.credits
    const count = settings.count || 1
    for (let index = 0; index < count; index += 1) {
      const result = await generateImage({
        model: settings.model,
        ratio: settings.ratio,
        quality: settings.quality || 'basic',
        nsfwChecker: Boolean(settings.nsfw_checker),
        nsfwEnabled: Boolean(settings.nsfw_enabled),
        promptId: trend.id,
        sourceFeedGenId: null,
        prompt: trend.prompt_text,
        references: [uploadedUrl],
      })
      addTask(result.task)
      if (result.detail) setTaskDetail(result.detail)
      credits = result.credits
      lastTask = result.task
    }
    setCredits(credits)
    if (!lastTask) throw new Error('Не удалось создать задачу')
    return lastTask
  }

  const runVideoTrend = async (uploadedUrl: string): Promise<Task> => {
    if (!trend || !settings || settings.kind !== 'video') {
      throw new Error('Настройки видео-тренда недоступны')
    }
    if (settings.scenario !== 'imgtxt') {
      throw new Error('Этот видео-тренд нужно пересохранить в режиме «Фото + текст»')
    }

    const result = await generateVideo({
      model: settings.model,
      scenario: settings.scenario,
      ratio: settings.ratio,
      duration: settings.duration || 5,
      grokMode: settings.grok_mode,
      grokResolution: settings.grok_resolution,
      veoGenerationType: settings.veo_generation_type,
      veoTranslation: settings.veo_translation,
      veoResolution: settings.veo_resolution,
      veoSeed: settings.veo_seed,
      veoWatermark: settings.veo_watermark,
      klingNegativePrompt: settings.kling_negative_prompt,
      klingCfgScale: settings.kling_cfg_scale,
      omniResolution: settings.omni_resolution,
      omniSeed: settings.omni_seed,
      omniAudioIds: settings.omni_audio_ids,
      omniCharacterIds: settings.omni_character_ids,
      omniBaseVoice: settings.omni_base_voice,
      omniVoiceName: settings.omni_voice_name,
      omniVoiceDescription: settings.omni_voice_description,
      omniExampleDialogue: settings.omni_example_dialogue,
      omniCharacterName: settings.omni_character_name,
      omniCharacterAudioIds: settings.omni_character_audio_ids,
      prompt: trend.prompt_text,
      startImage: uploadedUrl,
      references: [],
      videoReferences: [],
      audioReference: null,
    })
    addTask(result.task)
    setCredits(result.credits)
    if (result.detail) setTaskDetail(result.detail)
    return result.task
  }

  const handlePhoto = async (file?: File) => {
    if (!file || !trend || !settings || busy) return
    const extension = file.name.split('.').pop()?.toLowerCase() || ''
    if (!file.type.startsWith('image/') && !IMAGE_EXTENSIONS.has(extension)) {
      setPhase('error')
      setError('Нужно загрузить фотографию')
      return
    }

    if (previewRef.current.startsWith('blob:')) {
      URL.revokeObjectURL(previewRef.current)
    }
    const localPreview = URL.createObjectURL(file)
    previewRef.current = localPreview
    setPreviewUrl(localPreview)
    setError(null)
    setPhase('uploading')

    try {
      const uploaded = await uploadFile('image_reference', file)
      addSavedReference(uploaded)
      setPhase('generating')
      const task =
        settings.kind === 'video'
          ? await runVideoTrend(uploaded.url)
          : await runImageTrend(uploaded.url)
      selectTask(task)
      onOpenChange(false)
    } catch (cause) {
      setPhase('error')
      setError(cause instanceof Error ? cause.message : 'Не удалось запустить тренд')
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!busy) onOpenChange(nextOpen)
      }}
    >
      <DialogContent className="max-w-lg border-border/60 bg-background p-4">
        <DialogTitle className="pr-8 font-serif text-lg">
          {trend?.title || 'Повторить тренд'}
        </DialogTitle>

        {trend?.preview_url ? (
          settings?.kind === 'video' ? (
            <video
              src={trend.preview_url}
              muted
              loop
              autoPlay
              playsInline
              className="max-h-[42vh] w-full rounded-2xl bg-black object-contain"
            />
          ) : (
            <img
              src={trend.preview_url}
              alt={trend.title}
              className="max-h-[42vh] w-full rounded-2xl object-contain"
            />
          )
        ) : null}

        <div className="rounded-2xl border border-gold/25 bg-gold/10 p-4 text-center">
          <Sparkles className="mx-auto h-6 w-6 text-gold" />
          <p className="mt-2 text-sm font-semibold text-foreground">
            Загрузите своё фото
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Модель, промпт, формат, качество и остальные параметры применятся автоматически.
          </p>
        </div>

        {previewUrl ? (
          <img
            src={previewUrl}
            alt="Загруженное фото"
            className="max-h-56 w-full rounded-2xl object-contain"
          />
        ) : null}

        <label className="relative flex min-h-28 cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border/70 bg-secondary/35 p-4 text-sm text-muted-foreground transition hover:border-gold/50 hover:text-foreground">
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/heic,image/heif,image/avif"
            className="absolute inset-0 cursor-pointer opacity-0"
            disabled={busy}
            onChange={(event) => void handlePhoto(event.target.files?.[0])}
          />
          {busy ? (
            <Loader2 className="h-7 w-7 animate-spin text-gold" />
          ) : phase === 'error' ? (
            <RefreshCcw className="h-7 w-7 text-gold" />
          ) : (
            <ImagePlus className="h-7 w-7 text-gold" />
          )}
          <span className="font-medium">
            {phase === 'uploading'
              ? 'Загружаю фото…'
              : phase === 'generating'
                ? 'Применяю тренд и запускаю…'
                : phase === 'error'
                  ? 'Выбрать другое фото'
                  : 'Выбрать фото'}
          </span>
        </label>

        {error ? (
          <p className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <Button
          type="button"
          variant="secondary"
          disabled={busy}
          onClick={() => onOpenChange(false)}
        >
          Закрыть
        </Button>
      </DialogContent>
    </Dialog>
  )
}
""",
)

# App context: trend deep links open the same one-photo runner.
replace_once(
    "frontend/miniapp-v0/lib/app-context.tsx",
    """PromptPreset, SavedReference, ScenarioType""",
    """PromptItem, PromptPreset, SavedReference, ScenarioType""",
)
replace_once(
    "frontend/miniapp-v0/lib/app-context.tsx",
    """  videoPromptPreset: VideoPromptPreset | null
  viewedProfileCode: string | null
""",
    """  videoPromptPreset: VideoPromptPreset | null
  trendToRun: PromptItem | null
  viewedProfileCode: string | null
""",
)
replace_once(
    "frontend/miniapp-v0/lib/app-context.tsx",
    """  setVideoPromptPreset: (preset: VideoPromptPreset | null) => void
}
""",
    """  setVideoPromptPreset: (preset: VideoPromptPreset | null) => void
  setTrendToRun: (trend: PromptItem | null) => void
}
""",
)
replace_once(
    "frontend/miniapp-v0/lib/app-context.tsx",
    """  const [videoPromptPreset, setVideoPromptPreset] = useState<VideoPromptPreset | null>(null)
  const [viewedProfileCode, setViewedProfileCode] = useState<string | null>(null)
""",
    """  const [videoPromptPreset, setVideoPromptPreset] = useState<VideoPromptPreset | null>(null)
  const [trendToRun, setTrendToRun] = useState<PromptItem | null>(null)
  const [viewedProfileCode, setViewedProfileCode] = useState<string | null>(null)
""",
)
replace_once(
    "frontend/miniapp-v0/lib/app-context.tsx",
    """    setVideoPromptPreset(null)
    setViewedProfileCode(null)
""",
    """    setVideoPromptPreset(null)
    setTrendToRun(null)
    setViewedProfileCode(null)
""",
)
replace_once(
    "frontend/miniapp-v0/lib/app-context.tsx",
    """          const isVideoTrend =
            prompt.category === 'video' ||
            (prompt.tags || []).some((tag) => String(tag).toLowerCase() === 'trend-video') ||
            state.videoModels.some((model) => model.id === prompt.model)

          if (isVideoTrend) {
""",
    """          const isTrend = (prompt.tags || []).some(
            (tag) => String(tag).toLowerCase() === 'trend',
          )
          if (isTrend) {
            setTrendToRun(prompt)
            setActiveTabState(5)
            return
          }

          const isVideoTrend =
            prompt.category === 'video' ||
            (prompt.tags || []).some((tag) => String(tag).toLowerCase() === 'trend-video') ||
            state.videoModels.some((model) => model.id === prompt.model)

          if (isVideoTrend) {
""",
)
replace_once(
    "frontend/miniapp-v0/lib/app-context.tsx",
    """        videoPromptPreset,
        viewedProfileCode,
""",
    """        videoPromptPreset,
        trendToRun,
        viewedProfileCode,
""",
)
replace_once(
    "frontend/miniapp-v0/lib/app-context.tsx",
    """        setVideoPromptPreset,
      }}
""",
    """        setVideoPromptPreset,
        setTrendToRun,
      }}
""",
)

# Trends: direct one-photo runner; only admins see configuration while creating a trend.
replace_once(
    "frontend/miniapp-v0/components/tabs/trends-tab.tsx",
    """import { deactivatePrompt, fetchPromptLink, fetchPrompts, submitPrompt, uploadFile } from '@/lib/api'
""",
    """import { deactivatePrompt, fetchPromptLink, fetchPrompts, submitPrompt, uploadFile } from '@/lib/api'
import { TrendRunnerDialog } from '@/components/trend-runner-dialog'
""",
)
replace_once(
    "frontend/miniapp-v0/components/tabs/trends-tab.tsx",
    """  const {
    state,
    setActiveTab,
    setPromptPreset,
    setVideoPromptPreset,
  } = useApp()
""",
    """  const { state, trendToRun, setTrendToRun } = useApp()
""",
)
replace_once(
    "frontend/miniapp-v0/components/tabs/trends-tab.tsx",
    """  const [videoDuration, setVideoDuration] = useState(5)
  const [previewUrl, setPreviewUrl] = useState('')
""",
    """  const [videoDuration, setVideoDuration] = useState(5)
  const [trendRatio, setTrendRatio] = useState('1:1')
  const [imageQuality, setImageQuality] = useState('2K')
  const [previewUrl, setPreviewUrl] = useState('')
""",
)
replace_once(
    "frontend/miniapp-v0/components/tabs/trends-tab.tsx",
    """  const availableModels = trendKind === 'video' ? state.videoModels : state.imageModels
""",
    """  const availableModels = trendKind === 'video'
    ? state.videoModels.filter((item) => item.supports.includes('imgtxt'))
    : state.imageModels
  const selectedTrendImageModel = state.imageModels.find((item) => item.id === model)
  const selectedTrendVideoModel = state.videoModels.find((item) => item.id === model)
  const trendImageQualities =
    selectedTrendImageModel?.id === 'banana_pro' || selectedTrendImageModel?.id === 'banana_2'
      ? ['1K', '2K', '4K']
      : selectedTrendImageModel?.qualities?.length
        ? selectedTrendImageModel.qualities
        : ['basic']
""",
)
replace_once(
    "frontend/miniapp-v0/components/tabs/trends-tab.tsx",
    """  }, [model, state.videoModels, trendKind])

  const changeTrendKind = (nextKind: TrendKind) => {
""",
    """  }, [model, state.videoModels, trendKind])

  useEffect(() => {
    const selectedModel = trendKind === 'video'
      ? state.videoModels.find((item) => item.id === model)
      : state.imageModels.find((item) => item.id === model)
    const ratios = selectedModel?.ratios || []
    if (ratios.length && !ratios.includes(trendRatio)) {
      setTrendRatio(ratios[0])
    }
    if (trendKind === 'image' && !trendImageQualities.includes(imageQuality)) {
      setImageQuality(trendImageQualities[0] || 'basic')
    }
  }, [
    imageQuality,
    model,
    state.imageModels,
    state.videoModels,
    trendImageQualities,
    trendKind,
    trendRatio,
  ])

  const changeTrendKind = (nextKind: TrendKind) => {
""",
)
replace_once(
    "frontend/miniapp-v0/components/tabs/trends-tab.tsx",
    """    setVideoDuration(5)
    setPreviewUrl('')
""",
    """    setVideoDuration(5)
    setTrendRatio('1:1')
    setImageQuality('2K')
    setPreviewUrl('')
""",
)
old_apply = """  const applyTrend = (trend: PromptItem) => {
    if (isVideoTrend(trend)) {
      const videoModel = state.videoModels.find((item) => item.id === trend.model)
      const scenarioTag = (trend.tags || []).find((tag) => String(tag).startsWith('trend-scenario:'))
      const durationTag = (trend.tags || []).find((tag) => String(tag).startsWith('trend-duration:'))
      const configuredScenario = String(scenarioTag || '').split(':')[1] as ScenarioType
      const scenario = videoModel?.supports.includes(configuredScenario)
        ? configuredScenario
        : videoModel?.supports.includes('imgtxt') ? 'imgtxt' : videoModel?.supports[0] || 'text'
      setVideoPromptPreset({
        title: trend.title,
        prompt: trend.prompt_text,
        model: videoModel?.id || state.videoModels[0]?.id || 'v3_pro',
        scenario,
        duration: Number(String(durationTag || '').split(':')[1]) || videoModel?.durations[0] || 5,
      })
      setActiveTab(2)
      return
    }

    setPromptPreset({
      promptId: trend.id,
      title: trend.title,
      prompt: trend.prompt_text,
      model: trend.model || state.imageModels[0]?.id || 'banana_pro',
    })
    setActiveTab(1)
  }
"""
replace_once(
    "frontend/miniapp-v0/components/tabs/trends-tab.tsx",
    old_apply,
    """  const applyTrend = (trend: PromptItem) => {
    setTrendToRun(trend)
  }
""",
)
replace_once(
    "frontend/miniapp-v0/components/tabs/trends-tab.tsx",
    """      const created = await submitPrompt({
""",
    """      const generationSettings = trendKind === 'video'
        ? {
            kind: 'video' as const,
            user_input: 'photo' as const,
            model,
            scenario: 'imgtxt' as const,
            ratio: trendRatio,
            duration: videoDuration,
            grok_mode: selectedTrendVideoModel?.grok_modes?.[0] || 'normal',
            grok_resolution: selectedTrendVideoModel?.grok_resolutions?.[0] || '480p',
            veo_generation_type:
              selectedTrendVideoModel?.veo_generation_types?.find((value) =>
                value.toUpperCase().includes('IMAGE'),
              ) ||
              selectedTrendVideoModel?.veo_generation_types?.[0] ||
              'IMAGE_2_VIDEO',
            veo_translation: true,
            veo_resolution: selectedTrendVideoModel?.veo_resolutions?.[0] || '720p',
            veo_seed: null,
            veo_watermark: '',
            kling_negative_prompt: '',
            kling_cfg_scale: 0.5,
            omni_resolution: selectedTrendVideoModel?.omni_resolutions?.[0] || '720p',
            omni_seed: null,
            omni_audio_ids: [],
            omni_character_ids: [],
            omni_base_voice: selectedTrendVideoModel?.omni_base_voices?.[0] || 'achernar',
            omni_voice_name: '',
            omni_voice_description: '',
            omni_example_dialogue: '',
            omni_character_name: '',
            omni_character_audio_ids: [],
          }
        : {
            kind: 'image' as const,
            user_input: 'photo' as const,
            model,
            ratio: trendRatio,
            quality: imageQuality,
            count: 1,
            nsfw_checker: false,
            nsfw_enabled: false,
          }

      const created = await submitPrompt({
""",
)
replace_once(
    "frontend/miniapp-v0/components/tabs/trends-tab.tsx",
    """        model,
        tags: trendKind === 'video'
          ? [TREND_TAG, VIDEO_TREND_TAG, `trend-scenario:${videoScenario}`, `trend-duration:${videoDuration}`]
          : [TREND_TAG],
""",
    """        model,
        tags: trendKind === 'video'
          ? [TREND_TAG, VIDEO_TREND_TAG]
          : [TREND_TAG],
        generationSettings,
""",
)
old_admin_block = """          {trendKind === 'video' ? (
            <div className="grid grid-cols-2 gap-3">
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Режим повтора</span>
                <select value={videoScenario} onChange={(event) => setVideoScenario(event.target.value as ScenarioType)} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {(state.videoModels.find((item) => item.id === model)?.supports || ['text']).map((scenario) => (
                    <option key={scenario} value={scenario}>{scenario === 'imgtxt' ? 'Фото + текст' : scenario === 'text' ? 'Текст → видео' : scenario}</option>
                  ))}
                </select>
              </label>
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Длительность</span>
                <select value={videoDuration} onChange={(event) => setVideoDuration(Number(event.target.value))} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {(state.videoModels.find((item) => item.id === model)?.durations || [5]).map((duration) => (
                    <option key={duration} value={duration}>{duration} сек</option>
                  ))}
                </select>
              </label>
            </div>
          ) : null}
"""
new_admin_block = """          {trendKind === 'video' ? (
            <div className="grid grid-cols-2 gap-3">
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Формат</span>
                <select value={trendRatio} onChange={(event) => setTrendRatio(event.target.value)} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {(selectedTrendVideoModel?.ratios || ['16:9']).map((ratio) => (
                    <option key={ratio} value={ratio}>{ratio}</option>
                  ))}
                </select>
              </label>
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Длительность</span>
                <select value={videoDuration} onChange={(event) => setVideoDuration(Number(event.target.value))} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {(selectedTrendVideoModel?.durations || [5]).map((duration) => (
                    <option key={duration} value={duration}>{duration} сек</option>
                  ))}
                </select>
              </label>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Формат</span>
                <select value={trendRatio} onChange={(event) => setTrendRatio(event.target.value)} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {(selectedTrendImageModel?.ratios || ['1:1']).map((ratio) => (
                    <option key={ratio} value={ratio}>{ratio}</option>
                  ))}
                </select>
              </label>
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Качество</span>
                <select value={imageQuality} onChange={(event) => setImageQuality(event.target.value)} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {trendImageQualities.map((quality) => (
                    <option key={quality} value={quality}>{quality}</option>
                  ))}
                </select>
              </label>
            </div>
          )}
"""
replace_once(
    "frontend/miniapp-v0/components/tabs/trends-tab.tsx",
    old_admin_block,
    new_admin_block,
)
replace_once(
    "frontend/miniapp-v0/components/tabs/trends-tab.tsx",
    """      <Dialog open={Boolean(previewTrend)} onOpenChange={(open) => { if (!open) setPreviewTrend(null) }}>
""",
    """      <TrendRunnerDialog
        trend={trendToRun}
        open={Boolean(trendToRun)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setTrendToRun(null)
        }}
      />

      <Dialog open={Boolean(previewTrend)} onOpenChange={(open) => { if (!open) setPreviewTrend(null) }}>
""",
)

write(
    "tests/test_trend_one_tap_contract.py",
    """from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_trend_settings_are_persisted_as_structured_json() -> None:
    database = read("bot/database.py")
    miniapp = read("bot/miniapp.py")

    assert "generation_settings TEXT DEFAULT '{}'" in database
    assert '"generation_settings": prompt.generation_settings or {}' in database
    assert "generation_settings=generation_settings" in miniapp
    assert "if not config.is_admin(telegram_id):" in miniapp


def test_trend_runner_only_requests_a_photo_and_autostarts() -> None:
    runner = read("frontend/miniapp-v0/components/trend-runner-dialog.tsx")

    assert 'type="file"' in runner
    assert "void handlePhoto(event.target.files?.[0])" in runner
    assert "await uploadFile('image_reference', file)" in runner
    assert "await runVideoTrend(uploaded.url)" in runner
    assert "await runImageTrend(uploaded.url)" in runner
    assert "ModelSelect" not in runner
    assert "RatioSelect" not in runner
    assert "QualitySelect" not in runner
    assert "ScenarioSelect" not in runner
    assert "DurationSelect" not in runner


def test_trend_card_and_deep_link_open_the_same_runner() -> None:
    trends = read("frontend/miniapp-v0/components/tabs/trends-tab.tsx")
    context = read("frontend/miniapp-v0/lib/app-context.tsx")

    assert "setTrendToRun(trend)" in trends
    assert "trend={trendToRun}" in trends
    assert "setTrendToRun(prompt)" in context
    assert "setActiveTabState(5)" in context


def test_admin_snapshot_contains_every_generation_parameter_used_by_runner() -> None:
    trends = read("frontend/miniapp-v0/components/tabs/trends-tab.tsx")
    resolver = read("frontend/miniapp-v0/lib/trend-settings.ts")

    for key in (
        "model",
        "ratio",
        "quality",
        "count",
        "scenario",
        "duration",
        "grok_mode",
        "grok_resolution",
        "veo_generation_type",
        "veo_translation",
        "veo_resolution",
        "veo_seed",
        "veo_watermark",
        "kling_negative_prompt",
        "kling_cfg_scale",
        "omni_resolution",
        "omni_seed",
        "omni_audio_ids",
        "omni_character_ids",
        "omni_base_voice",
        "omni_voice_name",
        "omni_voice_description",
        "omni_example_dialogue",
        "omni_character_name",
        "omni_character_audio_ids",
    ):
        assert key in trends or key in resolver

    assert "trend-scenario:" not in trends
    assert "trend-duration:" not in trends
""",
)

# The codemod is temporary and must not remain in the feature branch.
Path(__file__).unlink()
