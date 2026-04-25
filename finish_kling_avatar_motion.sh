#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

# -----------------------------------------------------------------------------
# 1) Kling service: avatar audio/photo + Motion Control 2.6 / 3.0
# -----------------------------------------------------------------------------
p = Path("bot/services/kling_service.py")
s = p.read_text(encoding="utf-8")

s = s.replace(
    'MOTION_MODELS = {"kling-2.6/motion-control", "motion_control"}',
    'MOTION_MODELS = {"kling-2.6/motion-control", "kling-3.0/motion-control", "motion_control", "motion_control_v26", "motion_control_v30"}',
)
s = s.replace(
    'AVATAR_MODELS = {"avatar_std", "avatar_pro"}',
    'AVATAR_MODELS = {"avatar_std", "avatar_pro", "kling_avatar_std", "kling_avatar_pro"}',
)

# make create_kie_motion_task accept model param
s = s.replace(
'''    async def create_kie_motion_task(
        self,
        input_data: Dict[str, Any],
        webhook: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create Kie.ai Kling 2.6 Motion Control task."""
        payload: Dict[str, Any] = {
            "model": "kling-2.6/motion-control",
            "input": input_data,
        }
''',
'''    async def create_kie_motion_task(
        self,
        input_data: Dict[str, Any],
        webhook: Optional[str] = None,
        model: str = "kling-2.6/motion-control",
    ) -> Dict[str, Any]:
        """Create Kie.ai Kling Motion Control task."""
        payload: Dict[str, Any] = {
            "model": model,
            "input": input_data,
        }
''')

# add motion_model parameter to generate_motion_control
s = s.replace(
'''    async def generate_motion_control(
        self,
        *,
        image_url: str,
        video_urls: Optional[List[str]] = None,
        preset_motion: Optional[str] = None,
        prompt: Optional[str] = None,
        motion_direction: str = "video",
        mode: str = "std",
        webhook_url: Optional[str] = None,
    ) -> Dict[str, Any]:
''',
'''    async def generate_motion_control(
        self,
        *,
        image_url: str,
        video_urls: Optional[List[str]] = None,
        preset_motion: Optional[str] = None,
        prompt: Optional[str] = None,
        motion_direction: str = "video",
        mode: str = "std",
        motion_model: str = "kling-2.6/motion-control",
        webhook_url: Optional[str] = None,
    ) -> Dict[str, Any]:
''')

s = s.replace(
'''        return await self.create_kie_motion_task(input_data, webhook_url)
''',
'''        if motion_model not in {"kling-2.6/motion-control", "kling-3.0/motion-control"}:
            motion_model = "kling-2.6/motion-control"

        logger.info(
            "Motion Control payload prepared: model=%s image=%s videos=%s mode=%s direction=%s",
            motion_model,
            bool(image_url),
            len(cleaned_video_urls),
            input_data.get("mode"),
            input_data.get("character_orientation"),
        )
        return await self.create_kie_motion_task(input_data, webhook_url, model=motion_model)
''', 1)

# high-level router model selection for motion_control_v26/v30 and avatar audio_url passthrough
s = s.replace(
'''        if model in self.AVATAR_MODELS:
            return await self.generate_kling_ai_avatar(
                image_url=image_url or "",
                audio_url=(video_urls or [""])[0],
                prompt=prompt or "",
                model=(
                    "kling/ai-avatar-standard"
                    if model == "avatar_std"
                    else "kling/ai-avatar-pro"
                ),
                webhook=webhook_url,
            )
''',
'''        if model in self.AVATAR_MODELS:
            return await self.generate_kling_ai_avatar(
                image_url=image_url or "",
                audio_url=(video_urls or [""])[0],
                prompt=prompt or "",
                model=(
                    "kling/ai-avatar-standard"
                    if model in {"avatar_std", "kling_avatar_std"}
                    else "kling/ai-avatar-pro"
                ),
                webhook=webhook_url,
            )
''')

s = s.replace(
'''        if model in self.MOTION_MODELS or "motion" in model.lower():
            return await self.generate_motion_control(
                image_url=image_url or "",
                video_urls=video_urls or [],
                prompt=prompt,
                motion_direction="video",
                mode="std",
                webhook_url=webhook_url,
            )
''',
'''        if model in self.MOTION_MODELS or "motion" in model.lower():
            motion_model = (
                "kling-3.0/motion-control"
                if model in {"motion_control_v30", "kling-3.0/motion-control"}
                else "kling-2.6/motion-control"
            )
            return await self.generate_motion_control(
                image_url=image_url or "",
                video_urls=video_urls or [],
                prompt=prompt,
                motion_direction="video",
                mode="std",
                motion_model=motion_model,
                webhook_url=webhook_url,
            )
''')

