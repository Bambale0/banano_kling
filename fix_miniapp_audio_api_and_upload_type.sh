#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$PROJECT_DIR/frontend/miniapp-v0"
API="$APP_DIR/lib/api.ts"
TYPES="$APP_DIR/lib/types.ts"
UPLOAD="$APP_DIR/components/forms/upload-area.tsx"
FORM="$APP_DIR/components/forms/video-generator-form.tsx"

cd "$PROJECT_DIR"
echo "=== Fix MiniApp audio API + upload type ==="
for f in "$API" "$TYPES" "$UPLOAD" "$FORM"; do
  [ -f "$f" ] || { echo "Not found: $f"; exit 1; }
  cp "$f" "$f.bak.$(date +%Y%m%d_%H%M%S)"
done

python3 - "$API" "$TYPES" "$UPLOAD" "$FORM" <<'PY'
from pathlib import Path
import sys
api, types, upload, form = map(Path, sys.argv[1:])

s = types.read_text(encoding='utf-8')
s = s.replace("type: 'image' | 'video'", "type: 'image' | 'video' | 'audio'")
s = s.replace("v_reference_videos?: string[]", "v_reference_videos?: string[]\n    audio_reference?: string | null")
types.write_text(s, encoding='utf-8')

s = api.read_text(encoding='utf-8')
s = s.replace("kind: 'image' | 'video'", "kind: 'image' | 'video' | 'audio'")
s = s.replace("videoReferences: string[]\n}", "videoReferences: string[]\n  audioReference?: string | null\n}")
s = s.replace(
"""    v_reference_videos: payload.videoReferences,
  })""",
"""    v_reference_videos: payload.videoReferences,
    audio_reference: payload.audioReference || '',
  })"""
)
s = s.replace(
"""            request_data: { reference_images: payload.references },""",
"""            request_data: { reference_images: payload.references, audio_reference: payload.audioReference || null },"""
)
api.write_text(s, encoding='utf-8')

s = upload.read_text(encoding='utf-8')
s = s.replace("import { Upload, X, Loader2, Image as ImageIcon, Video } from 'lucide-react'", "import { Upload, X, Loader2, Image as ImageIcon, Video, Music } from 'lucide-react'")
# validation audio
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
      }"""
)
s = s.replace("type: file.type.startsWith('video') ? 'video' : 'image'", "type: file.type.startsWith('video') ? 'video' : file.type.startsWith('audio') ? 'audio' : 'image'")
s = s.replace("{file.type === 'video' ? (", "{file.type === 'audio' ? (\n                    <Music className=\"w-4 h-4 text-gold\" />\n                  ) : file.type === 'video' ? (")
s = s.replace("MP4, MOV и другие video-файлы. Держите короткие и чистые референсы для лучшего результата.", "MP3, WAV, M4A или MP4/MOV для видео-референсов. Держите референсы короткими и чистыми.")
upload.write_text(s, encoding='utf-8')

s = form.read_text(encoding='utf-8')
# Hide audio block unless model looks like avatar/talking model. This avoids showing audio on every video model.
if "const supportsAudioReference" not in s:
    s = s.replace(
"""  const needsVideoRef = selectedScenario === 'video' && videoReferences.length === 0""",
"""  const needsVideoRef = selectedScenario === 'video' && videoReferences.length === 0
  const supportsAudioReference = Boolean(model && /avatar|talk|lip|voice/i.test(`${model.id} ${model.label} ${model.description}`))"""
)
s = s.replace(
"""        <div className=\"space-y-2\">
          <label className=\"text-sm font-medium text-foreground\">
            Аудио-референс""",
"""        {supportsAudioReference && (
        <div className=\"space-y-2\">
          <label className=\"text-sm font-medium text-foreground\">
            Аудио-референс"""
)
s = s.replace(
"""          />
        </div>

        <div className=\"space-y-2\">
          <label className=\"text-sm font-medium text-foreground\">
            Фото-референсы""",
"""          />
        </div>
        )}

        <div className=\"space-y-2\">
          <label className=\"text-sm font-medium text-foreground\">
            Фото-референсы"""
)
form.write_text(s, encoding='utf-8')
PY

cd "$APP_DIR"
if command -v pnpm >/dev/null 2>&1; then pnpm build; else npm run build; fi

echo "OK: audio API/upload patch applied and build completed"
