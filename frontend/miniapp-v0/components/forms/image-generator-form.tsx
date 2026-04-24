'use client'

import { useState, useMemo, useEffect } from 'react'
import type { ImageModel, UploadedFile } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ModelSelect } from './model-select'
import { RatioSelect } from './ratio-select'
import { QualitySelect } from './quality-select'
import { UploadArea } from './upload-area'
import { Banana, Sparkles, Loader2, AlertCircle } from 'lucide-react'

interface ImageGeneratorFormProps {
  models: ImageModel[]
  onSubmit: (data: {
    model: string
    ratio: string
    quality: string
    count: number
    nsfwChecker: boolean
    nsfwEnabled: boolean
    prompt: string
    references: string[]
  }) => Promise<void>
  onUploadReference?: (file: File) => Promise<UploadedFile>
  isSubmitting: boolean
  credits: number
}

export function ImageGeneratorForm({ 
  models, 
  onSubmit, 
  onUploadReference,
  isSubmitting,
  credits,
}: ImageGeneratorFormProps) {
  const [selectedModel, setSelectedModel] = useState(models[0]?.id || '')
  const [selectedRatio, setSelectedRatio] = useState('1:1')
  const [selectedQuality, setSelectedQuality] = useState('basic')
  const [selectedCount, setSelectedCount] = useState(1)
  const [nsfwChecker, setNsfwChecker] = useState(false)
  const [nsfwEnabled, setNsfwEnabled] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [references, setReferences] = useState<UploadedFile[]>([])

  const model = useMemo(() => models.find(m => m.id === selectedModel), [models, selectedModel])
  
  const cost = (model?.cost || 0) * selectedCount
  const canAfford = credits >= cost
  const needsReference = model?.requires_reference && references.length === 0
  const isValid = prompt.trim().length > 0 && canAfford && !needsReference

  useEffect(() => {
    if (!model) return
    if (!model.ratios.includes(selectedRatio)) {
      setSelectedRatio(model.ratios[0] || '1:1')
    }
    if (model.qualities?.length && !model.qualities.includes(selectedQuality)) {
      setSelectedQuality(model.qualities[0])
    }
    if (!(model.supports_nsfw_checker || model.id === 'seedream_edit' || model.id === 'flux_pro')) {
      setNsfwChecker(false)
    }
    if (!(model.supports_nsfw_mode || model.id === 'grok_imagine_i2i')) {
      setNsfwEnabled(false)
    }
  }, [model, selectedQuality, selectedRatio])

  const handleSubmit = async () => {
    if (!isValid) return
    await onSubmit({
      model: selectedModel,
      ratio: selectedRatio,
      quality: selectedQuality,
      count: selectedCount,
      nsfwChecker,
      nsfwEnabled,
      prompt,
      references: references.map(r => r.url),
    })
    setPrompt('')
    setReferences([])
  }

  return (
    <div className="space-y-4">
      <div className="glass rounded-2xl border border-border/50 p-4 space-y-4">
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">Модель</label>
          <ModelSelect
            models={models.map(m => ({
              id: m.id,
              label: m.label,
              description: m.description,
              cost: m.cost,
            }))}
            value={selectedModel}
            onChange={setSelectedModel}
          />
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Формат</label>
            <RatioSelect
              ratios={model?.ratios || ['1:1']}
              value={selectedRatio}
              onChange={setSelectedRatio}
            />
          </div>
          {model?.qualities?.length ? (
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Качество</label>
              <QualitySelect
                qualities={model.qualities}
                value={selectedQuality}
                onChange={setSelectedQuality}
              />
            </div>
          ) : (
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Режим</label>
              <div className="rounded-xl border border-border/50 bg-secondary/40 px-4 py-3 text-sm text-muted-foreground">
                Стандартный режим модели
              </div>
            </div>
          )}
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Количество</label>
            <div className="flex flex-wrap gap-2">
              {[1, 2, 4, 6].map((count) => (
                <button
                  key={count}
                  type="button"
                  onClick={() => setSelectedCount(count)}
                  className={cn(
                    "rounded-lg border px-3 py-2 text-xs font-medium transition-all duration-200",
                    selectedCount === count
                      ? "border-gold/50 bg-gold/15 text-gold"
                      : "border-border/50 bg-secondary/50 text-muted-foreground hover:bg-secondary hover:text-foreground"
                  )}
                >
                  {count}x
                </button>
              ))}
            </div>
          </div>

          {(model?.supports_nsfw_checker || model?.id === 'seedream_edit' || model?.id === 'flux_pro') && (
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Фильтр контента</label>
              <button
                type="button"
                onClick={() => setNsfwChecker((prev) => !prev)}
                className={cn(
                  "w-full rounded-xl border px-4 py-3 text-left text-sm transition-all duration-200",
                  nsfwChecker
                    ? "border-cyan/40 bg-cyan/10 text-cyan"
                    : "border-border/50 bg-secondary/40 text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
                )}
              >
                {nsfwChecker ? 'NSFW checker включён' : 'NSFW checker выключен'}
              </button>
            </div>
          )}
        </div>

        {(model?.supports_nsfw_mode || model?.id === 'grok_imagine_i2i') && (
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">NSFW режим</label>
            <button
              type="button"
              onClick={() => setNsfwEnabled((prev) => !prev)}
              className={cn(
                "w-full rounded-xl border px-4 py-3 text-left text-sm transition-all duration-200",
                nsfwEnabled
                  ? "border-cyan/40 bg-cyan/10 text-cyan"
                  : "border-border/50 bg-secondary/40 text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
              )}
            >
              {nsfwEnabled ? 'NSFW режим включён' : 'NSFW режим выключен'}
            </button>
          </div>
        )}

        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-foreground">{model?.label}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {model?.description}
              </p>
            </div>
            <div className="rounded-full border border-cyan/20 bg-cyan/10 px-3 py-1 text-xs text-cyan">
              До {model?.max_references || 0} референсов
            </div>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-xl bg-background/40 px-3 py-2 text-muted-foreground">
              Режим: <span className="text-foreground">{model?.requires_reference ? 'Edit / reference' : 'Text / image mix'}</span>
            </div>
            <div className="rounded-xl bg-background/40 px-3 py-2 text-muted-foreground">
              Формат: <span className="text-foreground">{selectedRatio} • {selectedCount}x</span>
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">
            Референсы
            {model?.requires_reference && (
              <span className="text-destructive ml-1">*</span>
            )}
          </label>
          <UploadArea
            files={references}
            onFilesChange={setReferences}
            maxFiles={model?.max_references || 4}
            accept="image/*"
            required={model?.requires_reference}
            onUpload={onUploadReference}
          />
          <p className="text-xs text-muted-foreground">
            {model?.requires_reference
              ? 'Для этой модели нужен хотя бы один исходник или референс.'
              : 'Можно добавить референсы для стиля, композиции или сохранения деталей.'}
          </p>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">Промпт</label>
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Опишите сцену, стиль, свет, камеру, детали персонажей и желаемый результат..."
            className={cn(
              "min-h-[140px] resize-none",
              "bg-secondary/50 border-border/50",
              "focus:border-gold/50 focus:ring-gold/20",
              "placeholder:text-muted-foreground/50"
            )}
          />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{prompt.trim().length > 0 ? 'Промпт готов к запуску' : 'Пустой prompt не отправится'}</span>
            <span>{prompt.length} симв.</span>
          </div>
        </div>
      </div>

      <div className="glass rounded-2xl p-4 space-y-4">
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-xl bg-secondary/40 p-3">
            <p className="text-muted-foreground mb-1">Сводка</p>
            <p className="text-foreground font-medium">{model?.label}</p>
            <p className="text-muted-foreground mt-1">
              {selectedRatio}
              {model?.qualities?.length ? ` • ${selectedQuality}` : ''}
              {' • '}
              {selectedCount}x
            </p>
          </div>
          <div className="rounded-xl bg-secondary/40 p-3">
            <p className="text-muted-foreground mb-1">Файлы</p>
            <p className="text-foreground font-medium">{references.length} / {model?.max_references || 0}</p>
            <p className="text-muted-foreground mt-1">
              {model?.requires_reference ? 'Минимум 1 обязателен' : 'Опционально'}
            </p>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">Стоимость</span>
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

        {needsReference && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-gold/10 border border-gold/30">
            <AlertCircle className="w-4 h-4 text-gold flex-shrink-0" />
          <p className="text-xs text-gold">
              Загрузите референс для этой модели
            </p>
          </div>
        )}

        <Button
          onClick={handleSubmit}
          disabled={!isValid || isSubmitting}
          className={cn(
            "w-full h-12 text-base font-semibold",
            "bg-gold hover:bg-gold/90 text-primary-foreground",
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
              <Sparkles className="w-5 h-5 mr-2" />
              Запустить фото
            </>
          )}
        </Button>
      </div>
    </div>
  )
}
