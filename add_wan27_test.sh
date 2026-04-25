#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

cat > bot/services/wan27_service.py <<'PY'
"""Wan 2.7 Image service via Kie.ai."""

import logging
from typing import Dict, List, Optional

from bot.config import config
from bot.services.kling_service import KlingService
from bot.services.media_input_utils import image_sources_to_provider_safe_png_urls

logger = logging.getLogger(__name__)


class Wan27Service(KlingService):
    """Wrapper for Wan 2.7 Image / Image Pro through Kie.ai createTask."""

    async def generate_image(
        self,
        *,
        prompt: str,
        aspect_ratio: str = "1:1",
        input_urls: Optional[List[str]] = None,
        n: int = 1,
        resolution: str = "2K",
        pro: bool = True,
        enable_sequential: bool = False,
        thinking_mode: bool = False,
        watermark: bool = False,
        seed: int = 0,
        nsfw_checker: bool = False,
        callBackUrl: Optional[str] = None,
    ) -> Optional[Dict]:
        cleaned_urls = image_sources_to_provider_safe_png_urls(input_urls or [])[:9]
        model = "wan/2-7-image-pro" if pro else "wan/2-7-image"

        # Docs: thinking_mode is only for text-to-image, non-sequential.
        if cleaned_urls or enable_sequential:
            thinking_mode = False

        if enable_sequential:
            n = max(1, min(int(n or 12), 12))
        else:
            n = max(1, min(int(n or 1), 4))

        input_data = {
            "prompt": str(prompt or "").strip()[:5000],
            "aspect_ratio": aspect_ratio,
            "enable_sequential": bool(enable_sequential),
            "n": n,
            "resolution": resolution,
            "thinking_mode": bool(thinking_mode),
            "watermark": bool(watermark),
            "seed": int(seed or 0),
            "nsfw_checker": False,
        }

        if cleaned_urls:
            input_data["input_urls"] = cleaned_urls
            input_data["bbox_list"] = [[] for _ in cleaned_urls]

        payload = {
            "model": model,
            "input": input_data,
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl

        logger.info(
            "Wan 2.7 payload prepared: model=%s refs=%s ratio=%s n=%s resolution=%s thinking=%s",
            model,
            len(cleaned_urls),
            aspect_ratio,
            n,
            resolution,
            thinking_mode,
        )
        return await self._kie_post("/api/v1/jobs/createTask", payload)


wan27_service = Wan27Service(kie_key=config.KIE_AI_API_KEY)
PY

python3 - <<'PY'
from pathlib import Path

# 1. preset aliases / fallback costs
p = Path("bot/services/preset_manager.py")
s = p.read_text(encoding="utf-8")
if '"wan_27": "wan_27"' not in s:
    # Insert near other aliases in dict.
    s = s.replace(
        '"grok_imagine_i2i": "grok_imagine_i2i",',
        '"grok_imagine_i2i": "grok_imagine_i2i",\n    "wan_27": "wan_27",\n    "wan27": "wan_27",\n    "wan-2.7": "wan_27",',
    )
# If cost map exists and wan not present, add near grok fallback.
if '"wan_27"' not in s[s.find("FALLBACK") if "FALLBACK" in s else 0:]:
    s = s.replace(
        '"grok_imagine_i2i": 7,',
        '"grok_imagine_i2i": 7,\n    "wan_27": 7,',
    )
p.write_text(s, encoding="utf-8")

# 2. keyboards labels/buttons
p = Path("bot/keyboards.py")
s = p.read_text(encoding="utf-8")
s = s.replace(
    '"grok_imagine_i2i": "Grok Imagine",',
    '"grok_imagine_i2i": "Grok Imagine",\n    "wan_27": "Wan 2.7 Pro",',
)
# Add to image model selection list after grok if a list contains grok_imagine_i2i.
s = s.replace(
    '"grok_imagine_i2i",',
    '"grok_imagine_i2i",\n            "wan_27",',
    1,
)
p.write_text(s, encoding="utf-8")

# 3. generation routing
p = Path("bot/handlers/generation.py")
s = p.read_text(encoding="utf-8")

if "from bot.services.wan27_service import wan27_service" not in s:
    s = s.replace(
        "from bot.services.seedream_service import seedream_service",
        "from bot.services.seedream_service import seedream_service\nfrom bot.services.wan27_service import wan27_service",
    )

s = s.replace(
    'if img_service == "grok_imagine_i2i":\n        return "grok-imagine-image-to-image"',
    'if img_service == "grok_imagine_i2i":\n        return "grok-imagine-image-to-image"\n    if img_service == "wan_27":\n        return "wan/2-7-image-pro"',
)

# Extend safe prompt framing eligibility.
s = s.replace(
    'if img_service not in {"banana_pro", "banana_2", "nanobanana", "grok_imagine_i2i"}:',
    'if img_service not in {"banana_pro", "banana_2", "nanobanana", "grok_imagine_i2i", "wan_27"}:',
)

route_marker = '''    elif runtime_img_service == "grok_imagine_i2i":
        result = await grok_service.generate_image_to_image(
            image_urls=reference_images,
            prompt=effective_prompt,
            nsfw_checker=nsfw_enabled,
            callBackUrl=callback_url,
        )
'''
if 'runtime_img_service == "wan_27"' not in s:
    insert = route_marker + '''    elif runtime_img_service == "wan_27":
        result = await wan27_service.generate_image(
            prompt=effective_prompt,
            aspect_ratio=img_ratio,
            input_urls=reference_images,
            n=1,
            resolution="2K",
            pro=True,
            enable_sequential=False,
            thinking_mode=False,
            watermark=False,
            seed=random.randint(1, 2147483647),
            nsfw_checker=False,
            callBackUrl=callback_url,
        )
'''
    if route_marker not in s:
        raise SystemExit("Could not find grok route marker in generation.py")
    s = s.replace(route_marker, insert)

# Add simple main callback button handler if main image callbacks exist.
if 'F.data == "main_img_wan_27"' not in s:
    marker = '''@router.callback_query(F.data == "main_img_grok")
async def show_main_img_grok(callback: types.CallbackQuery, state: FSMContext):
    await _open_image_model_from_main(
        callback, state, model="grok_imagine_i2i", upload_first=True
    )
'''
    add = marker + '''

@router.callback_query(F.data == "main_img_wan_27")
async def show_main_img_wan_27(callback: types.CallbackQuery, state: FSMContext):
    await _open_image_model_from_main(callback, state, model="wan_27")
'''
    if marker in s:
        s = s.replace(marker, add)

p.write_text(s, encoding="utf-8")

# 4. miniapp model list / backend route
p = Path("bot/miniapp.py")
s = p.read_text(encoding="utf-8")

if "from bot.services.wan27_service import wan27_service" not in s:
    s = s.replace(
        "from bot.services.seedream_service import seedream_service",
        "from bot.services.seedream_service import seedream_service\nfrom bot.services.wan27_service import wan27_service",
    )

# Add model to IMAGE_MODELS if array has grok_imagine_i2i item.
if '"id": "wan_27"' not in s:
    needle = '''    {
        "id": "grok_imagine_i2i",'''
    idx = s.find(needle)
    if idx != -1:
        list_start = s.rfind("[", 0, idx)
        # Safer: append before closing IMAGE_MODELS by finding VIDEO_MODELS marker.
        marker = "\n]\n\nVIDEO_MODELS"
        model_block = '''    {
        "id": "wan_27",
        "label": "Wan 2.7 Pro",
        "description": "Тестовая модель Wan 2.7 для генерации и редактирования изображений.",
        "cost": preset_manager.get_generation_cost("wan_27"),
        "ratios": ["1:1", "16:9", "4:3", "21:9", "3:4", "9:16"],
        "max_references": 9,
        "requires_reference": False,
        "supports_nsfw_checker": False,
    },
'''
        if marker in s:
            s = s.replace(marker, model_block + "]\n\nVIDEO_MODELS", 1)

# Add route in miniapp _start_image_generation_task if similar function exists.
grok_marker = '''    elif runtime_img_service == "grok_imagine_i2i":
        result = await grok_service.generate_image_to_image(
            image_urls=reference_images,
            prompt=effective_prompt,
            nsfw_checker=nsfw_enabled,
            callBackUrl=callback_url,
        )
'''
if 'runtime_img_service == "wan_27"' not in s and grok_marker in s:
    s = s.replace(
        grok_marker,
        grok_marker + '''    elif runtime_img_service == "wan_27":
        result = await wan27_service.generate_image(
            prompt=effective_prompt,
            aspect_ratio=img_ratio,
            input_urls=reference_images,
            n=1,
            resolution="2K",
            pro=True,
            enable_sequential=False,
            thinking_mode=False,
            watermark=False,
            seed=random.randint(1, 2147483647),
            nsfw_checker=False,
            callBackUrl=callback_url,
        )
''',
    )

p.write_text(s, encoding="utf-8")
PY

python3 -m py_compile bot/services/wan27_service.py bot/handlers/generation.py bot/miniapp.py bot/keyboards.py bot/services/preset_manager.py

echo "Wan 2.7 test integration applied."
echo "Review with:"
echo "  grep -R \"wan_27\\|Wan 2.7\\|wan/2-7-image\" -n bot | head -80"
