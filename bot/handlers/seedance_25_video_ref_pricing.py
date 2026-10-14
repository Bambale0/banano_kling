"""Seedance 2.5 video-reference retail pricing compatibility.

The product rule is simple and server-authoritative: when a Seedance generation
contains video references, charge their measured seconds plus the selected
output seconds at the same rate. Do not multiply prices by presence.
"""

from __future__ import annotations

from functools import wraps

from bot.video_reference_policy import apply_video_reference_cost

from . import seedance_25_preview as preview_module

MODEL_KEY = "seedance_2_5"
_installed = False


def install_seedance_25_video_ref_pricing() -> None:
    """Wrap the shared Seedance 2.5 quote used by Telegram and Mini App."""
    global _installed
    if _installed:
        return

    original = preview_module._price_quote

    @wraps(original)
    def priced(data: dict) -> float:
        base_cost = float(original(data))
        references = list(data.get("v_reference_videos") or [])
        if not references:
            return base_cost
        durations = list(data.get("seedance25_reference_video_durations") or [])
        if len(durations) != len(references) or any(float(item) <= 0 for item in durations):
            raise ValueError("Длительность видео-референсов ещё не проверена")
        seconds = 5 if data.get("seedance25_video_editing") is True else int(data.get("v_duration", 5))
        if seconds == -1:
            seconds = 5  # Established admin Auto estimate.
        from bot.services.preset_manager import preset_manager
        return float(preset_manager._format_cost(apply_video_reference_cost(
            MODEL_KEY, base_cost, references, output_seconds=seconds,
            reference_seconds=sum(float(item) for item in durations),
        )))

    preview_module._price_quote = priced
    _installed = True
