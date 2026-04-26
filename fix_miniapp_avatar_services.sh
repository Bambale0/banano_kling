#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path

# -----------------------------------------------------------------------------
# 1) Service grid: add Avatar to Mini App services
# -----------------------------------------------------------------------------
p = Path("frontend/miniapp-v0/components/service-grid.tsx")
s = p.read_text(encoding="utf-8")

if "Mic2" not in s:
    s = s.replace("  ArrowRight,\n} from 'lucide-react'", "  ArrowRight,\n  Mic2,\n} from 'lucide-react'", 1)

if "id: 'avatar'" not in s:
    avatar_block = """  {
    id: 'avatar',
    icon: Mic2,
    title: 'Avatar',
    description: 'Говорящий аватар: загрузите фото персонажа и аудио.',
    badge: 'Фото + аудио',
    tone: 'cyan',
  },
"""
    # Put avatar after prompt-by-photo card.
    marker = """  {
    id: 'edit-photo',"""
    if marker in s:
        s = s.replace(marker, avatar_block + marker, 1)

s = s.replace("<span className=\"text-xs text-muted-foreground\">4 сценария</span>", "<span className=\"text-xs text-muted-foreground\">5 сценариев</span>")
p.write_text(s, encoding="utf-8")

# -----------------------------------------------------------------------------
# 2) Services tab: Avatar opens Video tab with avatar_pro selected
# -----------------------------------------------------------------------------
p = Path("frontend/miniapp-v0/components/tabs/services-tab.tsx")
s = p.read_text(encoding="utf-8")

if "avatar: {" not in s:
    insert = """  avatar: {
    title: 'Avatar',
    tab: 2,
    message: 'Открываю Avatar: фото персонажа + аудио.',
  },
"""
    marker = """  'edit-photo': {"""
    s = s.replace(marker, insert + marker, 1)

old = """    if (typeof config.tab === 'number') {
      setActiveTab(config.tab)
    }
"""
new = """    if (serviceId === 'avatar' && typeof window !== 'undefined') {
      window.localStorage.setItem('miniapp_requested_video_model', 'avatar_pro')
      window.localStorage.setItem('miniapp_requested_video_scenario', 'avatar')
    }

    if (typeof config.tab === 'number') {
      setActiveTab(config.tab)
    }
"""
if "miniapp_requested_video_model" not in s:
    s = s.replace(old, new, 1)

p.write_text(s, encoding="utf-8")

# -----------------------------------------------------------------------------
# 3) Video form: hide Avatar/Motion from common video list, but allow Avatar from Services
# -----------------------------------------------------------------------------
p = Path("frontend/miniapp-v0/components/forms/video-generator-form.tsx")
s = p.read_text(encoding="utf-8")

# Add hidden-model helper after audio state.
needle = """  const [audioReference, setAudioReference] = useState<UploadedFile[]>([])

  const model = useMemo(() => models.find(m => m.id === selectedModel), [models, selectedModel])
"""
replacement = """  const [audioReference, setAudioReference] = useState<UploadedFile[]>([])

  const hiddenFromCommonVideoList = new Set(['avatar_std', 'avatar_pro', 'motion_control', 'motion_control_v26', 'motion_control_v30'])
  const regularVideoModels = useMemo(
    () => models.filter((item) => !hiddenFromCommonVideoList.has(item.id)),
    [models]
  )
  const requestedServiceModel = hiddenFromCommonVideoList.has(selectedModel)
    ? models.filter((item) => item.id === selectedModel)
    : []
  const visibleModels = requestedServiceModel.length
    ? [...requestedServiceModel, ...regularVideoModels]
    : regularVideoModels

  const model = useMemo(() => models.find(m => m.id === selectedModel), [models, selectedModel])
"""
if "hiddenFromCommonVideoList" not in s:
    s = s.replace(needle, replacement, 1)

# Default selected model should not be avatar/motion.
s = s.replace(
    "const [selectedModel, setSelectedModel] = useState(models[0]?.id || '')",
    "const [selectedModel, setSelectedModel] = useState(models.find((item) => !['avatar_std', 'avatar_pro', 'motion_control', 'motion_control_v26', 'motion_control_v30'].includes(item.id))?.id || models[0]?.id || '')",
    1,
)

