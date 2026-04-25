#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$PROJECT_DIR/frontend/miniapp-v0"
VIDEO_FORM="$APP_DIR/components/forms/video-generator-form.tsx"
VIDEO_TAB="$APP_DIR/components/tabs/video-tab.tsx"
MOTION_TAB="$APP_DIR/components/tabs/motion-tab.tsx"

cd "$PROJECT_DIR"
echo "=== MiniApp patch: avatar audio reference + motion model check ==="

[ -f "$VIDEO_FORM" ] || { echo "Not found: $VIDEO_FORM"; exit 1; }
[ -f "$VIDEO_TAB" ] || { echo "Not found: $VIDEO_TAB"; exit 1; }
[ -f "$MOTION_TAB" ] || { echo "Not found: $MOTION_TAB"; exit 1; }

cp "$VIDEO_FORM" "$VIDEO_FORM.bak.$(date +%Y%m%d_%H%M%S)"
cp "$VIDEO_TAB" "$VIDEO_TAB.bak.$(date +%Y%m%d_%H%M%S)"
cp "$MOTION_TAB" "$MOTION_TAB.bak.$(date +%Y%m%d_%H%M%S)"

python3 - "$VIDEO_FORM" "$VIDEO_TAB" "$MOTION_TAB" <<'PY'
from pathlib import Path
import sys

video_form = Path(sys.argv[1])
video_tab = Path(sys.argv[2])
motion_tab = Path(sys.argv[3])

s = video_form.read_text(encoding='utf-8')

# Types: submit payload gets audioReference.
s = s.replace(
"""    videoReferences: string[]
  }) => Promise<void>""",
"""    videoReferences: string[]
    audioReference: string | null
  }) => Promise<void>"""
)

# Props: uploader callback.
s = s.replace(
"""  onUploadVideoReference?: (file: File) => Promise<UploadedFile>
  isSubmitting: boolean""",
"""  onUploadVideoReference?: (file: File) => Promise<UploadedFile>
  onUploadAudioReference?: (file: File) => Promise<UploadedFile>
  isSubmitting: boolean"""
)

s = s.replace(
"""  onUploadVideoReference,
  isSubmitting,""",
"""  onUploadVideoReference,
  onUploadAudioReference,
  isSubmitting,"""
)

# State.
if "const [audioReference, setAudioReference]" not in s:
    s = s.replace(
"""  const [videoReferences, setVideoReferences] = useState<UploadedFile[]>([])""",
"""  const [videoReferences, setVideoReferences] = useState<UploadedFile[]>([])
  const [audioReference, setAudioReference] = useState<UploadedFile[]>([])"""
)

# Submit payload.
s = s.replace(
"""      videoReferences: videoReferences.map(r => r.url),
    })""",
"""      videoReferences: videoReferences.map(r => r.url),
      audioReference: audioReference[0]?.url || null,
    })"""
)

# Reset.
s = s.replace(
"""    setVideoReferences([])""",
"""    setVideoReferences([])
    setAudioReference([])"""
)

# UI: add audio upload after video refs block if not present.
if "Аудио-референс" not in s:
    marker = """        <div className=\"space-y-2\">
          <label className=\"text-sm font-medium text-foreground\">
            Фото-референсы"""
    audio_block = """        <div className=\"space-y-2\">
          <label className=\"text-sm font-medium text-foreground\">
            Аудио-референс
            <span className=\"text-xs text-muted-foreground ml-2\">(опционально для Avatar Video)</span>
          </label>
          <UploadArea
            files={audioReference}
            onFilesChange={setAudioReference}
            maxFiles={1}
            accept=\"audio/*\"
            onUpload={onUploadAudioReference}
          />
        </div>

"""
    if marker not in s:
        raise SystemExit('Cannot find insert point for audio upload')
    s = s.replace(marker, audio_block + marker, 1)

# Summary count includes audio.
s = s.replace(
"""              {startImage.length + photoReferences.length + videoReferences.length}""",
"""              {startImage.length + photoReferences.length + videoReferences.length + audioReference.length}"""
)

video_form.write_text(s, encoding='utf-8')

# Video tab: payload and uploader.
s = video_tab.read_text(encoding='utf-8')
s = s.replace(
"""    videoReferences: string[]
  }) => {""",
"""    videoReferences: string[]
    audioReference: string | null
  }) => {"""
)

if "handleUploadAudioReference" not in s:
    insert_after = """  const handleUploadVideoReference = async (file: File): Promise<UploadedFile> => {
    if (state.mode !== 'live') {
      return {
        id: `file_${Date.now()}`,
        name: file.name,
        url: '',
        type: 'video',
        size: file.size,
      }
    }
    return uploadFile('video_reference', file)
  }
"""
    audio_fn = """

  const handleUploadAudioReference = async (file: File): Promise<UploadedFile> => {
    if (state.mode !== 'live') {
      return {
        id: `file_${Date.now()}`,
        name: file.name,
        url: '',
        type: 'audio',
        size: file.size,
      }
    }
    return uploadFile('audio_reference', file)
  }
"""
    if insert_after not in s:
        raise SystemExit('Cannot find video upload function')
    s = s.replace(insert_after, insert_after + audio_fn, 1)

s = s.replace(
"""          onUploadVideoReference={handleUploadVideoReference}
          isSubmitting={isSubmitting}""",
"""          onUploadVideoReference={handleUploadVideoReference}
          onUploadAudioReference={handleUploadAudioReference}
          isSubmitting={isSubmitting}"""
)
video_tab.write_text(s, encoding='utf-8')

# Motion: verify model is present in live request.
s = motion_tab.read_text(encoding='utf-8')
if "model: motionModel" not in s:
    s = s.replace("direction,", "direction,\n          model: motionModel,", 1)
if "motion_control_v30" not in s:
    raise SystemExit('Motion model selector not found; manual review needed')
motion_tab.write_text(s, encoding='utf-8')

print('MiniApp files patched')
PY

cd "$APP_DIR"
if command -v pnpm >/dev/null 2>&1; then
  pnpm build
else
  npm run build
fi

echo "OK: MiniApp patched and build completed"
echo "If MiniApp is served by a process manager, restart it now. If it is served by Next standalone, restart that service."
