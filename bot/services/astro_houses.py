"""Deterministic Placidus house annotations and directional synastry overlays.

These are *symbolic* astrology conventions, not scientifically predictive
claims. House cusp positions are calculated elsewhere from JPL DE440; this
module never makes up coordinates, times or house positions.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class AstroHouseError(ValueError):
    """Unsupported house geometry or rulership configuration."""


_ZODIAC = (
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
)
_TRADITIONAL = (
    "Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
    "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter",
)
_MODERN = (
    "Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
    "Venus", "Pluto", "Jupiter", "Saturn", "Uranus", "Neptune",
)
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "astro_settings.json"


def _ruler_mode(config_path: Path | None = None) -> str:
    try:
        source = json.loads((config_path or _CONFIG_PATH).read_text(encoding="utf-8"))
        if source.get("schema_version") != 1:
            raise AstroHouseError("Unsupported Astro settings version")
        mode = source["houses"]["ruler_system"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AstroHouseError("Missing or invalid Astro house settings") from exc
    if mode not in ("traditional", "modern"):
        raise AstroHouseError("Unsupported Astro ruler system")
    return mode


def _geometry(chart: dict) -> list[float] | None:
    cusps = chart.get("cusps")
    angles = chart.get("angles")
    if cusps is None and angles is None:
        return None
    if cusps is None or angles is None or not isinstance(angles, dict):
        raise AstroHouseError("Incomplete house angles or cusps")
    if not isinstance(cusps, list) or len(cusps) != 12:
        raise AstroHouseError("Expected 12 calculated Placidus cusps")
    if any(type(x) not in (float, int) or not math.isfinite(x) or not 0 <= x < 360
           for x in cusps):
        raise AstroHouseError("Invalid Placidus cusp longitude")
    numeric = [float(v) for v in cusps]
    spans = [(numeric[(idx + 1) % 12] - current) % 360
             for idx, current in enumerate(numeric)]
    if any(span <= 0 for span in spans) or not math.isclose(
        sum(spans), 360.0, abs_tol=1e-6,
    ):
        raise AstroHouseError("Placidus cusps do not form a single full circle")
    return numeric


def _body_houses(chart: dict, cusp_positions: list[float]) -> dict[str, int]:
    bodies = chart.get("bodies")
    if not isinstance(bodies, dict):
        raise AstroHouseError("Expected astronomical body coordinates")
    result: dict[str, int] = {}
    for name, body in bodies.items():
        if not isinstance(name, str) or not isinstance(body, dict):
            raise AstroHouseError("Invalid celestial body format")
        longitude = body.get("lon")
        if type(longitude) not in (int, float) or not math.isfinite(longitude):
            raise AstroHouseError("Invalid celestial longitude")
        value = float(longitude) % 360
        for index, start in enumerate(cusp_positions):
            span = (cusp_positions[(index + 1) % 12] - start) % 360
            if (value - start) % 360 < span:
                result[name] = index + 1
                break
        else:
            raise AstroHouseError("Planet not assigned to any house")
    return result


def annotate_houses(
    chart: dict[str, Any], *, ruler_system: str | None = None,
) -> dict[str, Any]:
    """Add 12 rulers and body-in-house numbers only with valid time/geometry."""
    if not isinstance(chart, dict):
        raise AstroHouseError("Invalid chart")
    mode = ruler_system if ruler_system is not None else _ruler_mode()
    if mode not in ("traditional", "modern"):
        raise AstroHouseError("Unsupported Astro ruler system")
    cusps = _geometry(chart)
    if cusps is None:
        return {"ruler_scheme": mode, "houses": None, "body_houses": None}
    rulers = _TRADITIONAL if mode == "traditional" else _MODERN
    houses = []
    for index, longitude in enumerate(cusps):
        sign_index = int(longitude // 30)
        houses.append({
            "house": index + 1, "cusp_lon": longitude,
            "sign": _ZODIAC[sign_index], "ruler": rulers[sign_index],
        })
    return {
        "ruler_scheme": mode, "houses": houses,
        "body_houses": _body_houses(chart, cusps),
    }


def overlay_houses(first: dict, second: dict) -> dict[str, dict[str, int] | None]:
    """First person's planets in second person's houses and vice versa.

    If a receiver's birth time is missing, house placement is undefined. The
    source person's missing time may omit Moon, but existing safe positions
    can still be overlaid onto the receiver's houses.
    """
    first_cusps, second_cusps = _geometry(first), _geometry(second)
    return {
        "first_in_second": (
            _body_houses(first, second_cusps)
            if second_cusps is not None else None
        ),
        "second_in_first": (
            _body_houses(second, first_cusps)
            if first_cusps is not None else None
        ),
    }
