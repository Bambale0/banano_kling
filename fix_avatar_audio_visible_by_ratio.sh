#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$PROJECT_DIR/frontend/miniapp-v0"
FORM="$APP_DIR/components/forms/video-generator-form.tsx"
API="$APP_DIR/lib/api.ts"
TYPES="$APP_DIR/lib/types.ts"
UPLOAD="$APP_DIR/components/forms/upload-area.tsx"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$PROJECT_DIR/gpt_avatar_audio_fix_${TS}.txt"

cd "$PROJECT_DIR"
echo "=== Fix Avatar audio visible by ratio ==="

for f in "$FORM" "$API" "$TYPES" "$UPLOAD"; do
  [ -f "$f" ] || { echo "Not found: $f"; exit 1; }
  cp "$f" "$f.bak.$TS"
done

python3 - "$FORM" "$API" "$TYPES" "$UPLOAD" <<'PY'
from pathlib import Path
import re
import sys

form, api, types, upload = map(Path, sys.argv[1:])

s = form.read_text(encoding='utf-8')
# Make audio visible for Avatar by selected ratio too. This matches the current UI where format is "avatar".
s = re.sub(
    r"const supportsAudioReference = Boolean\([^\n]+\)",
    "const supportsAudioReference = Boolean(model && (selectedRatio === 'avatar' || model.ratios?.includes('avatar') || /avatar|talk|lip|voice/i.test(`${model.id} ${model.label} ${model.description}`)))",
    s,
)
if "const supportsAudioReference" not in s:
    s = s.replace(
        "const needsVideoRef = selectedScenario === 'video' && videoReferences.length === 0",
        "const needsVideoRef = selectedScenario === 'video' && videoReferences.length === 0\n  const supportsAudioReference = Boolean(model && (selectedRatio === 'avatar' || model.ratios?.includes('avatar') || /avatar|talk|lip|voice/i.test(`${model.id} ${model.label} ${model.description}`)))",
    )
# If previous script didn't add block, fail loudly.
if "Аудио-референс" not in s:
    raise SystemExit('Audio upload block is missing in video-generator-form.tsx. Run fix_miniapp_avatar_audio_motion_model.sh first.')
form.write_text(s, encoding='utf-8')

# Ensure API accepts/sends audioReference.
s = api.read_text(encoding='utf-8')
if "audioReference" not in s:
    s = s.replace("videoReferences: string[]\n}", "videoReferences: string[]\n  audioReference?: string | null\n}")
if "audio_reference:" not in s:
    s = s.replace("v_reference_videos: payload.videoReferences,", "v_reference_videos: payload.videoReferences,\n    audio_reference: payload.audioReference || '',")
api.write_text(s, encoding='utf-8')

# Ensure UploadedFile supports audio.
s = types.read_text(encoding='utf-8')
s = s.replace("type: 'image' | 'video'", "type: 'image' | 'video' | 'audio'")
types.write_text(s, encoding='utf-8')

# Ensure UploadArea accepts audio MIME and sets type audio.
s = upload.read_text(encoding='utf-8')
if "Music" not in s:
    s = s.replace("import { Upload, X, Loader2, Image as ImageIcon, Video } from 'lucide-react'", "import { Upload, X, Loader2, Image as ImageIcon, Video, Music } from 'lucide-react'")
if "accept.startsWith('audio/')" not in s:
    s = s.replace(
        """      if (accept.startsWith('video/') && !file.type.startsWith('video/')) {
        setError('Загрузите видео-файл')
        continue
      }""",
        """      if (accept.startsWith('video/') && !file.type.startsWith('video/')) {
        setError('Загрузите видео-файл')
        continue
      }
      if (accept.startsWith('audio/') && !file.type.startsWith('audio/')) {
        setError('Загрузите аудио-файл')
        continue
      }""",
    )
s = s.replace("type: file.type.startsWith('video') ? 'video' : 'image'", "type: file.type.startsWith('video') ? 'video' : file.type.startsWith('audio') ? 'audio' : 'image'")
upload.write_text(s, encoding='utf-8')
PY

cd "$APP_DIR"
if command -v pnpm >/dev/null 2>&1; then
  pnpm build > "$OUT" 2>&1
else
  npm run build > "$OUT" 2>&1
fi

echo "Build log: $OUT"
echo "OK: Avatar audio visibility patched. Restart Mini App frontend process if it is managed separately."
