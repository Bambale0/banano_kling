"""Versioned retail settlement; supplier duration never rewrites fixed quotes."""
from __future__ import annotations

import math


def settlement_amounts(quote: dict, reserve: float, result_seconds: float) -> tuple[float, float]:
    reserve = float(reserve)
    result_seconds = float(result_seconds)
    if not math.isfinite(reserve) or reserve < 0 or not math.isfinite(result_seconds) or result_seconds <= 0:
        raise ValueError("Invalid Wan settlement measurement")
    version = quote.get("version")
    mode = quote.get("billing_mode")
    if version == 3:
        if mode == "output_only":
            # Fixed-price v3 quotes remain immutable even if the provider's
            # measured output differs from the selected duration.
            charge = reserve
        elif mode == "auto_output_reserve":
            # New Auto tariffs charge actual generated seconds, not references.
            charge = min(reserve, round(float(quote["rate_per_second"]) * result_seconds * 2) / 2)
        else:
            raise ValueError("Unknown Wan retail billing mode")
    elif version == 2 and mode == "input_plus_selected_output":
        # Keep accepted v2 fixed quotes and admin-free charges untouched.
        charge = reserve
    else:
        # Preserve accepted legacy and v2 Auto reference-plus-output quotes.
        seconds = float(quote["input_video_seconds"]) + result_seconds
        charge = min(reserve, round(float(quote["rate_per_second"]) * seconds * 2) / 2)
    return charge, max(0.0, reserve - charge)
