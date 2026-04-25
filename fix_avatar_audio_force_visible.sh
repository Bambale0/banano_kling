#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$PROJECT_DIR/frontend/miniapp-v0"
FORM="$APP_DIR/components/forms/video-generator-form.tsx"
API="$APP_DIR/lib/api.ts"
TYPES="$APP_DIR/lib/types.ts"
UPLOAD="$APP_DIR/components/forms/upload-area.tsx"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$PROJECT_DIR/gpt_avatar_audio_force_${TS}.txt"

cd "$PROJECT_DIR"
echo "=== Force avatar audio upload visible ==="

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
if 'audioReference' not in s:
    s = s.replace('    videoReferences: string[]\n', '    videoReferences: string[]\n    audioReference: string | null\n')
    s = s.replace('  onUploadVideoReference?: (file: File) => Promise<UploadedFile>\n', '  onUploadVideoReference?: (file: File) => Promise<UploadedFile>\n  onUploadAudioReference?: (file: File) => Promise<UploadedFile>\n')
    s = s.replace('  onUploadVideoReference,\n', '  onUploadVideoReference,\n  onUploadAudioReference,\n')
    s = s.replace('  const [videoReferences, setVideoReferences] = useState<UploadedFile[]>([])', '  const [videoReferences, setVideoReferences] = useState<UploadedFile[]>([])\n  const [audioReference, setAudioReference] = useState<UploadedFile[]>([])')
    s = s.replace('      videoReferences: videoReferences.map(r => r.url),\n', '      videoReferences: videoReferences.map(r => r.url),\n      audioReference: audioReference[0]?.url || null,\n')
    s = s.replace('    setVideoReferences([])', '    setVideoReferences([])\n    setAudioReference([])')

# Always show the audio upload block after video refs / before photo refs.
if 'Аудио-референс' not in s:
    marker = '        <div className="space-y-2">\n          <label className="text-sm font-medium text-foreground">\n            Фото-референсы'
    block = '''        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">
            Аудио-референс
            <span className="text-xs text-muted-foreground ml-2">(опционально для Avatar Video)</span>
          </label>
          <UploadArea
            files={audioReference}
            onFilesChange={setAudioReference}
            maxFiles={1}
            accept="audio/*"
            onUpload={onUploadAudioReference}
          />
        </div>

'''
    if marker not in s:
        raise SystemExit('insert marker not found')
    s = s.replace(marker, block + marker, 1)
else:
    # Remove broken conditional wrapper if it was added by older patch.
    s = s.replace('        {supportsAudioReference && (\n        <div className="space-y-2">\n          <label className="text-sm font-medium text-foreground">\n            Аудио-референс', '        <div className="space-y-2">\n          <label className="text-sm font-medium text-foreground">\n            Аудио-референс')
    s = s.replace('          />\n        </div>\n        )}\n\n        <div className="space-y-2">\n          <label className="text-sm font-medium text-foreground">\n            Фото-референсы', '          />\n        </div>\n\n        <div className="space-y-2">\n          <label className="text-sm font-medium text-foreground">\n            Фото-референсы')

s = re.sub(r'\n  const supportsAudioReference = .*', '', s)
s = s.replace('{startImage.length + photoReferences.length + videoReferences.length}', '{startImage.length + photoReferences.length + videoReferences.length + audioReference.length}')
form.write_text(s, encoding='utf-8')

s = api.read_text(encoding='utf-8')
s = s.replace("kind: 'image' | 'video'", "kind: 'image' | 'video' | 'audio'")
if 'audioReference' not in s[s.find('export async function generateVideo'):s.find('export async function generateMotion') if 'export async function generateMotion' in s else len(s)]:
    s = s.replace('  videoReferences: string[]\n}', '  videoReferences: string[]\n  audioReference?: string | null\n}')
if 'audio_reference:' not in s:
    s = s.replace('    v_reference_videos: payload.videoReferences,', '    v_reference_videos: payload.videoReferences,\n    audio_reference: payload.audioReference || \'\',')
api.write_text(s, encoding='utf-8')

s = types.read_text(encoding='utf-8')
s = s.replace("type: 'image' | 'video'", "type: 'image' | 'video' | 'audio'")
types.write_text(s, encoding='utf-8')

s = upload.read_text(encoding='utf-8')
s = s.replace("import { Upload, X, Loader2, Image as ImageIcon, Video } from 'lucide-react'", "import { Upload, X, Loader2, Image as ImageIcon, Video, Music } from 'lucide-react'")
if "accept.startsWith('audio/')" not in s:
    s = s.replace("""      if (accept.startsWith('video/') && !file.type.startsWith('video/')) {
        setError('Загрузите видео-файл')
        continue
      }""", """      if (accept.startsWith('video/') && !file.type.startsWith('video/')) {
        setError('Загрузите видео-файл')
        continue
      }
      if (accept.startsWith('audio/') && !file.type.startsWith('audio/')) {
        setError('Загрузите аудио-файл')
        continue
      }""")
s = s.replace("type: file.type.startsWith('video') ? 'video' : 'image'", "type: file.type.startsWith('video') ? 'video' : file.type.startsWith('audio') ? 'audio' : 'image'")
if '<Music className=' not in s:
    s = s.replace("{file.type === 'video' ? (", "{file.type === 'audio' ? (\n                    <Music className=\"w-4 h-4 text-gold\" />\n                  ) : file.type === 'video' ? (")
upload.write_text(s, encoding='utf-8')
PY

cd "$APP_DIR"
rm -rf .next
if command -v pnpm >/dev/null 2>&1; then pnpm build > "$OUT" 2>&1; else npm run build > "$OUT" 2>&1; fi

grep -Rni "Аудио-референс\|audioReference\|audio_reference" components/forms/video-generator-form.tsx lib/api.ts > "$PROJECT_DIR/gpt_avatar_audio_check_${TS}.txt" || true
echo "Build log: $OUT"
echo "Check: $PROJECT_DIR/gpt_avatar_audio_check_${TS}.txt"
echo "OK. Now restart the MiniApp frontend service, not only bot restart.sh."