# Consume service request from localStorage.
if "consume requested Avatar service" not in s:
    anchor = """  // Reset scenario if not supported
  useEffect(() => {
"""
    block = """  // consume requested Avatar service
  useEffect(() => {
    if (typeof window === 'undefined') return
    const requestedModel = window.localStorage.getItem('miniapp_requested_video_model')
    const requestedScenario = window.localStorage.getItem('miniapp_requested_video_scenario')
    if (requestedModel && models.some((item) => item.id === requestedModel)) {
      setSelectedModel(requestedModel)
      if (requestedScenario) setSelectedScenario(requestedScenario as ScenarioType)
      window.localStorage.removeItem('miniapp_requested_video_model')
      window.localStorage.removeItem('miniapp_requested_video_scenario')
    }
  }, [models])

"""
    s = s.replace(anchor, block + anchor, 1)

# Use visibleModels in select.
s = s.replace("models={models.map(m => ({", "models={visibleModels.map(m => ({", 1)

# Make avatar validation require image + audio, not just prompt.
if "needsAvatarImage" not in s:
    s = s.replace(
        "  const needsVideoRef = selectedScenario === 'video' && videoReferences.length === 0\n  \n  const isValid = prompt.trim().length > 0 && ",
        "  const needsVideoRef = selectedScenario === 'video' && videoReferences.length === 0\n  const needsAvatarImage = selectedScenario === 'avatar' && startImage.length === 0\n  const needsAvatarAudio = selectedScenario === 'avatar' && audioReference.length === 0\n  \n  const isValid = prompt.trim().length > 0 && ",
        1,
    )
    s = s.replace(
        "    !needsStartImage && \n    !needsVideoRef",
        "    !needsStartImage && \n    !needsVideoRef &&\n    !needsAvatarImage &&\n    !needsAvatarAudio",
        1,
    )

# Render avatar photo upload using existing startImage slot.
if "selectedScenario === 'avatar'" not in s:
    marker = """        {selectedScenario === 'imgtxt' && (
          <div className="space-y-2">
"""
    avatar_upload = """        {selectedScenario === 'avatar' && (
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              Фото аватара
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

"""
    s = s.replace(marker, avatar_upload + marker, 1)

# Make audio label required for avatar.
s = s.replace(
    """            Аудио-референс
            <span className="text-xs text-muted-foreground ml-2">(опционально для Avatar Video)</span>""",
    """            {selectedScenario === 'avatar' ? 'Аудио для аватара' : 'Аудио-референс'}
            {selectedScenario === 'avatar' ? <span className="text-destructive ml-1">*</span> : <span className="text-xs text-muted-foreground ml-2">(опционально)</span>}""",
)

# Human readable scenario chips/summary for avatar.
s = s.replace(
    "scenario === 'text' ? 'Текст → Видео' : scenario === 'imgtxt' ? 'Фото + Текст' : 'Видео + Текст'",
    "scenario === 'text' ? 'Текст → Видео' : scenario === 'imgtxt' ? 'Фото + Текст' : scenario === 'avatar' ? 'Avatar' : 'Видео + Текст'",
)
s = s.replace(
    "selectedScenario === 'text' ? 'Текст → Видео' : selectedScenario === 'imgtxt' ? 'Фото + Текст' : 'Видео + Текст'",
    "selectedScenario === 'text' ? 'Текст → Видео' : selectedScenario === 'imgtxt' ? 'Фото + Текст' : selectedScenario === 'avatar' ? 'Avatar' : 'Видео + Текст'",
)

# Show avatar validation warnings.
if "needsAvatarAudio &&" not in s:
    marker = """        {needsVideoRef && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-cyan/10 border border-cyan/30">
            <AlertCircle className="w-4 h-4 text-cyan flex-shrink-0" />
            <p className="text-xs text-cyan">
              Загрузите видео-референс
            </p>
          </div>
        )}

"""
    warnings = marker + """        {needsAvatarImage && (
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

"""
    s = s.replace(marker, warnings, 1)

p.write_text(s, encoding="utf-8")
PY

# Validate and build export.
cd frontend/miniapp-v0
npm run build
cd ../..

echo "Mini App Avatar service patch applied."
echo "Now restart bot and fully reopen Telegram Mini App."