p.write_text(s, encoding="utf-8")

# -----------------------------------------------------------------------------
# 2) Mini App backend: audio upload, avatar models, motion v26/v30
# -----------------------------------------------------------------------------
p = Path("bot/miniapp.py")
s = p.read_text(encoding="utf-8")

# audio upload support
s = s.replace(
'''FILE_KIND_MAP = {
    "image_reference": {"prefix": "image/", "fallback_ext": "png", "group": "image"},
    "video_reference": {"prefix": "video/", "fallback_ext": "mp4", "group": "video"},
}''',
'''FILE_KIND_MAP = {
    "image_reference": {"prefix": "image/", "fallback_ext": "png", "group": "image"},
    "video_reference": {"prefix": "video/", "fallback_ext": "mp4", "group": "video"},
    "audio_reference": {"prefix": "audio/", "fallback_ext": "mp3", "group": "audio"},
}''')

# add motion/avatar video models before VIDEO_MODELS closing tuple
if '"id": "motion_control_v26"' not in s:
    insert_models = '''    {
        "id": "motion_control_v26",
        "label": "Kling 2.6 Motion Control",
        "description": "Перенос движения по фото персонажа и видео движения",
        "durations": [5],
        "ratios": ["motion"],
        "supports": ["motion"],
        "motion_versions": ["2.6"],
        "motion_modes": ["720p", "1080p"],
        "max_image_references": 1,
        "max_video_references": 1,
    },
    {
        "id": "motion_control_v30",
        "label": "Kling 3.0 Motion Control",
        "description": "Улучшенный перенос движения и стабильность лица",
        "durations": [5],
        "ratios": ["motion"],
        "supports": ["motion"],
        "motion_versions": ["3.0"],
        "motion_modes": ["720p", "1080p"],
        "max_image_references": 1,
        "max_video_references": 1,
    },
    {
        "id": "avatar_std",
        "label": "Kling Avatar Standard",
        "description": "Говорящий аватар по фото и аудио",
        "durations": [5],
        "ratios": ["avatar"],
        "supports": ["avatar"],
        "requires_audio": True,
        "requires_image": True,
        "max_image_references": 1,
        "max_audio_references": 1,
    },
    {
        "id": "avatar_pro",
        "label": "Kling Avatar Pro",
        "description": "Качественный говорящий аватар по фото и аудио",
        "durations": [5],
        "ratios": ["avatar"],
        "supports": ["avatar"],
        "requires_audio": True,
        "requires_image": True,
        "max_image_references": 1,
        "max_audio_references": 1,
    },
'''
    marker = '\n)\n\nFILE_KIND_MAP'
    pos = s.find(marker)
    if pos != -1:
        s = s[:pos] + insert_models + s[pos:]

# parse audio_url in generate-video endpoint
s = s.replace(
'''        video_references = list(body.get("v_reference_videos", []) or [])
        grok_mode = str(body.get("grok_mode", "normal") or "normal")''',
'''        video_references = list(body.get("v_reference_videos", []) or [])
        audio_url = str(body.get("audio_url", "") or "") or None
        audio_references = list(body.get("audio_references", []) or [])
        if not audio_url and audio_references:
            audio_url = str(audio_references[0] or "") or None
        grok_mode = str(body.get("grok_mode", "normal") or "normal")''')

# validation avatar/motion support
s = s.replace(
'''        if generation_type == "video" and not video_references:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для режима Видео + Текст нужен хотя бы один видео-референс",
                },
                status=400,
            )''',
'''        if generation_type == "video" and not video_references:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для режима Видео + Текст нужен хотя бы один видео-референс",
                },
                status=400,
            )
        if generation_type == "motion" and (not image_url or not video_references):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для Motion Control загрузите фото персонажа и видео движения",
                },
                status=400,
            )
        if generation_type == "avatar" and (not image_url or not audio_url):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для Kling Avatar загрузите фото персонажа и аудиофайл",
                },
                status=400,
            )''')

# pass audio into _launch_video_generation_task call
s = s.replace(
'''            video_references=video_references,
            grok_mode=grok_mode,''',
'''            video_references=video_references,
            audio_url=audio_url,
            grok_mode=grok_mode,''')

# _launch_video_generation_task signature add audio_url
s = s.replace(
'''    video_references: list[str],
    grok_mode: str = "normal",''',
'''    video_references: list[str],
    audio_url: str | None = None,
    grok_mode: str = "normal",''')

