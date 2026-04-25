#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_FILE="$PROJECT_DIR/bot/handlers/generation.py"
RESTART_SCRIPT="$PROJECT_DIR/restart.sh"

echo "=== Fix Banana preserve reference details ==="
[ -f "$TARGET_FILE" ] || { echo "File not found: $TARGET_FILE"; exit 1; }
cd "$PROJECT_DIR"
cp "$TARGET_FILE" "$TARGET_FILE.bak.$(date +%Y%m%d_%H%M%S)"

python3 - "$TARGET_FILE" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text(encoding='utf-8')

helper = '''\n\ndef _apply_reference_detail_preservation(img_service: str, prompt: str, reference_images: list[str]) -> str:\n    """For Banana models, ask provider to keep reference details stable."""\n    prompt = (prompt or "").strip()\n    if not reference_images or img_service not in {"banana_pro", "banana_2", "nanobanana"}:\n        return prompt\n    instruction = (\n        "Preserve the reference image details exactly: identity, face, proportions, hairstyle, outfit, accessories, colors, textures, labels, markings, object shape, material, and visual style. "\n        "Do not redesign or replace unchanged elements. Apply only the requested user changes."\n    )\n    return f"{instruction}\\n\\nUser request: {prompt}" if prompt else instruction\n'''

if '_apply_reference_detail_preservation' not in s:
    anchor = '\ndef _build_image_variant_prompt(prompt: str, variant_index: int, total_count: int) -> str:\n'
    if anchor not in s:
        raise SystemExit('anchor not found')
    s = s.replace(anchor, helper + anchor, 1)

old = 'effective_prompt = _apply_safe_prompt_framing(runtime_img_service, prompt)'
new = 'effective_prompt = _apply_safe_prompt_framing(runtime_img_service, _apply_reference_detail_preservation(runtime_img_service, prompt, reference_images))'
if old in s:
    s = s.replace(old, new, 1)
elif '_apply_reference_detail_preservation(runtime_img_service, prompt, reference_images)' not in s:
    raise SystemExit('effective_prompt line not found')

p.write_text(s, encoding='utf-8')
PY

python3 -m py_compile "$TARGET_FILE"
echo "OK: generation.py patched"

if [ -f "$RESTART_SCRIPT" ]; then
  chmod +x "$RESTART_SCRIPT"
  "$RESTART_SCRIPT"
else
  echo "restart.sh not found, restart bot manually"
fi
