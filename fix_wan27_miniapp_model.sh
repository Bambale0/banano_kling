#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path

p = Path("bot/miniapp.py")
s = p.read_text(encoding="utf-8")

if '"id": "wan_27"' not in s:
    wan_block = '''    {
        "id": "wan_27",
        "label": "Wan 2.7 Pro",
        "description": "Генерация и редактирование изображений через Wan 2.7 Pro.",
        "cost": preset_manager.get_generation_cost("wan_27"),
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "21:9"],
        "max_references": 9,
        "requires_reference": False,
        "supports_nsfw_checker": False,
        "supports_wan_options": True,
    },
'''

    # Insert into IMAGE_MODELS before VIDEO_MODELS. This is safer than targeting a specific existing model.
    marker = "\n]\n\nVIDEO_MODELS"
    if marker not in s:
        raise SystemExit("Could not find IMAGE_MODELS closing marker before VIDEO_MODELS in bot/miniapp.py")
    s = s.replace(marker, wan_block + "]\n\nVIDEO_MODELS", 1)

# Ensure miniapp route can actually run Wan if service was integrated in generation.py but not miniapp.py.
if "from bot.services.wan27_service import wan27_service" not in s:
    import_marker = "from bot.services.seedream_service import seedream_service"
    if import_marker in s:
        s = s.replace(import_marker, import_marker + "\nfrom bot.services.wan27_service import wan27_service", 1)
    else:
        raise SystemExit("Could not find seedream_service import marker in bot/miniapp.py")

# Add Wan provider label if helper exists in this file.
if 'if img_service == "wan_27"' not in s and "def _get_image_provider_model" in s:
    s = s.replace(
        'if img_service == "grok_imagine_i2i":\n        return "grok-imagine-image-to-image"',
        'if img_service == "grok_imagine_i2i":\n        return "grok-imagine-image-to-image"\n    if img_service == "wan_27":\n        return "wan/2-7-image-pro"',
        1,
    )

# Add Wan route after Grok route inside miniapp image generation launcher, if missing.
if 'runtime_img_service == "wan_27"' not in s:
    grok_route = '''    elif runtime_img_service == "grok_imagine_i2i":
        result = await grok_service.generate_image_to_image(
            image_urls=reference_images,
            prompt=effective_prompt,
            nsfw_checker=nsfw_enabled,
            callBackUrl=callback_url,
        )
'''
    wan_route = grok_route + '''    elif runtime_img_service == "wan_27":
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
    if grok_route in s:
        s = s.replace(grok_route, wan_route, 1)

p.write_text(s, encoding="utf-8")

# Keep frontend mock data in sync for fallback/demo mode, if present.
mock = Path("frontend/miniapp-v0/lib/mock-data.ts")
if mock.exists():
    ms = mock.read_text(encoding="utf-8")
    if "id: 'wan_27'" not in ms:
        block = """  {
    id: 'wan_27',
    label: 'Wan 2.7 Pro',
    description: 'Генерация и редактирование изображений через Wan 2.7 Pro.',
    cost: 7,
    ratios: ['1:1', '16:9', '9:16', '4:3', '3:4', '21:9'],
    max_references: 9,
    requires_reference: false,
    supports_nsfw_checker: false,
    supports_wan_options: true,
  },
"""
        marker = "export const mockImageModels"
        if marker in ms:
            # Insert before closing of first exported image model array, right before mockVideoModels.
            close_marker = "\n]\n\nexport const mockVideoModels"
            if close_marker in ms:
                ms = ms.replace(close_marker, "\n" + block + "]\n\nexport const mockVideoModels", 1)
                mock.write_text(ms, encoding="utf-8")
PY

python3 -m py_compile bot/miniapp.py bot/services/wan27_service.py

echo "Wan 2.7 added to Mini App bootstrap. Restart bot, then hard-refresh Mini App."
echo "Check with: grep -n 'wan_27\|Wan 2.7' bot/miniapp.py frontend/miniapp-v0/lib/mock-data.ts | head -40"