# branch in launcher for avatar/motion before grok/video default
s = s.replace(
'''    if model == "grok_imagine":
        result = await grok_service.generate_image_to_video(''',
'''    if model in {"avatar_std", "avatar_pro"}:
        result = await kling_service.generate_video(
            prompt=prompt,
            model=model,
            duration=duration,
            aspect_ratio=normalized_ratio,
            image_url=image_url,
            video_urls=[audio_url] if audio_url else [],
            webhook_url=callback_url,
        )
    elif model in {"motion_control_v26", "motion_control_v30"}:
        result = await kling_service.generate_video(
            prompt=prompt,
            model=model,
            duration=duration,
            aspect_ratio=normalized_ratio,
            image_url=image_url,
            video_urls=video_references[:1],
            webhook_url=callback_url,
        )
    elif model == "grok_imagine":
        result = await grok_service.generate_image_to_video(''')

# include audio in request data when queued
s = s.replace(
'''                "v_reference_videos": video_references,
                "grok_mode": grok_mode,''',
'''                "v_reference_videos": video_references,
                "audio_url": audio_url,
                "grok_mode": grok_mode,''')

p.write_text(s, encoding="utf-8")

# -----------------------------------------------------------------------------
# 3) Frontend API: audio upload + motion model payload
# -----------------------------------------------------------------------------
p = Path("frontend/miniapp-v0/lib/api.ts")
if p.exists():
    s = p.read_text(encoding="utf-8")
    s = s.replace(
        "fileKind: 'image_reference' | 'video_reference',",
        "fileKind: 'image_reference' | 'video_reference' | 'audio_reference',",
    )
    # generateMotion payload: add optional model and send motion type
    s = s.replace(
'''export async function generateMotion(payload: {
  imageUrl: string
  videoUrl: string
  prompt: string
  mode: string
  direction: string
}): Promise<{''',
'''export async function generateMotion(payload: {
  imageUrl: string
  videoUrl: string
  prompt: string
  mode: string
  direction: string
  model?: string
}): Promise<{''')
    s = s.replace(
'''    v_model: 'motion_control',
    v_type: 'imgtxt',''',
'''    v_model: payload.model || 'motion_control_v26',
    v_type: 'motion',''')
    p.write_text(s, encoding="utf-8")

# -----------------------------------------------------------------------------
# 4) Frontend Motion tab: add explicit Kling 2.6 / 3.0 switch
# -----------------------------------------------------------------------------
p = Path("frontend/miniapp-v0/components/tabs/motion-tab.tsx")
if p.exists():
    s = p.read_text(encoding="utf-8")
    if "type MotionModel" not in s:
        s = s.replace(
            "type MotionMode = '720p' | '1080p'\n",
            "type MotionMode = '720p' | '1080p'\ntype MotionModel = 'motion_control_v26' | 'motion_control_v30'\n",
        )
    if "const [motionModel" not in s:
        s = s.replace(
            "  const [motionVideo, setMotionVideo] = useState<UploadedFile | null>(null)\n",
            "  const [motionVideo, setMotionVideo] = useState<UploadedFile | null>(null)\n  const [motionModel, setMotionModel] = useState<MotionModel>('motion_control_v26')\n",
        )
    s = s.replace(
'''          mode,
          direction,
        })''',
'''          mode,
          direction,
          model: motionModel,
        })''')
    # insert model selector before quality settings if not inserted
    if "Версия Kling" not in s:
        s = s.replace(
'''            <div className="space-y-3">
              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Качество
''',
'''            <div className="space-y-3">
              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Версия Kling
                </p>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { id: 'motion_control_v26' as const, label: 'Kling 2.6' },
                    { id: 'motion_control_v30' as const, label: 'Kling 3.0' },
                  ].map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setMotionModel(item.id)}
                      className={cn(
                        'rounded-2xl border px-4 py-3 text-sm font-medium transition-all',
                        motionModel === item.id
                          ? 'border-gold/60 bg-gold/10 text-gold'
                          : 'border-border/70 bg-background/40 text-muted-foreground'
                      )}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Качество
''')
    s = s.replace("<strong>Kling Motion</strong>", "<strong>{motionModel === 'motion_control_v30' ? 'Kling 3.0 Motion' : 'Kling 2.6 Motion'}</strong>")
    p.write_text(s, encoding="utf-8")

PY

python3 -m py_compile bot/services/kling_service.py bot/miniapp.py

if [ -d frontend/miniapp-v0 ]; then
  cd frontend/miniapp-v0
  npm run build || true
  cd ../..
fi

echo "Kling Avatar + Motion Control 2.6/3.0 integration patch applied."
echo "Recommended checks:"
echo "  grep -R 'motion_control_v30\|audio_reference\|avatar_std' -n bot frontend/miniapp-v0 | head -80"
