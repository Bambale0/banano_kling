#!/usr/bin/env python3
"""Read-only full Astro engine smoke: public test birth date, no Telegram/DB writes."""

from __future__ import annotations

from datetime import datetime

from bot.services.astro_chart_core import build_natal_facts
from bot.services.astro_natal import _ecliptic_longitude
from bot.services.astro_places import get_place, search_places


def main() -> None:
    matches = search_places("Россия, Санкт-Петербург", limit=10)
    place = next((row for row in matches if row["place_id"] == 498817), None)
    if place is None:
        raise RuntimeError("GeoNames baseline lookup failed")
    exact = get_place(place["place_id"])
    profile = {
        "date": "29.02.2000",
        "time": "13:45",
        "latitude": exact["latitude"],
        "longitude": exact["longitude"],
        "timezone": exact["timezone"],
    }
    result = build_natal_facts(profile)
    chart = result["chart"]
    if (
        chart["house_system"] != "Placidus"
        or len(chart["cusps"]) != 12
        or not result["accuracy"]["houses_available"]
        or not isinstance(chart["angles"], dict)
        or not all(key in chart["angles"] for key in ("asc", "mc"))
        or len(chart["bodies"]) != 12
    ):
        raise RuntimeError("Astro engine did not return complete natal facts")

    # Independent astronomy-engine ephemeris must agree on planetary longitudes.
    import astronomy

    at = datetime.fromisoformat(chart["utc"])
    for name in ("Sun", "Moon", "Mercury", "Venus", "Mars"):
        a = chart["bodies"][name]["lon"]
        b = _ecliptic_longitude(astronomy, name, at)
        deviation = abs((a - b + 180) % 360 - 180)
        if deviation > 0.05:
            raise RuntimeError("Independent ephemeris check failed")

    # No invented houses when birth time is unknown.
    unknown = build_natal_facts({**profile, "time": None})
    if unknown["chart"]["cusps"] is not None or unknown["accuracy"]["houses_available"]:
        raise RuntimeError("Unknown-time chart fabricated houses")
    print(
        "ASTRO_FULL_NATAL_SMOKE_OK place_id=498817 timezone=Europe/Moscow "
        "houses=12 bodies=12 angles=ASC,MC cross_ephemeris=passed unknown_time=passed"
    )


if __name__ == "__main__":
    main()
