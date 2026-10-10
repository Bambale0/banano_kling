'use client'

import { normalizeRepeatPrompt } from '@/lib/repeat-prompt'
import { normalizeVideoRepeatSlots } from '@/lib/video-repeat-references'
import { getPendingVideoRepeat, isVideoStatusPending, VIDEO_REPEAT_PENDING_CHANGED, type PendingVideoRepeat } from '@/lib/video-repeat-pending'

import { useState, useMemo, useEffect, useRef } from 'react'
import type { VideoModel, UploadedFile, ScenarioType, VideoPromptPreset, VideoRepeatReferenceSlots } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { ModelSelect } from './model-select'
import { Wan3PrimeForm } from './wan3-prime-form'
import type { Wan3PrimeGenerateResponse, Wan3PrimeRecipe } from '@/lib/wan3-prime-api'
import { RatioSelect } from './ratio-select'
import { UploadArea } from './upload-area'
import { ScenarioSelect } from './scenario-select'
import { DurationSelect } from './duration-select'
import { getStorageItem, removeStorageItem } from '@/hooks/browser-storage'
import {
  AlertCircle,
  Banana,
  Clapperboard,
  Headphones,
  Loader2,
  Sparkles,
  UserRound,
  Video,
} from 'lucide-react'

function roundVideoCost(raw: number) {
  return Math.round(raw * 2) / 2
}

function getVideoModelCost(model: VideoModel | undefined, duration: number, quality?: string, multiplier = 1) {
  if (!model) return 5
  const quotedCost = quality ? model.quality_duration_costs?.[quality]?.[duration.toString()] : undefined
  if (typeof quotedCost === 'number' && Number.isFinite(quotedCost)) return quotedCost * multiplier
  const qualityCost = quality ? model.quality_costs?.[quality] : undefined
  if (typeof qualityCost === 'number') {
    return roundVideoCost(qualityCost * duration) * multiplier
  }
  return (model.costs[duration.toString()] ?? Object.values(model.costs)[0] ?? 5) * multiplier
}

function getVideoModelPerSecondCost(model: VideoModel | undefined, duration: number, quality?: string, multiplier = 1) {
  return getVideoModelCost(model, duration, quality, multiplier) / Math.max(duration, 1)
}

const HIDDEN_FROM_COMMON_VIDEO_LIST = new Set([
  'avatar_std',
  'avatar_pro',
  'motion_control',
  'motion_control_v26',
  'motion_control_v30',
])

interface VideoGeneratorFormProps {
  models: VideoModel[]
  onSubmit: (data: {
    model: string
    scenario: ScenarioType
    ratio: string
    duration: number
    sourceFeedGenId?: number | null
    grokMode: string
    grokResolution: string
    veoGenerationType: string
    veoTranslation: boolean
    veoResolution: string
    veoSeed: number | null
    veoWatermark: string
    wanResolution: string
    wanSeed: number | null
    wanAudio: boolean
    wanNsfwChecker: boolean
    wanFirstFrameUrl: string | null
    wanLastFrameUrl: string | null
    wanReferenceFileUrls: string[]
    wanReferenceLinkUrls: string[]
    klingNegativePrompt: string
    klingCfgScale: number
    omniResolution: string
    omniSeed: number | null
    omniAudioIds: string[]
    omniCharacterIds: string[]
    omniBaseVoice: string
    omniVoiceName: string
    omniVoiceDescription: string
    omniExampleDialogue: string
    omniCharacterName: string
    omniCharacterAudioIds: string[]
    prompt: string
    startImage: string | null
    references: string[]
    videoReferences: string[]
    audioReference: string | null
    audioReferences: string[]
  }) => Promise<void>
  onUploadImageReference?: (file: File) => Promise<UploadedFile>
  onUploadVideoReference?: (file: File, typedRepeatModel?: string) => Promise<UploadedFile>
  onUploadAudioReference?: (file: File) => Promise<UploadedFile>
  savedImageReferences?: UploadedFile[]
  savedVideoReferences?: UploadedFile[]
  savedAudioReferences?: UploadedFile[]
  promptPreset?: VideoPromptPreset | null
  onPromptPresetConsumed?: () => void
  isSubmitting: boolean
  credits: number
  isAdmin?: boolean
  onWanQueued?: (result: Wan3PrimeGenerateResponse) => void | Promise<void>
  onModelSelected?: (modelId: string) => void
  onCheckPendingVideo?: () => void
}

