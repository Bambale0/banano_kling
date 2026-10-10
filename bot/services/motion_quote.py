"""Pure, source-locked Motion quote. No client duration or multiplier."""
from __future__ import annotations

import hashlib
import json
import math


def build_motion_quote(*, model: str, quality: str, direction: str, prompt: str,
                       image_url: str, video_url: str, source_sha256: str,
                       source_seconds: float, rate: float, admin_free: bool,
                       format_cost) -> dict:
    if model not in {"motion_control_v26", "motion_control_v30"}:
        raise ValueError("Неизвестная модель Motion")
    if quality not in {"720p", "1080p"} or direction not in {"video", "image"}:
        raise ValueError("Некорректные настройки Motion")
    maximum = 10 if direction == "image" else 30
    if isinstance(source_seconds, bool) or not math.isfinite(source_seconds) or not 3 <= source_seconds <= maximum:
        raise ValueError(f"Загрузите видео движения от 3 до {maximum} секунд")
    if isinstance(rate, bool) or not math.isfinite(rate) or rate <= 0:
        raise ValueError("Администратор ещё не настроил ставку выбранного качества Motion")
    # Motion accepts no output duration field. The displayed locked output
    # follows the actual source clip; changing it requires changing the clip.
    seconds = source_seconds + source_seconds
    cost = float(format_cost(seconds * rate))
    if not math.isfinite(cost) or cost <= 0:
        raise ValueError("Некорректная стоимость Motion")
    quote = {
        "version": 2, "billing_mode": "source_locked_output",
        "model": model, "quality": quality, "direction": direction,
        "prompt": prompt, "image_url": image_url, "video_url": video_url,
        "source_sha256": source_sha256, "input_seconds": source_seconds,
        "output_seconds": source_seconds, "billable_seconds": seconds,
        "rate_per_second": rate, "cost": cost,
        "charge_cost": 0.0 if admin_free else cost, "admin_free": bool(admin_free),
    }
    quote["quote_hash"] = hashlib.sha256(json.dumps(
        quote, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()).hexdigest()
    return quote
