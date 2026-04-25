#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path

p = Path("bot/handlers/generation.py")
s = p.read_text(encoding="utf-8")

marker = "\n\nasync def _start_image_generation_task"
if "def _build_image_variant_prompt" not in s:
    helper = r'''

def _build_image_variant_prompt(prompt: str, variant_index: int, total_count: int) -> str:
    """Add controlled variation for multi-image batches while keeping references."""
    prompt = (prompt or "").strip()
    if total_count <= 1:
        return prompt

    variants = [
        "Create a distinct variation while preserving the same referenced person/object, identity, key features, outfit, and visual style. Use a slightly different composition and micro-pose.",
        "Create another distinct interpretation while preserving the same referenced person/object, identity, key features, outfit, and visual style. Change camera angle, crop, and natural expression slightly.",
        "Create a new variation while preserving the same referenced person/object, identity, key features, outfit, and visual style. Vary lighting balance, framing, and background depth slightly.",
        "Create an alternate editorial take while preserving the same referenced person/object, identity, key features, outfit, and visual style. Use a different crop, pose nuance, and mood.",
    ]
    instruction = variants[variant_index % len(variants)]
    return f"{prompt}\n\nVariant {variant_index + 1} of {total_count}: {instruction} Do not copy previous outputs exactly."
'''
    if marker not in s:
        raise SystemExit("Could not find _start_image_generation_task marker")
    s = s.replace(marker, helper + marker)

old_log = '''    logger.info(
        "Image route: local_task_id=%s selected_model=%s runtime_model=%s provider_model=%s references=%s ratio=%s",
        local_task_id,
        img_service,
        runtime_img_service,
        provider_model,
        len(reference_images),
        img_ratio,
    )'''
new_log = '''    logger.info(
        "Image route: local_task_id=%s selected_model=%s runtime_model=%s provider_model=%s references=%s ratio=%s ref_sample=%s prompt_len=%s",
        local_task_id,
        img_service,
        runtime_img_service,
        provider_model,
        len(reference_images),
        img_ratio,
        reference_images[:3],
        len(prompt or ""),
    )'''
if old_log in s:
    s = s.replace(old_log, new_log)

# Patch common batch loop pattern in bot flow.
s = s.replace(
    "reference_images=reference_images,\n            unit_cost=unit_cost,",
    "reference_images=list(stable_reference_images if 'stable_reference_images' in locals() else (reference_images or [])),\n            unit_cost=unit_cost,",
)

# If loops use prompt=prompt directly, variant prompt is applied when loop variables exist.
s = s.replace(
    "prompt=prompt,\n            img_ratio=img_ratio,",
    "prompt=_build_image_variant_prompt(prompt, index if 'index' in locals() else 0, img_count if 'img_count' in locals() else 1),\n            img_ratio=img_ratio,",
)

# Add stable refs before the common for index in range(img_count) loop if present.
s = s.replace(
    "for index in range(img_count):",
    "stable_reference_images = list(reference_images or [])\n    for index in range(img_count):",
    1,
)

p.write_text(s, encoding="utf-8")
PY

python3 -m py_compile bot/handlers/generation.py

echo "Batch generation patch applied. Review with: git diff -- bot/handlers/generation.py"