export function VideoGeneratorForm({ 
  models, 
  onSubmit, 
  onUploadImageReference,
  onUploadVideoReference,
  onUploadAudioReference,
  savedImageReferences = [],
  savedVideoReferences = [],
  savedAudioReferences = [],
  promptPreset,
  onPromptPresetConsumed,
  isSubmitting,
  credits,
  isAdmin = false,
  onWanQueued,
  onModelSelected,
  onCheckPendingVideo,
}: VideoGeneratorFormProps) {
  const formatPerSecondCost = (raw: number) => Number(raw.toFixed(2)).toString()
  const [selectedModel, setSelectedModel] = useState(models.find((item) => !['motion_control', 'motion_control_v26', 'motion_control_v30'].includes(item.id))?.id || models[0]?.id || '')
  const [selectedScenario, setSelectedScenario] = useState<ScenarioType>('text')
  const [selectedRatio, setSelectedRatio] = useState('16:9')
  const [selectedDuration, setSelectedDuration] = useState(5)
  const [grokMode, setGrokMode] = useState('normal')
  const [grokResolution, setGrokResolution] = useState('480p')
  const [veoGenerationType, setVeoGenerationType] = useState('TEXT_2_VIDEO')
  const [veoTranslation, setVeoTranslation] = useState(true)
  const [veoResolution, setVeoResolution] = useState('720p')
  const [veoSeed, setVeoSeed] = useState('')
  const [veoWatermark, setVeoWatermark] = useState('')
  const [wanOwnerTaskId, setWanOwnerTaskId] = useState<string | undefined>()
  const [wanRecipe, setWanRecipe] = useState<Wan3PrimeRecipe | undefined>()
  const [wanPublicationSource, setWanPublicationSource] = useState<number | null>(null)
  const [wanResolution, setWanResolution] = useState('1080P')
  const [wanSeed, setWanSeed] = useState('')
  const [wanAudio, setWanAudio] = useState(true)
  const [wanNsfwChecker, setWanNsfwChecker] = useState(false)
  const [wanLastFrame, setWanLastFrame] = useState<UploadedFile[]>([])
  const [wanFileUrl, setWanFileUrl] = useState('')
  const [wanLinkUrl, setWanLinkUrl] = useState('')
  const [klingNegativePrompt, setKlingNegativePrompt] = useState('')
  const [klingCfgScale, setKlingCfgScale] = useState(0.5)
  const [omniResolution, setOmniResolution] = useState('720p')
  const [omniSeed, setOmniSeed] = useState('')
  const [omniAudioIds, setOmniAudioIds] = useState('')
  const [omniCharacterIds, setOmniCharacterIds] = useState('')
  const [omniBaseVoice, setOmniBaseVoice] = useState('achernar')
  const [omniVoiceName, setOmniVoiceName] = useState('')
  const [omniVoiceDescription, setOmniVoiceDescription] = useState('')
  const [omniExampleDialogue, setOmniExampleDialogue] = useState('')
  const [omniCharacterName, setOmniCharacterName] = useState('')
  const [omniCharacterAudioIds, setOmniCharacterAudioIds] = useState('')
  const [prompt, setPrompt] = useState('')
  const [sourceFeedGenId, setSourceFeedGenId] = useState<number | null>(null)
  const appliedPromptPresetRef = useRef<VideoPromptPreset | null>(null)
  const [repeatTitle, setRepeatTitle] = useState('')
  const [repeatSlots, setRepeatSlots] = useState<VideoRepeatReferenceSlots | undefined>()
  const [repeatUploads, setRepeatUploads] = useState<Record<string, UploadedFile[]>>({})
  const [repeatError, setRepeatError] = useState(false)
  const [repeatPending, setRepeatPending] = useState<PendingVideoRepeat | null>(null)
  const repeatSession = useRef(0)
  const submittingRef = useRef(false)
  const slotSession = repeatSession.current
  const typedSlots = repeatSlots ? [
    ...repeatSlots.images.map((slot) => ({ ...slot, type: 'image' as const, key: `image-${slot.index}` })),
    ...repeatSlots.videos.map((slot) => ({ ...slot, type: 'video' as const, key: `video-${slot.index}` })),
  ] : []
  const missingRepeatUploads = typedSlots.some((slot) => slot.binding === 'upload'
    && (!repeatUploads[slot.key]?.[0]?.url || repeatUploads[slot.key][0].uploading))
  const repeatBlocked = Boolean(repeatPending) || Boolean(repeatSlots && (!repeatSlots.available || missingRepeatUploads || repeatError))
  const [startImage, setStartImage] = useState<UploadedFile[]>([])
  const [photoReferences, setPhotoReferences] = useState<UploadedFile[]>([])
  const [videoReferences, setVideoReferences] = useState<UploadedFile[]>([])
  const [audioReference, setAudioReference] = useState<UploadedFile[]>([])

  const regularVideoModels = useMemo(
    () => models.filter((item) => !HIDDEN_FROM_COMMON_VIDEO_LIST.has(item.id)),
    [models]
  )
  const requestedServiceModel = useMemo(
    () =>
      HIDDEN_FROM_COMMON_VIDEO_LIST.has(selectedModel)
        ? models.filter((item) => item.id === selectedModel)
        : [],
    [models, selectedModel]
  )
  const visibleModels = useMemo(
    () =>
      requestedServiceModel.length
        ? [...requestedServiceModel, ...regularVideoModels]
        : regularVideoModels,
    [regularVideoModels, requestedServiceModel]
  )

  const model = useMemo(() => models.find(m => m.id === selectedModel), [models, selectedModel])

  const isGeminiOmni = selectedModel === 'gemini_omni'
  const isOmniAudio = selectedModel === 'gemini_omni_audio' || (isGeminiOmni && selectedScenario === 'audio')
  const isOmniCharacter = selectedModel === 'gemini_omni_character' || (isGeminiOmni && selectedScenario === 'character')
  const isOmniVideo = selectedModel === 'gemini_omni_video' || (isGeminiOmni && !isOmniAudio && !isOmniCharacter)
  const isWanPrime = selectedModel === 'wan_3_prime'
  const qualityForModel = (item?: VideoModel) => {
    if (!item) return undefined
    if (item.grok_resolutions?.length) {
      return item.grok_resolutions.includes(grokResolution) ? grokResolution : item.grok_resolutions[0]
    }
    if (item.veo_resolutions?.length) {
      return item.veo_resolutions.includes(veoResolution) ? veoResolution : item.veo_resolutions[0]
    }
    if (item.wan_resolutions?.length) {
      return item.wan_resolutions.includes(wanResolution) ? wanResolution.toLowerCase() : item.wan_resolutions[0].toLowerCase()
    }
    if ((item.id === 'gemini_omni' || item.id === 'gemini_omni_video') && selectedScenario !== 'audio' && selectedScenario !== 'character') {
      return item.omni_resolutions?.includes(omniResolution) ? omniResolution : item.omni_resolutions?.[0]
    }
    return undefined
  }
  const selectedQuality = qualityForModel(model)
  // The descriptor covers the complete server recipe, including retained video
  // inputs that deliberately have no local URL. Never infer a tariff from IDs.
  const requiresDurationQuote = Boolean(repeatSlots && selectedModel === 'seedance_2_5')
  const retainedDurationCosts = repeatSlots?.duration_costs
  const retainedDurationCost = retainedDurationCosts?.[selectedDuration.toString()]
  const modelQualityPrice = selectedQuality ? model?.quality_costs?.[selectedQuality] : undefined
  const modelRequiresConfiguredQuality = Boolean(model?.requires_quality_pricing)
  const priceAvailable = (!repeatSlots || repeatSlots.available)
    && (!requiresDurationQuote || (typeof retainedDurationCost === 'number' && Number.isFinite(retainedDurationCost)))
    && (!modelRequiresConfiguredQuality || (typeof modelQualityPrice === 'number' && Number.isFinite(modelQualityPrice) && modelQualityPrice > 0))
  // Normal Seedance 2 submits retained video refs even after switching scenario.
  // Repeat descriptors already include all retained/replacement source inputs.
  const repeatCostMultiplier = repeatSlots?.cost_multiplier ?? (
    selectedModel === 'seedance_2' && (model?.max_video_references ?? 0) > 0 && videoReferences.length > 0 ? 2 : 1
  )
  const durationCosts = useMemo(
    () => requiresDurationQuote ? retainedDurationCosts || {} : priceAvailable
      ? Object.fromEntries(
        (model?.durations || [selectedDuration]).map((duration) => [
          duration.toString(),
          getVideoModelCost(model, duration, selectedQuality, repeatCostMultiplier),
        ])
      ) : {},
    [model, selectedDuration, selectedQuality, priceAvailable, repeatCostMultiplier, requiresDurationQuote, retainedDurationCosts]
  )
  const baseCost = requiresDurationQuote
    ? retainedDurationCost ?? 0
    : getVideoModelCost(model, selectedDuration, selectedQuality, repeatCostMultiplier)
  const cost = isOmniAudio
    ? model?.omni_audio_cost ?? 3
    : isOmniCharacter
      ? model?.omni_character_cost ?? 5
      : baseCost
  const perSecondCost = cost / Math.max(selectedDuration, 1)
  const canAfford = priceAvailable && credits >= cost
  const parseAssetIds = (value: string) =>
    value
      .split(/[\s,;]+/)
      .map((item) => item.trim())
      .filter(Boolean)
  const parsedOmniAudioIds = parseAssetIds(omniAudioIds)
  const parsedOmniCharacterIds = parseAssetIds(omniCharacterIds)
  const parsedOmniCharacterAudioIds = parseAssetIds(omniCharacterAudioIds)
  const omniImageCount = isOmniVideo ? photoReferences.length : 0
  const omniVideoCount = isOmniVideo ? videoReferences.length : 0
  const omniInputUnits = omniImageCount + omniVideoCount * 2 + parsedOmniCharacterIds.length
  const omniTooManyVideos = isOmniVideo && omniVideoCount > 1
  const omniTooManyAudioIds = isOmniVideo && parsedOmniAudioIds.length > 1
  const omniTooManyCharacterIds = isOmniVideo && parsedOmniCharacterIds.length > 3
  const omniTooManyCharacterAudioIds = isOmniCharacter && parsedOmniCharacterAudioIds.length > 1
  const omniOverQuota = isOmniVideo && omniInputUnits > 7
  const omniHasVideoReference = isOmniVideo && omniVideoCount > 0
  
  // Check if scenario is supported
  const scenarioSupported = model?.supports.includes(selectedScenario) ?? false
  
  // Image-to-video uses the same photo-reference picker as every other photo input.
  // The backend promotes the first selected reference to the provider's primary image slot.
  const needsPhotoReference = selectedScenario === 'imgtxt' && !isOmniVideo && !sourceFeedGenId && photoReferences.length === 0
  const needsCharacterImage = !repeatSlots && selectedScenario === 'character' && startImage.length === 0
  const needsVideoRef = selectedScenario === 'video' && !isOmniVideo && !isWanPrime && !sourceFeedGenId && videoReferences.length === 0
  const needsWanEditSource = isWanPrime && selectedScenario === 'edit' && !sourceFeedGenId && videoReferences.length === 0
  const needsWanFile = isWanPrime && selectedScenario === 'file' && wanFileUrl.trim().length === 0
  const needsWanLink = isWanPrime && selectedScenario === 'link' && wanLinkUrl.trim().length === 0
  const needsWanLastFrame = isWanPrime && selectedScenario === 'first_last' && wanLastFrame.length === 0
  const needsAvatarImage = !repeatSlots && selectedScenario === 'avatar' && startImage.length === 0
  const needsAvatarAudio = !repeatSlots && selectedScenario === 'avatar' && audioReference.length === 0
  const needsOmniVoiceName = isOmniAudio && omniVoiceName.trim().length === 0

  const wanHasReferenceOnlyInput = isWanPrime
    && selectedScenario === 'video'
    && photoReferences.length === 0
    && videoReferences.length === 0
    && audioReference.length > 0
  const hasPrompt = prompt.trim().length > 0 || Boolean(sourceFeedGenId) || wanHasReferenceOnlyInput
  const isValid = hasPrompt &&
    canAfford &&
    !repeatBlocked &&
    scenarioSupported &&
    !needsPhotoReference &&
    !needsCharacterImage &&
    !needsVideoRef &&
    !needsWanEditSource &&
    !needsWanFile &&
    !needsWanLink &&
    !needsWanLastFrame &&
    !needsAvatarImage &&
    !needsAvatarAudio &&
    !needsOmniVoiceName &&
    !omniTooManyVideos &&
    !omniTooManyAudioIds &&
    !omniTooManyCharacterIds &&
    !omniTooManyCharacterAudioIds &&
    !omniOverQuota

  const omniGuideSteps = [
    {
      icon: Headphones,
      title: '1. Голос',
      text: 'Создайте Audio ID, если ролику нужен постоянный голос.',
    },
    {
      icon: UserRound,
      title: '2. Персонаж',
      text: 'Создайте Character ID по фото и при желании привяжите голос.',
    },
    {
      icon: Video,
      title: '3. Видео',
      text: 'Соберите промпт, референсы и нужные ID в режиме Video.',
    },
  ]

  // consume requested Avatar service
  useEffect(() => {
    const requestedModel = getStorageItem('miniapp_requested_video_model')
    const requestedScenario = getStorageItem('miniapp_requested_video_scenario')
    if (requestedModel && models.some((item) => item.id === requestedModel)) {
      setSelectedModel(requestedModel)
      if (requestedScenario) setSelectedScenario(requestedScenario as ScenarioType)
      removeStorageItem('miniapp_requested_video_model')
      removeStorageItem('miniapp_requested_video_scenario')
    }
  }, [models])

  useEffect(() => {
    if (!promptPreset || appliedPromptPresetRef.current === promptPreset) return
    appliedPromptPresetRef.current = promptPreset
    if (promptPreset.model === 'wan_3_prime') {
      setWanOwnerTaskId(promptPreset.wan3OwnerTaskId)
      setWanRecipe(promptPreset.wan3Recipe)
      setWanPublicationSource(promptPreset.wan3OwnerTaskId ? null : promptPreset.sourceFeedGenId || null)
    }
    setPrompt(normalizeRepeatPrompt(promptPreset).prompt)
    setSourceFeedGenId(promptPreset.sourceFeedGenId || null)
    setRepeatTitle(promptPreset.sourceFeedGenId ? promptPreset.title : '')
    const slots = promptPreset.sourceFeedGenId && promptPreset.repeatReferenceSlots
      ? normalizeVideoRepeatSlots(promptPreset.repeatReferenceSlots) : undefined
    repeatSession.current += 1
    setRepeatSlots(slots && !models.some((item) => item.id === promptPreset.model)
      ? { version: 1, available: false, images: [], videos: [] } : slots)
    setRepeatUploads({})
    setRepeatError(false)
    setRepeatPending(getPendingVideoRepeat(promptPreset.sourceFeedGenId))
    if (promptPreset.model && models.some((item) => item.id === promptPreset.model)) {
      setSelectedModel(promptPreset.model)
    }
    if (promptPreset.scenario) {
      setSelectedScenario(promptPreset.scenario)
    }
    if (promptPreset.ratio) {
      setSelectedRatio(promptPreset.ratio)
    }
    if (promptPreset.duration) {
      setSelectedDuration(promptPreset.duration)
    }
    if (slots) {
      setStartImage([])
      setPhotoReferences([])
    } else if (promptPreset.scenario === 'character' || promptPreset.scenario === 'avatar') {
      setStartImage(promptPreset.initialStartImage || [])
      setPhotoReferences(promptPreset.initialPhotoReferences || [])
    } else {
      setStartImage([])
      const combinedPhotoReferences = [
        ...(promptPreset.initialStartImage || []),
        ...(promptPreset.initialPhotoReferences || []),
      ]
      setPhotoReferences(
        combinedPhotoReferences.filter(
          (item, index, items) => items.findIndex((candidate) => candidate.url === item.url) === index
        )
      )
    }
    setVideoReferences(slots ? [] : promptPreset.initialVideoReferences || [])
    setAudioReference([])
    onPromptPresetConsumed?.()
  }, [models, onPromptPresetConsumed, promptPreset])

  useEffect(() => {
    const syncPending = () => setRepeatPending(getPendingVideoRepeat(sourceFeedGenId))
    syncPending()
    window.addEventListener(VIDEO_REPEAT_PENDING_CHANGED, syncPending)
    return () => window.removeEventListener(VIDEO_REPEAT_PENDING_CHANGED, syncPending)
  }, [sourceFeedGenId])

  // selected model is hidden motion: switch to first visible video model
  useEffect(() => {
    if (HIDDEN_FROM_COMMON_VIDEO_LIST.has(selectedModel)) {
      const nextModel = visibleModels[0]
      if (nextModel) setSelectedModel(nextModel.id)
    }
  }, [selectedModel, visibleModels])

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
    if (model.grok_resolutions?.length && !model.grok_resolutions.includes(grokResolution)) {
      setGrokResolution(model.grok_resolutions[0])
    }
    if (model.veo_generation_types?.length && !model.veo_generation_types.includes(veoGenerationType)) {
      setVeoGenerationType(model.veo_generation_types[0])
    }
    if (model.veo_resolutions?.length && !model.veo_resolutions.includes(veoResolution)) {
      setVeoResolution(model.veo_resolutions[0])
    }
    if (model.omni_resolutions?.length && !model.omni_resolutions.includes(omniResolution)) {
      setOmniResolution(model.omni_resolutions[0])
    }
    if (model.omni_base_voices?.length && !model.omni_base_voices.includes(omniBaseVoice)) {
      setOmniBaseVoice(model.omni_base_voices[0])
    }
    if (!model.supports_translation) setVeoTranslation(true)
    if (!model.supports_watermark) setVeoWatermark('')
    if (!model.supports_seed) setVeoSeed('')
    if (!model.supports_seed && model.id !== 'wan_3_prime') setWanSeed('')
    if (!model.supports_negative_prompt) setKlingNegativePrompt('')
    if (!model.supports_cfg_scale) setKlingCfgScale(0.5)
    if (!model.supports_omni_seed) setOmniSeed('')
    if (!model.supports_omni_audio_ids) setOmniAudioIds('')
    if (!model.supports_omni_character_ids) setOmniCharacterIds('')
    if (!model.supports_omni_character_audio_ids) setOmniCharacterAudioIds('')
  }, [model, grokMode, grokResolution, veoGenerationType, veoResolution, omniResolution, omniBaseVoice])

  const handleModelChange = (modelId: string) => {
    onModelSelected?.(modelId)
    const nextModel = models.find((item) => item.id === modelId)
    if (!nextModel) {
      setSelectedModel(modelId)
      return
    }

    setSelectedModel(modelId)
    setSelectedScenario((current) =>
      nextModel.supports.includes(current) ? current : nextModel.supports[0] || 'text'
    )
    setSelectedRatio((current) =>
      nextModel.ratios.includes(current) ? current : nextModel.ratios[0] || '16:9'
    )
    setSelectedDuration((current) =>
      nextModel.durations.includes(current) ? current : nextModel.durations[0] || 5
    )

    if (nextModel.id === 'seedance_2') {
      // Seedance 2.0 is primarily an image-to-video flow in the Mini App.
      // Selecting the model should open the useful default immediately instead
      // of leaving the previous Text -> Video scenario selected.
      setSelectedScenario('imgtxt')
      setStartImage([])
      setVideoReferences([])
      setAudioReference([])
    } else if (nextModel.id === 'grok_imagine') {
      setSelectedScenario('imgtxt')
      setStartImage([])
      setSelectedRatio((current) =>
        nextModel.ratios.includes(current) ? current : nextModel.ratios[0] || '16:9'
      )
      setSelectedDuration((current) =>
        nextModel.durations.includes(current) ? current : nextModel.durations[0] || 6
      )
      setVideoReferences([])
      setAudioReference([])
    } else if (nextModel.id === 'grok_imagine_v15') {
      setSelectedScenario('imgtxt')
      setStartImage([])
      setSelectedRatio((current) =>
        nextModel.ratios.includes(current) ? current : nextModel.ratios[0] || 'auto'
      )
      setSelectedDuration((current) =>
        nextModel.durations.includes(current) ? current : nextModel.durations[0] || 1
      )
      setPhotoReferences([])
      setVideoReferences([])
      setAudioReference([])
    } else if (nextModel.id === 'wan_3_prime') {
      setSelectedScenario('text')
      setSelectedRatio((current) =>
        nextModel.ratios.includes(current) ? current : 'adaptive'
      )
      setSelectedDuration((current) =>
        nextModel.durations.includes(current) ? current : 5
      )
    }
  }

  const handleSubmit = async () => {
    if (!isValid || isSubmitting || submittingRef.current) return
    submittingRef.current = true
    const submittedSession = repeatSession.current
    const submitDuration = isOmniAudio || isOmniCharacter ? 6 : selectedDuration
    try {
    await onSubmit({
      model: selectedModel,
      scenario: selectedScenario,
      ratio: selectedRatio,
      duration: submitDuration,
      sourceFeedGenId,
      grokMode,
      grokResolution,
      veoGenerationType,
      veoTranslation,
      veoResolution,
      veoSeed: veoSeed.trim() ? Number(veoSeed) : null,
      veoWatermark,
      wanResolution,
      wanSeed: wanSeed.trim() ? Number(wanSeed) : null,
      wanAudio,
      wanNsfwChecker,
      wanFirstFrameUrl: isWanPrime && selectedScenario === 'first_last' ? photoReferences[0]?.url || null : null,
      wanLastFrameUrl: isWanPrime ? wanLastFrame[0]?.url || null : null,
      wanReferenceFileUrls: isWanPrime && selectedScenario === 'file' ? [wanFileUrl.trim()].filter(Boolean) : [],
      wanReferenceLinkUrls: isWanPrime && selectedScenario === 'link' ? [wanLinkUrl.trim()].filter(Boolean) : [],
      klingNegativePrompt,
      klingCfgScale,
      omniResolution,
      omniSeed: omniSeed.trim() ? Number(omniSeed) : null,
      omniAudioIds: parsedOmniAudioIds,
      omniCharacterIds: parsedOmniCharacterIds,
      omniBaseVoice,
      omniVoiceName,
      omniVoiceDescription,
      omniExampleDialogue,
      omniCharacterName,
      omniCharacterAudioIds: parsedOmniCharacterAudioIds,
      prompt,
      startImage:
        repeatSlots ? null : isOmniAudio || !['character', 'avatar'].includes(selectedScenario)
          ? null
          : startImage[0]?.url || null,
      references:
        repeatSlots ? typedSlots.filter((slot) => slot.type === 'image' && slot.binding === 'upload').map((slot) => repeatUploads[slot.key][0].url) : isOmniAudio || isOmniCharacter
          ? []
          : selectedScenario === 'imgtxt' || (model?.max_image_references ?? 8) > 0
            ? photoReferences.map((item) => item.url)
            : [],
      videoReferences: repeatSlots ? typedSlots.filter((slot) => slot.type === 'video' && slot.binding === 'upload').map((slot) => repeatUploads[slot.key][0].url) : isOmniVideo || (model?.max_video_references ?? 0) > 0 ? videoReferences.map(r => r.url) : [],
      audioReference: selectedScenario === 'avatar' ? audioReference[0]?.url || null : null,
      audioReferences: isWanPrime ? audioReference.map((item) => item.url) : [],
    })
    } catch (error) {
      if (submittedSession === repeatSession.current) {
        if (isVideoStatusPending(error)) setRepeatPending(getPendingVideoRepeat(sourceFeedGenId))
        else if (repeatSlots) setRepeatError(true)
      }
      return
    } finally {
      submittingRef.current = false
    }
    if (submittedSession !== repeatSession.current) return
    setRepeatSlots(undefined)
    setRepeatUploads({})
    setPrompt('')
    setSourceFeedGenId(null)
    setRepeatTitle('')
    setStartImage([])
    setPhotoReferences([])
    setVideoReferences([])
    setAudioReference([])
    setOmniSeed('')
    setWanSeed('')
    setWanFileUrl('')
    setWanLinkUrl('')
    setWanLastFrame([])
  }

  if (isWanPrime) return <Wan3PrimeForm
    key={wanOwnerTaskId || (wanPublicationSource ? `publication-${wanPublicationSource}` : 'wan-composer')}
    credits={credits} isAdmin={isAdmin} ownerTaskId={wanOwnerTaskId}
    initialRecipe={wanRecipe} onQueued={onWanQueued}
    publicationSourceId={wanPublicationSource}
    modelSelector={<ModelSelect models={visibleModels.map(item => ({
      id: item.id, label: item.label, description: item.description,
      cost: item.id === 'wan_3_prime' ? undefined : getVideoModelPerSecondCost(item, 5, qualityForModel(item)),
    }))} value={selectedModel} onChange={handleModelChange} />}
  />

  return (
    <div className="min-w-0 space-y-4 overflow-x-hidden">
      <div className="glass min-w-0 space-y-4 overflow-hidden rounded-2xl border border-cyan/20 p-3 sm:p-4">
        <fieldset disabled={Boolean(repeatSlots)} aria-label="Модель" className="space-y-2">
          <label className="text-sm font-medium text-foreground">Модель</label>
          {!priceAvailable ? <p className="text-sm text-foreground">{model?.label}</p> : <ModelSelect
            models={visibleModels.map(m => ({
              id: m.id,
              label: m.label,
              description: m.description,
              cost:
                m.id === 'gemini_omni' && selectedScenario === 'audio'
                  ? m.omni_audio_cost ?? 3
                  : m.id === 'gemini_omni' && selectedScenario === 'character'
                    ? m.omni_character_cost ?? 5
                    : requiresDurationQuote && m.id === selectedModel
                      ? baseCost / Math.max(selectedDuration, 1)
                      : getVideoModelPerSecondCost(m, selectedDuration, qualityForModel(m), m.id === selectedModel ? repeatCostMultiplier : 1),
            }))}
            value={selectedModel}
            onChange={handleModelChange}
          />}
        </fieldset>

        {isGeminiOmni ? (
            <div className="space-y-3 rounded-2xl border border-cyan/20 bg-cyan/5 p-3 text-xs leading-relaxed text-muted-foreground sm:p-4">
              <div className="flex items-start gap-2 text-foreground">
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-cyan" />
                <p>
                  Gemini Omni объединяет три режима: видео, сохранённые голоса и сохранённых персонажей. ID из Audio и Character можно вставлять в Video, чтобы ролики держали один голос и одного героя.
                </p>
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                {omniGuideSteps.map(({ icon: Icon, title, text }) => (
                  <div key={title} className="flex items-start gap-2">
                    <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-cyan/30 bg-cyan/10 text-cyan">
                      <Icon className="h-4 w-4" />
                    </span>
                    <span>
                      <span className="block font-medium text-foreground">{title}</span>
                      <span>{text}</span>
                    </span>
                  </div>
                ))}
              </div>
              <p>
                Video принимает текст, стартовое изображение, фото-референсы, один видео-референс, один Audio ID и до трёх Character ID. Доступны 4/6/8/10 сек, 16:9 или 9:16, 720p/1080p/4k и seed для повторяемого результата.
              </p>
            </div>
        ) : null}

        <fieldset disabled={Boolean(repeatSlots)} aria-label="Сценарий" className="space-y-2">
          <label className="text-sm font-medium text-foreground">Сценарий</label>
          <ScenarioSelect
            scenarios={model?.supports || ['text']}
            value={selectedScenario}
            onChange={setSelectedScenario}
          />
          {repeatSlots ? <p className="text-xs text-muted-foreground">Модель и сценарий сохранены из публикации.</p> : null}
          {repeatSlots?.pricing_quality ? <p className="text-xs text-muted-foreground">Качество исходного видео: {repeatSlots.pricing_quality}</p> : null}
        </fieldset>

        {isWanPrime ? (
          <div className="space-y-4 rounded-2xl border border-cyan/20 bg-cyan/5 p-4">
            <div className="grid gap-3 lg:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Качество Wan</label>
                <div className="flex gap-2">
                  {(model?.wan_resolutions || ['480P', '720P', '1080P']).map((resolution) => {
                    const key = resolution.toLowerCase()
                    const resolutionCost = model?.quality_costs?.[key]
                    const unavailable = typeof resolutionCost !== 'number'
                    return (
                      <button
                        key={resolution}
                        type="button"
                        onClick={() => setWanResolution(resolution)}
                        className={cn(
                          'flex-1 rounded-xl border px-3 py-2 text-xs font-medium leading-tight transition-all duration-200',
                          wanResolution === resolution
                            ? 'border-cyan/50 bg-cyan/15 text-cyan'
                            : 'border-border/50 bg-secondary/40 text-muted-foreground hover:bg-secondary hover:text-foreground'
                        )}
                      >
                        <span className="block">{resolution}</span>
                        <span className="block text-[10px] text-gold">
                          {unavailable ? 'не настроено' : `${resolutionCost}🍌/с`}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Seed</label>
                <Input
                  type="number"
                  min="0"
                  max="2147483647"
                  value={wanSeed}
                  onChange={(e) => setWanSeed(e.target.value)}
                  placeholder="Авто"
                  className="bg-secondary/50 border-border/50"
                />
              </div>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => setWanAudio((prev) => !prev)}
                className={cn(
                  'rounded-xl border px-4 py-3 text-left text-sm transition-all duration-200',
                  wanAudio
                    ? 'border-cyan/40 bg-cyan/10 text-cyan'
                    : 'border-border/50 bg-secondary/40 text-muted-foreground hover:bg-secondary/60 hover:text-foreground'
                )}
              >
                {wanAudio ? 'Аудио в результате включено' : 'Аудио в результате выключено'}
              </button>
              <button
                type="button"
                onClick={() => setWanNsfwChecker((prev) => !prev)}
                className={cn(
                  'rounded-xl border px-4 py-3 text-left text-sm transition-all duration-200',
                  wanNsfwChecker
                    ? 'border-cyan/40 bg-cyan/10 text-cyan'
                    : 'border-border/50 bg-secondary/40 text-muted-foreground hover:bg-secondary/60 hover:text-foreground'
                )}
              >
                {wanNsfwChecker ? 'Проверка NSFW включена' : 'Проверка NSFW выключена'}
              </button>
            </div>
            {selectedScenario === 'file' ? (
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Публичный URL файла</label>
                <Input value={wanFileUrl} onChange={(e) => setWanFileUrl(e.target.value)} placeholder="https://..." className="bg-secondary/50 border-border/50" />
              </div>
            ) : null}
            {selectedScenario === 'link' ? (
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Публичная ссылка</label>
                <Input value={wanLinkUrl} onChange={(e) => setWanLinkUrl(e.target.value)} placeholder="https://..." className="bg-secondary/50 border-border/50" />
              </div>
            ) : null}
          </div>
        ) : null}

        {!isOmniAudio && !isOmniCharacter && selectedScenario !== 'avatar' ? (
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
                costs={durationCosts}
              />
            </div>
          </div>
        ) : null}

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

        {model?.grok_resolutions?.length ? (
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Качество Grok 1.5</label>
            <div className="flex gap-2">
              {model.grok_resolutions.map((resolution) => (
                <button
                  key={resolution}
                  type="button"
                  onClick={() => setGrokResolution(resolution)}
                  className={cn(
                    'flex-1 rounded-xl border px-3 py-2 text-xs font-medium transition-all duration-200',
                    grokResolution === resolution
                      ? 'border-cyan/50 bg-cyan/15 text-cyan'
                      : 'border-border/50 bg-secondary/50 text-muted-foreground hover:bg-secondary hover:text-foreground'
                  )}
                >
                  {resolution}
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
                <label className="text-sm font-medium text-foreground">Качество</label>
                <div className="flex gap-2">
                  {(model.veo_resolutions || ['720p']).map((resolution) => {
                    const resolutionCost = getVideoModelCost(model, selectedDuration, resolution, repeatCostMultiplier)
                    return (
                      <button
                        key={resolution}
                        type="button"
                        onClick={() => setVeoResolution(resolution)}
                        className={cn(
                          'flex-1 rounded-xl border px-3 py-2 text-xs font-medium leading-tight transition-all duration-200',
                          veoResolution === resolution
                            ? 'border-cyan/50 bg-cyan/15 text-cyan'
                            : 'border-border/50 bg-secondary/40 text-muted-foreground hover:bg-secondary hover:text-foreground'
                        )}
                      >
                        <span className="block">{resolution}</span>
                        <span className="block text-[10px] text-gold">{resolutionCost}🍌</span>
                      </button>
                    )
                  })}
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
                  <label className="text-sm font-medium text-foreground">Метка на видео</label>
                  <Input
                    value={veoWatermark}
                    onChange={(e) => setVeoWatermark(e.target.value)}
                    placeholder="Текст для метки"
                    className="bg-secondary/50 border-border/50"
                  />
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {isOmniVideo ? (
          <div className="space-y-4 rounded-2xl border border-cyan/20 bg-cyan/5 p-4">
            <div className="grid gap-3 lg:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Качество</label>
                <div className="flex gap-2">
                  {(model?.omni_resolutions || ['720p', '1080p', '4k']).map((resolution) => {
                    const resolutionCost = getVideoModelCost(model, selectedDuration, resolution, repeatCostMultiplier)
                    return (
                      <button
                        key={resolution}
                        type="button"
                        onClick={() => setOmniResolution(resolution)}
                        className={cn(
                          'flex-1 rounded-xl border px-3 py-2 text-xs font-medium leading-tight transition-all duration-200',
                          omniResolution === resolution
                            ? 'border-cyan/50 bg-cyan/15 text-cyan'
                            : 'border-border/50 bg-secondary/40 text-muted-foreground hover:bg-secondary hover:text-foreground'
                        )}
                      >
                        <span className="block">{resolution}</span>
                        <span className="block text-[10px] text-gold">{resolutionCost}🍌</span>
                      </button>
                    )
                  })}
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Seed</label>
                <Input
                  type="number"
                  min="0"
                  max="2147483647"
                  value={omniSeed}
                  onChange={(e) => setOmniSeed(e.target.value)}
                  placeholder="Авто"
                  className="bg-secondary/50 border-border/50"
                />
              </div>
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Audio ID</label>
                <Input
                  value={omniAudioIds}
                  onChange={(e) => setOmniAudioIds(e.target.value)}
                  placeholder="audio_..."
                  className="bg-secondary/50 border-border/50"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Character ID</label>
                <Input
                  value={omniCharacterIds}
                  onChange={(e) => setOmniCharacterIds(e.target.value)}
                  placeholder="character_1, character_2"
                  className="bg-secondary/50 border-border/50"
                />
              </div>
            </div>
            <div className="rounded-xl border border-border/50 bg-background/40 p-3 text-xs text-muted-foreground">
              <div className="flex items-center justify-between gap-3">
                <span>Inputs</span>
                <span className={cn('font-medium', omniOverQuota ? 'text-destructive' : 'text-foreground')}>
                  {omniInputUnits}/7
                </span>
              </div>
              <p className="mt-1">
                Фото: {omniImageCount} · Видео: {omniVideoCount}×2 · Character ID: {parsedOmniCharacterIds.length}
              </p>
              {omniHasVideoReference ? (
                <p className="mt-1 text-cyan">
                  С видео-референсом настройка секунд не фиксирует финальную длину.
                </p>
              ) : null}
            </div>
          </div>
        ) : null}

        {isOmniAudio ? (
          <div className="space-y-4 rounded-2xl border border-cyan/20 bg-cyan/5 p-4">
            <div className="grid gap-3 lg:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Базовый голос</label>
                <select
                  value={omniBaseVoice}
                  onChange={(e) => setOmniBaseVoice(e.target.value)}
                  className="h-10 w-full rounded-xl border border-border/50 bg-secondary/50 px-3 text-sm text-foreground"
                >
                  {(model?.omni_base_voices || ['achernar']).map((voice) => (
                    <option key={voice} value={voice}>{voice}</option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">
                  Имя голоса<span className="text-destructive ml-1">*</span>
                </label>
                <Input
                  maxLength={20}
                  value={omniVoiceName}
                  onChange={(e) => setOmniVoiceName(e.target.value)}
                  placeholder="Например: Рассказчик"
                  className="bg-secondary/50 border-border/50"
                />
              </div>
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Описание голоса</label>
                <Textarea
                  value={omniVoiceDescription}
                  onChange={(e) => setOmniVoiceDescription(e.target.value)}
                  maxLength={2000}
                  className="min-h-24 resize-none bg-secondary/50 border-border/50"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Пример диалога</label>
                <Textarea
                  value={omniExampleDialogue}
                  onChange={(e) => setOmniExampleDialogue(e.target.value)}
                  maxLength={2000}
                  className="min-h-24 resize-none bg-secondary/50 border-border/50"
                />
              </div>
            </div>
          </div>
        ) : null}

        {isOmniCharacter ? (
          <div className="space-y-4 rounded-2xl border border-cyan/20 bg-cyan/5 p-4">
            <div className="grid gap-3 lg:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Имя персонажа</label>
                <Input
                  maxLength={20}
                  value={omniCharacterName}
                  onChange={(e) => setOmniCharacterName(e.target.value)}
                  placeholder="Например: Дженни"
                  className="bg-secondary/50 border-border/50"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Audio ID</label>
                <Input
                  value={omniCharacterAudioIds}
                  onChange={(e) => setOmniCharacterAudioIds(e.target.value)}
                  placeholder="audio_..."
                  className="bg-secondary/50 border-border/50"
                />
              </div>
            </div>
          </div>
        ) : null}

        {!repeatSlots && (selectedScenario === 'character' || selectedScenario === 'avatar') && (
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              {selectedScenario === 'character' ? 'Изображение персонажа' : 'Фото аватара'}
              <span className="text-destructive ml-1">*</span>
            </label>
            <UploadArea
              files={startImage}
              onFilesChange={setStartImage}
              maxFiles={1}
              accept="image/*"
              required
              onUpload={onUploadImageReference}
              libraryFiles={savedImageReferences}
              libraryLabel={selectedScenario === 'character' ? 'Сохранённые изображения персонажей' : 'Сохранённые фото'}
            />
          </div>
        )}

        {!repeatSlots && (selectedScenario === 'video' || selectedScenario === 'edit' || isOmniVideo) && (
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              {selectedScenario === 'edit' ? 'Video1 · исходное видео' : isOmniVideo ? 'Видео-референс' : 'Видео-референсы'}
              {isOmniVideo || (isWanPrime && selectedScenario === 'video') || sourceFeedGenId ? (
                <span className="text-xs text-muted-foreground ml-2">(опционально)</span>
              ) : (
                <span className="text-destructive ml-1">*</span>
              )}
            </label>
          <UploadArea
            files={videoReferences}
            onFilesChange={setVideoReferences}
            maxFiles={isOmniVideo ? 1 : model?.max_video_references || 5}
            accept="video/*"
            required={selectedScenario === 'edit' && !sourceFeedGenId}
            onUpload={onUploadVideoReference}
            libraryFiles={savedVideoReferences}
            libraryLabel="Сохранённые видео-референсы"
          />
          </div>
        )}

        {isWanPrime && selectedScenario === 'first_last' ? (
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              Последний кадр<span className="text-destructive ml-1">*</span>
            </label>
            <UploadArea
              files={wanLastFrame}
              onFilesChange={setWanLastFrame}
              maxFiles={1}
              accept="image/*"
              required
              onUpload={onUploadImageReference}
              libraryFiles={savedImageReferences}
              libraryLabel="Сохранённые фото"
            />
          </div>
        ) : null}

        {selectedScenario === 'avatar' || (isWanPrime && ['video', 'edit', 'file', 'link'].includes(selectedScenario)) ? (
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              {selectedScenario === 'avatar' ? 'Аудио для аватара' : 'Аудио-референсы'}
              {selectedScenario === 'avatar' ? <span className="text-destructive ml-1">*</span> : <span className="text-xs text-muted-foreground ml-2">(опционально)</span>}
            </label>
            <UploadArea
              files={audioReference}
              onFilesChange={setAudioReference}
              maxFiles={isWanPrime ? model?.max_audio_references || 5 : 1}
              accept="audio/*"
              onUpload={onUploadAudioReference}
              libraryFiles={savedAudioReferences}
              libraryLabel="Сохранённые аудио-референсы"
            />
          </div>
        ) : null}

        {!repeatSlots && !isOmniAudio && !isOmniCharacter && ((model?.max_image_references ?? 8) > 0 || selectedScenario === 'imgtxt' || selectedScenario === 'first_last') ? (
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              Фото-референсы
              {(selectedScenario === 'imgtxt' || selectedScenario === 'first_last') && !isOmniVideo && !sourceFeedGenId ? (
                <span className="text-destructive ml-1">*</span>
              ) : (
                <span className="text-xs text-muted-foreground ml-2">(опционально)</span>
              )}
            </label>
            <UploadArea
              files={photoReferences}
              onFilesChange={setPhotoReferences}
              maxFiles={
                selectedScenario === 'first_last'
                  ? 1
                  : selectedScenario === 'imgtxt'
                    ? Math.max(1, model?.max_image_references ?? 0)
                    : model?.max_image_references || 8
              }
              accept="image/*"
              required={(selectedScenario === 'imgtxt' || selectedScenario === 'first_last') && !isOmniVideo && !sourceFeedGenId}
              onUpload={onUploadImageReference}
              libraryFiles={savedImageReferences}
              libraryLabel="Сохранённые фото-референсы"
            />
          </div>
        ) : null}
        {repeatPending ? (
          <div role="status" className="space-y-2 rounded-2xl border border-gold/30 bg-gold/10 p-4">
            <p className="text-sm font-medium">Видео принято, ожидаем подтверждения статуса</p>
            <p className="text-xs text-muted-foreground">Повторный запуск заблокирован, пока история не подтвердит результат этой задачи.</p>
            {onCheckPendingVideo ? <Button type="button" variant="outline" onClick={onCheckPendingVideo}>Проверить в истории</Button> : null}
          </div>
        ) : null}

        {repeatSlots && !repeatPending ? (
          <div role="group" aria-label="Референсы повтора" className="min-w-0 space-y-3 rounded-2xl border border-cyan/25 p-3">
            <p className="text-sm font-medium">Референсы повтора</p>
            {!repeatSlots.available || repeatError ? (
              <p role="alert" className="text-sm text-destructive">Повтор недоступен. Откройте публикацию заново, чтобы проверить разрешения автора.</p>
            ) : (
              <>
                <p className="text-xs text-muted-foreground">Сохранено автором: {typedSlots.filter((slot) => slot.binding === 'fixed').length}</p>
                <p className="text-xs text-muted-foreground">Сохранённые референсы используются скрыто. Загрузите свои файлы для остальных позиций.</p>
                {typedSlots.map((slot) => {
                  const label = `${slot.role === 'first_frame' ? 'Первый кадр · ' : slot.role === 'last_frame' ? 'Последний кадр · ' : ''}${slot.type === 'image' ? 'Фото' : 'Видео'} ${slot.index + 1}`
                  return slot.binding === 'fixed' ? (
                    <p key={slot.key} className="text-xs text-muted-foreground">{label} · Сохранён автором</p>
                  ) : (
                    <fieldset key={`${slotSession}-${slot.key}`} aria-label={label} className="min-w-0 space-y-2" disabled={isSubmitting}>
                      <legend className="text-sm font-medium">{label} · Ваш файл</legend>
                      <UploadArea files={repeatUploads[slot.key] || []}
                        onFilesChange={(files) => {
                          if (slotSession !== repeatSession.current) return
                          setRepeatUploads((current) => ({ ...current, [slot.key]: files }))
                        }}
                        maxFiles={1} accept={`${slot.type}/*`} required
                        onUpload={slot.type === 'image' ? onUploadImageReference : onUploadVideoReference
                          ? (file) => onUploadVideoReference(file, selectedModel) : undefined}
                        libraryFiles={(slot.type === 'image' ? savedImageReferences : savedVideoReferences).filter((file) =>
                          !typedSlots.some((other) => other.key !== slot.key && other.type === slot.type
                            && repeatUploads[other.key]?.some((selected) => selected.url === file.url)))}
                        libraryLabel={slot.type === 'image' ? 'Сохранённые фото' : 'Сохранённые видео'} />
                    </fieldset>
                  )
                })}
              </>
            )}
          </div>
        ) : null}

        <div className="space-y-2">
          {sourceFeedGenId ? (
            <div className="rounded-2xl border border-cyan/25 bg-cyan/10 p-4">
              <p className="text-sm font-medium text-foreground">
                {repeatTitle || 'Повторить видео из ленты'}
              </p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {repeatSlots ? 'Промпт и сохранённые референсы подставляются на сервере. Заполните позиции своими файлами.' : 'Настройки и промпт подставлены. Можно поменять длительность, формат или добавить свои референсы.'}
              </p>
            </div>
          ) : null}
          <label className="text-sm font-medium text-foreground">
            {isOmniAudio ? 'Описание голоса' : isOmniCharacter ? 'Описание персонажа' : 'Промпт'}
          </label>
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder={
              isOmniAudio
                ? 'Спокойный, ясный голос для объясняющих видео...'
                : isOmniCharacter
                  ? 'Коротко опишите внешность, стиль и характер персонажа...'
                  : 'Опишите движение камеры, сцену, свет, ритм, физику движения и желаемый cinematic-эффект...'
            }
            className={cn(
              "min-h-[140px] resize-none",
              "bg-secondary/50 border-border/50",
              "focus:border-cyan/50 focus:ring-cyan/20",
              "placeholder:text-muted-foreground/50"
            )}
          />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {repeatPending
                ? 'Видео принято, статус уточняется'
                : !priceAvailable
                  ? 'Стоимость пока недоступна'
                : repeatBlocked
                ? !repeatSlots?.available || repeatError ? 'Повтор нужно открыть заново' : 'Заполните референсы для повтора'
                : sourceFeedGenId
                ? prompt.trim().length > 0
                  ? 'Промпт из ленты готов к запуску'
                  : 'Промпт скрыт автором, запуск доступен'
                : scenarioSupported
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
            <p className="text-foreground font-medium">
              {selectedScenario === 'text'
                ? 'Текст → Видео'
                : selectedScenario === 'imgtxt'
                  ? 'Фото + Текст'
                  : selectedScenario === 'avatar'
                    ? 'Avatar'
                    : selectedScenario === 'audio'
                      ? 'Audio ID'
                      : selectedScenario === 'character'
                        ? 'Character ID'
                        : 'Видео + Текст'}
            </p>
            <p className="text-muted-foreground mt-1">
              {isOmniAudio || isOmniCharacter
                ? model?.label
                : omniHasVideoReference
                  ? `${selectedRatio} • длина по видео-рефу`
                  : `${selectedRatio} • ${selectedDuration} сек.`}
            </p>
          </div>
          <div className="rounded-xl bg-secondary/40 p-3">
            <p className="text-muted-foreground mb-1">Референсы</p>
            <p className="text-foreground font-medium">
              {repeatSlots ? typedSlots.length : startImage.length + photoReferences.length + videoReferences.length + audioReference.length}
            </p>
            <p className="text-muted-foreground mt-1">
              {model?.grok_modes?.length
                ? `Grok: ${grokMode}`
                : model?.grok_resolutions?.length
                  ? `Grok 1.5: ${grokResolution}`
                  : model?.veo_generation_types?.length
                  ? `Veo: ${veoGenerationType}`
                  : isOmniVideo
                    ? `Качество: ${omniResolution}`
                    : isOmniAudio
                      ? `Голос: ${omniBaseVoice}`
                      : isOmniCharacter
                        ? 'Character ID'
                  : selectedScenario === 'video'
                    ? 'Видео-режим активен'
                    : selectedScenario === 'imgtxt' && !isOmniVideo && !sourceFeedGenId
                      ? 'Фото-референс обязателен'
                      : 'Фото-референсы опциональны'}
            </p>
          </div>
        </div>

        {!priceAvailable ? <p className="text-sm text-muted-foreground">Стоимость недоступна</p> : <div className="flex items-center justify-between">
          <div>
            <span className="text-sm text-muted-foreground">Стоимость</span>
            <p className="text-xs text-muted-foreground/70">
              {isOmniAudio || isOmniCharacter
                ? `${model?.label} • ${cost}🍌`
                : omniHasVideoReference
                  ? `видео-реф • ${selectedRatio} • ${formatPerSecondCost(perSecondCost)}🍌/с`
                  : `${selectedDuration} сек. • ${selectedRatio} • ${formatPerSecondCost(perSecondCost)}🍌/с`}
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            <Banana className="w-4 h-4 text-gold" />
            <span className="text-lg font-semibold text-gold">{cost}</span>
          </div>
        </div>}

        {priceAvailable && !canAfford && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-destructive/10 border border-destructive/30">
            <AlertCircle className="w-4 h-4 text-destructive flex-shrink-0" />
            <p className="text-xs text-destructive">
              Недостаточно бананов. Пополните баланс.
            </p>
          </div>
        )}

        {needsPhotoReference && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-cyan/10 border border-cyan/30">
            <AlertCircle className="w-4 h-4 text-cyan flex-shrink-0" />
            <p className="text-xs text-cyan">Добавьте фото-референс</p>
          </div>
        )}

        {needsCharacterImage && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-cyan/10 border border-cyan/30">
            <AlertCircle className="w-4 h-4 text-cyan flex-shrink-0" />
            <p className="text-xs text-cyan">Добавьте изображение персонажа</p>
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

        {needsAvatarImage && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-cyan/10 border border-cyan/30">
            <AlertCircle className="w-4 h-4 text-cyan flex-shrink-0" />
            <p className="text-xs text-cyan">Загрузите фото аватара</p>
          </div>
        )}

        {needsAvatarAudio && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-cyan/10 border border-cyan/30">
            <AlertCircle className="w-4 h-4 text-cyan flex-shrink-0" />
            <p className="text-xs text-cyan">Загрузите аудио для аватара</p>
          </div>
        )}

        {needsOmniVoiceName && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-cyan/10 border border-cyan/30">
            <AlertCircle className="w-4 h-4 text-cyan flex-shrink-0" />
            <p className="text-xs text-cyan">Укажите имя для Audio ID</p>
          </div>
        )}

        {(omniTooManyVideos || omniTooManyAudioIds || omniTooManyCharacterIds || omniTooManyCharacterAudioIds || omniOverQuota) && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-destructive/10 border border-destructive/30">
            <AlertCircle className="w-4 h-4 text-destructive flex-shrink-0" />
            <p className="text-xs text-destructive">
              {omniOverQuota
                ? 'Слишком много входов для Gemini Omni: фото + видео×2 + Character ID <= 7.'
                : omniTooManyVideos
                  ? 'Gemini Omni принимает только один видео-референс.'
                  : omniTooManyCharacterIds
                    ? 'Gemini Omni принимает максимум 3 Character ID.'
                    : omniTooManyCharacterAudioIds
                      ? 'Character ID принимает один Audio ID.'
                      : 'Gemini Omni Video принимает один Audio ID.'}
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
              {isOmniAudio ? 'Создать Audio ID' : isOmniCharacter ? 'Создать Character ID' : 'Запустить видео'}
            </>
          )}
        </Button>
      </div>
    </div>
  )
}
