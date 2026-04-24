'use client'

import { useState, useMemo, useEffect } from 'react'
import type { VideoModel, UploadedFile, ScenarioType } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { ModelSelect } from './model-select'
import { RatioSelect } from './ratio-select'
import { UploadArea } from './upload-area'
import { ScenarioSelect } from './scenario-select'
import { DurationSelect } from './duration-select'
import { Banana, Clapperboard, Loader2, AlertCircle } from 'lucide-react'

interface VideoGeneratorFormProps {
  models: VideoModel[]
  onSubmit: (data: {
    model: string
    scenario: ScenarioType
    ratio: string
    duration: number
    grokMode: string
    veoGenerationType: string
    veoTranslation: boolean
    veoResolution: string
    veoSeed: number | null
    veoWatermark: string
    klingNegativePrompt: string
    klingCfgScale: number
    prompt: string
    startImage: string | null
    references: string[]
    videoReferences: string[]
  }) => Promise<void>
  onUploadImageReference?: (file: File) => Promise<UploadedFile>
  onUploadVideoReference?: (file: File) => Promise<UploadedFile>
  isSubmitting: boolean
  credits: number
}

export function VideoGeneratorForm({ 
  models, 
  onSubmit, 
  onUploadImageReference,
  onUploadVideoReference,
  isSubmitting,
  credits,
}: VideoGeneratorFormProps) {
  const [selectedModel, setSelectedModel] = useState(models[0]?.id || '')
  const [selectedScenario, setSelectedScenario] = useState<ScenarioType>('text')
  const [selectedRatio, setSelectedRatio] = useState('16:9')
  const [selectedDuration, setSelectedDuration] = useState(5)
  const [grokMode, setGrokMode] = useState('normal')
  const [veoGenerationType, setVeoGenerationType] = useState('TEXT_2_VIDEO')
  const [veoTranslation, setVeoTranslation] = useState(true)
  const [veoResolution, setVeoResolution] = useState('720p')
  const [veoSeed, setVeoSeed] = useState('')
  const [veoWatermark, setVeoWatermark] = useState('')
  const [klingNegativePrompt, setKlingNegativePrompt] = useState('')
  const [klingCfgScale, setKlingCfgScale] = useState(0.5)
  const [prompt, setPrompt] = useState('')
  const [startImage, setStartImage] = useState<UploadedFile[]>([])
  const [photoReferences, setPhotoReferences] = useState<UploadedFile[]>([])
  const [videoReferences, setVideoReferences] = useState<UploadedFile[]>([])

  const model = useMemo(() => models.find(m => m.id === selectedModel), [models, selectedModel])
  
  const cost = model?.costs[selectedDuration.toString()] || 5
  const canAfford = credits >= cost
  
  // Check if scenario is supported
  const scenarioSupported = model?.supports.includes(selectedScenario) ?? false
  
  // Validation
  const needsStartImage = selectedScenario === 'imgtxt' && startImage.length === 0
  const needsVideoRef = selectedScenario === 'video' && videoReferences.length === 0
  
  const isValid = prompt.trim().length > 0 && 
    canAfford && 
    scenarioSupported && 
    !needsStartImage && 
    !needsVideoRef

  // Reset scenario if not supported
  useEffect(() => {
    if (model && !model.supports.includes(selectedScenario)) {
      setSelectedScenario(model.supports[0] || 'text')
    }
  }, [model, selectedScenario])

  useEffect(() => {
    if (model && !model.ratios.includes(selectedRatio)) {
      setSelectedRatio(model.ratios[0] || '16:9')
    }
  }, [model, selectedRatio])

  // Reset duration if not available
  useEffect(() => {
    if (model && !model.durations.includes(selectedDuration)) {
      setSelectedDuration(model.durations[0] || 5)
    }
  }, [model, selectedDuration])

  useEffect(() => {
    if (!model) return
    if (model.grok_modes?.length && !model.grok_modes.includes(grokMode)) {
      setGrokMode(model.grok_modes[0])
    }
    if (model.veo_generation_types?.length && !model.veo_generation_types.includes(veoGenerationType)) {
      setVeoGenerationType(model.veo_generation_types[0])
    }
    if (model.veo_resolutions?.length && !model.veo_resolutions.includes(veoResolution)) {
      setVeoResolution(model.veo_resolutions[0])
    }
    if (!model.supports_translation) setVeoTranslation(true)
    if (!model.supports_watermark) setVeoWatermark('')
    if (!model.supports_seed) setVeoSeed('')
    if (!model.supports_negative_prompt) setKlingNegativePrompt('')
    if (!model.supports_cfg_scale) setKlingCfgScale(0.5)
  }, [model, grokMode, veoGenerationType, veoResolution])

  const handleSubmit = async () => {
    if (!isValid) return
    await onSubmit({
      model: selectedModel,
      scenario: selectedScenario,
      ratio: selectedRatio,
      duration: selectedDuration,
      grokMode,
      veoGenerationType,
      veoTranslation,
      veoResolution,
      veoSeed: veoSeed.trim() ? Number(veoSeed) : null,
      veoWatermark,
      klingNegativePrompt,
      klingCfgScale,
      prompt,
      startImage: startImage[0]?.url || null,
      references: photoReferences.map(r => r.url),
      videoReferences: videoReferences.map(r => r.url),
    })
    setPrompt('')
    setStartImage([])
    setPhotoReferences([])
    setVideoReferences([])
  }

  return (
    <div className="space-y-4">
      <div className="glass rounded-2xl border border-cyan/20 p-4 space-y-4">
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">Модель</label>
          <ModelSelect
            models={models.map(m => ({
              id: m.id,
              label: m.label,
              description: m.description,
              cost: m.costs[selectedDuration.toString()] || Object.values(m.costs)[0] || 0,
            }))}
            value={selectedModel}
            onChange={setSelectedModel}
          />
        </div>

        <div className="rounded-2xl border border-cyan/20 bg-cyan/5 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
            <p className="text-sm font-medium text-foreground">{model?.label}</p>
            <p className="text-xs text-muted-foreground mt-1">{model?.description}</p>
          </div>
          <div className="rounded-full border border-gold/20 bg-gold/10 px-3 py-1 text-xs text-gold">
              {model?.durations.join(' / ')} сек
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {(model?.supports || []).map((scenario) => (
              <span
                key={scenario}
                className="rounded-full border border-border/50 bg-background/40 px-3 py-1 text-xs text-secondary-foreground"
              >
                {scenario === 'text' ? 'Текст → Видео' : scenario === 'imgtxt' ? 'Фото + Текст' : 'Видео + Текст'}
              </span>
            ))}
            {model?.grok_modes?.length ? (
              <span className="rounded-full border border-border/50 bg-background/40 px-3 py-1 text-xs text-secondary-foreground">
                Grok modes: {model.grok_modes.join(' / ')}
              </span>
            ) : null}
            {model?.supports_negative_prompt ? (
              <span className="rounded-full border border-border/50 bg-background/40 px-3 py-1 text-xs text-secondary-foreground">
                Negative + CFG
              </span>
            ) : null}
            {model?.veo_generation_types?.length ? (
              <span className="rounded-full border border-border/50 bg-background/40 px-3 py-1 text-xs text-secondary-foreground">
                Veo controls
              </span>
            ) : null}
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">Сценарий</label>
          <ScenarioSelect
            scenarios={model?.supports || ['text']}
            value={selectedScenario}
            onChange={setSelectedScenario}
          />
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Формат</label>
            <RatioSelect
              ratios={model?.ratios || ['16:9']}
              value={selectedRatio}
              onChange={setSelectedRatio}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Длительность</label>
            <DurationSelect
              durations={model?.durations || [5]}
              value={selectedDuration}
              onChange={setSelectedDuration}
              costs={model?.costs || {}}
            />
          </div>
        </div>

        {model?.grok_modes?.length ? (
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Режим Grok</label>
            <div className="flex gap-2">
              {model.grok_modes.map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setGrokMode(mode)}
                  className={cn(
                    'flex-1 rounded-xl border px-3 py-2 text-xs font-medium transition-all duration-200',
                    grokMode === mode
                      ? 'border-cyan/50 bg-cyan/15 text-cyan'
                      : 'border-border/50 bg-secondary/50 text-muted-foreground hover:bg-secondary hover:text-foreground'
                  )}
                >
                  {mode}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {model?.supports_negative_prompt || model?.supports_cfg_scale ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {model.supports_negative_prompt ? (
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Negative prompt</label>
                <Input
                  value={klingNegativePrompt}
                  onChange={(e) => setKlingNegativePrompt(e.target.value)}
                  placeholder="Что нужно исключить из кадра"
                  className="bg-secondary/50 border-border/50"
                />
              </div>
            ) : null}
            {model.supports_cfg_scale ? (
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">CFG scale</label>
                <Input
                  type="number"
                  min="0"
                  max="1"
                  step="0.1"
                  value={klingCfgScale}
                  onChange={(e) => setKlingCfgScale(Number(e.target.value))}
                  className="bg-secondary/50 border-border/50"
                />
              </div>
            ) : null}
          </div>
        ) : null}

        {model?.veo_generation_types?.length ? (
          <div className="space-y-4 rounded-2xl border border-cyan/20 bg-cyan/5 p-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Veo режим</label>
              <div className="flex flex-wrap gap-2">
                {model.veo_generation_types.map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setVeoGenerationType(mode)}
                    className={cn(
                      'rounded-xl border px-3 py-2 text-xs font-medium transition-all duration-200',
                      veoGenerationType === mode
                        ? 'border-cyan/50 bg-cyan/15 text-cyan'
                        : 'border-border/50 bg-secondary/40 text-muted-foreground hover:bg-secondary hover:text-foreground'
                    )}
                  >
                    {mode === 'TEXT_2_VIDEO'
                      ? 'Текст → Видео'
                      : mode === 'FIRST_AND_LAST_FRAMES_2_VIDEO'
                        ? 'Кадры → Видео'
                        : 'Референсы → Видео'}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Resolution</label>
                <div className="flex gap-2">
                  {(model.veo_resolutions || ['720p']).map((resolution) => (
                    <button
                      key={resolution}
                      type="button"
                      onClick={() => setVeoResolution(resolution)}
                      className={cn(
                        'flex-1 rounded-xl border px-3 py-2 text-xs font-medium transition-all duration-200',
                        veoResolution === resolution
                          ? 'border-cyan/50 bg-cyan/15 text-cyan'
                          : 'border-border/50 bg-secondary/40 text-muted-foreground hover:bg-secondary hover:text-foreground'
                      )}
                    >
                      {resolution}
                    </button>
                  ))}
                </div>
              </div>

              {model.supports_translation ? (
                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Перевод prompt</label>
                  <button
                    type="button"
                    onClick={() => setVeoTranslation((prev) => !prev)}
                    className={cn(
                      'w-full rounded-xl border px-4 py-3 text-left text-sm transition-all duration-200',
                      veoTranslation
                        ? 'border-cyan/40 bg-cyan/10 text-cyan'
                        : 'border-border/50 bg-secondary/40 text-muted-foreground hover:bg-secondary/60 hover:text-foreground'
                    )}
                  >
                    {veoTranslation ? 'Перевод включён' : 'Перевод выключен'}
                  </button>
                </div>
              ) : null}
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              {model.supports_seed ? (
                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Seed</label>
                  <Input
                    type="number"
                    inputMode="numeric"
                    value={veoSeed}
                    onChange={(e) => setVeoSeed(e.target.value)}
                    placeholder="Например 42"
                    className="bg-secondary/50 border-border/50"
                  />
                </div>
              ) : null}
              {model.supports_watermark ? (
                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Watermark</label>
                  <Input
                    value={veoWatermark}
                    onChange={(e) => setVeoWatermark(e.target.value)}
                    placeholder="Текст для watermark"
                    className="bg-secondary/50 border-border/50"
                  />
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {selectedScenario === 'imgtxt' && (
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              Стартовое изображение
              <span className="text-destructive ml-1">*</span>
            </label>
            <UploadArea
              files={startImage}
              onFilesChange={setStartImage}
              maxFiles={1}
              accept="image/*"
              required
              onUpload={onUploadImageReference}
            />
          </div>
        )}

        {selectedScenario === 'video' && (
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              Видео-референсы
              <span className="text-destructive ml-1">*</span>
            </label>
          <UploadArea
            files={videoReferences}
            onFilesChange={setVideoReferences}
            maxFiles={model?.max_video_references || 5}
            accept="video/*"
            required
            onUpload={onUploadVideoReference}
          />
          </div>
        )}

        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">
            Фото-референсы
            <span className="text-xs text-muted-foreground ml-2">(опционально)</span>
          </label>
          <UploadArea
            files={photoReferences}
            onFilesChange={setPhotoReferences}
            maxFiles={model?.max_image_references || 8}
            accept="image/*"
            onUpload={onUploadImageReference}
          />
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">Промпт</label>
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Опишите движение камеры, сцену, свет, ритм, физику движения и желаемый cinematic-эффект..."
            className={cn(
              "min-h-[140px] resize-none",
              "bg-secondary/50 border-border/50",
              "focus:border-cyan/50 focus:ring-cyan/20",
              "placeholder:text-muted-foreground/50"
            )}
          />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {scenarioSupported
                ? 'Сценарий поддерживается выбранной моделью'
                : 'Выбранный сценарий для модели недоступен'}
            </span>
            <span>{prompt.length} симв.</span>
          </div>
        </div>
      </div>

      <div className="glass rounded-2xl p-4 space-y-4 border border-cyan/20">
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-xl bg-secondary/40 p-3">
            <p className="text-muted-foreground mb-1">Сводка</p>
            <p className="text-foreground font-medium">{selectedScenario === 'text' ? 'Текст → Видео' : selectedScenario === 'imgtxt' ? 'Фото + Текст' : 'Видео + Текст'}</p>
            <p className="text-muted-foreground mt-1">{selectedRatio} • {selectedDuration} сек.</p>
          </div>
          <div className="rounded-xl bg-secondary/40 p-3">
            <p className="text-muted-foreground mb-1">Референсы</p>
            <p className="text-foreground font-medium">
              {startImage.length + photoReferences.length + videoReferences.length}
            </p>
            <p className="text-muted-foreground mt-1">
              {model?.grok_modes?.length
                ? `Grok: ${grokMode}`
                : model?.veo_generation_types?.length
                  ? `Veo: ${veoGenerationType}`
                  : selectedScenario === 'video'
                    ? 'Видео-режим активен'
                    : 'Фото-референсы опциональны'}
            </p>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <span className="text-sm text-muted-foreground">Стоимость</span>
            <p className="text-xs text-muted-foreground/70">
              {selectedDuration} сек. • {selectedRatio}
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            <Banana className="w-4 h-4 text-gold" />
            <span className="text-lg font-semibold text-gold">{cost}</span>
          </div>
        </div>

        {!canAfford && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-destructive/10 border border-destructive/30">
            <AlertCircle className="w-4 h-4 text-destructive flex-shrink-0" />
            <p className="text-xs text-destructive">
              Недостаточно бананов. Пополните баланс.
            </p>
          </div>
        )}

        {needsStartImage && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-cyan/10 border border-cyan/30">
            <AlertCircle className="w-4 h-4 text-cyan flex-shrink-0" />
            <p className="text-xs text-cyan">
              Загрузите стартовое изображение
            </p>
          </div>
        )}

        {needsVideoRef && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-cyan/10 border border-cyan/30">
            <AlertCircle className="w-4 h-4 text-cyan flex-shrink-0" />
            <p className="text-xs text-cyan">
              Загрузите видео-референс
            </p>
          </div>
        )}

        <Button
          onClick={handleSubmit}
          disabled={!isValid || isSubmitting}
          className={cn(
            "w-full h-12 text-base font-semibold",
            "bg-cyan hover:bg-cyan/90 text-background",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-5 h-5 mr-2 animate-spin" />
              Запускаю...
            </>
          ) : (
            <>
              <Clapperboard className="w-5 h-5 mr-2" />
              Запустить видео
            </>
          )}
        </Button>
      </div>
    </div>
  )
}
