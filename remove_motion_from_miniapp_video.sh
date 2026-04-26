#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

# 1) Backend bootstrap: do not expose Motion Control in regular VIDEO_MODELS.
p = Path("bot/miniapp.py")
s = p.read_text(encoding="utf-8")

# Remove motion_control_v26 / motion_control_v30 objects from VIDEO_MODELS tuple/list.
for model_id in ("motion_control_v26", "motion_control_v30", "motion_control"):
    s = re.sub(
        r'\n\s*\{\s*"id"\s*:\s*"' + re.escape(model_id) + r'"[\s\S]*?\n\s*\},',
        '',
        s,
        count=0,
    )

p.write_text(s, encoding="utf-8")

# 2) Frontend: hard filter Motion models from video selector even if backend still returns cached data.
p = Path("frontend/miniapp-v0/components/forms/video-generator-form.tsx")
s = p.read_text(encoding="utf-8")

# Ensure hidden set includes all Motion IDs.
if "hiddenFromCommonVideoList" in s:
    s = re.sub(
        r"new Set\(\[([^\]]*)\]\)",
        lambda m: "new Set([" + m.group(1).strip().rstrip(',') + ", 'motion_control', 'motion_control_v26', 'motion_control_v30'])",
        s,
        count=1,
    )
else:
    needle = "  const model = useMemo(() => models.find(m => m.id === selectedModel), [models, selectedModel])"
    inject = """  const hiddenFromCommonVideoList = new Set(['motion_control', 'motion_control_v26', 'motion_control_v30'])
  const visibleModels = useMemo(
    () => models.filter((item) => !hiddenFromCommonVideoList.has(item.id)),
    [models]
  )

"""
    if needle in s:
        s = s.replace(needle, inject + needle, 1)

# Make selectedModel default skip hidden motion models.
s = re.sub(
    r"const \[selectedModel, setSelectedModel\] = useState\([^\n]+\)",
    "const [selectedModel, setSelectedModel] = useState(models.find((item) => !['motion_control', 'motion_control_v26', 'motion_control_v30'].includes(item.id))?.id || models[0]?.id || '')",
    s,
    count=1,
)

# Use visibleModels in ModelSelect if still using raw models.
s = s.replace("models={models.map(m => ({", "models={visibleModels.map(m => ({", 1)

# Add safety effect: if currently selected model is hidden, switch away.
if "selected model is hidden motion" not in s:
    marker = "  // Reset scenario if not supported\n"
    effect = """  // selected model is hidden motion: switch to first visible video model
  useEffect(() => {
    if (hiddenFromCommonVideoList.has(selectedModel)) {
      const nextModel = visibleModels[0]
      if (nextModel) setSelectedModel(nextModel.id)
    }
  }, [selectedModel, visibleModels])

"""
    if marker in s:
        s = s.replace(marker, effect + marker, 1)

p.write_text(s, encoding="utf-8")

# 3) Frontend mock/fallback data: remove Motion from mock video models if present.
p = Path("frontend/miniapp-v0/lib/mock-data.ts")
if p.exists():
    s = p.read_text(encoding="utf-8")
    for model_id in ("motion_control", "motion_control_v26", "motion_control_v30"):
        s = re.sub(
            r'\n\s*\{\s*id:\s*[\'\"]' + re.escape(model_id) + r'[\'\"][\s\S]*?\n\s*\},',
            '',
            s,
        )
    p.write_text(s, encoding="utf-8")
PY

python3 -m py_compile bot/miniapp.py

cd frontend/miniapp-v0
NEXT_EXPORT=1 npm run build
cd ../..

echo "Motion Control removed from Mini App regular video model list."
echo "Restart bot and fully reopen Telegram Mini App."
