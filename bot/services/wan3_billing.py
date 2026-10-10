"""Versioned retail settlement; supplier duration never rewrites fixed quotes."""
from __future__ import annotations

import math


def settlement_amounts(quote: dict, reserve: float, result_seconds: float) -> tuple[float, float]:
    reserve = float(reserve)
    result_seconds = float(result_seconds)
    if not math.isfinite(reserve) or reserve < 0 or not math.isfinite(result_seconds) or result_seconds <= 0:
        raise ValueError("Invalid Wan settlement measurement")
    if quote.get("version") == 2 and quote.get("billing_mode") == "input_plus_selected_output":
        # Immutable accepted amount, including admin zero charge. Actual output
        # is validated independently and retained as supplier/quality telemetry.
        charge = reserve
    else:
        # Preserve legacy accepted snapshots and proven-cap Auto reserve policy.
        seconds = float(quote["input_video_seconds"]) + result_seconds
        charge = min(reserve, round(float(quote["rate_per_second"]) * seconds * 2) / 2)
    return charge, max(0.0, reserve - charge)
