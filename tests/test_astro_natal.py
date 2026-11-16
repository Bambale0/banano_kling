"""Known astronomy, honest degraded charts, civil time and aspects."""
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from bot.services.astro_lunar import AstroInputError
from bot.services.astro_natal import (
    build_natal_positions,
    major_aspects,
    resolve_birth_instant,
)


def test_birth_date_timezone_and_utc():
    instant, known = resolve_birth_instant("2000-01-01", "15:30", "Europe/Moscow")
    assert known is True
    assert instant == datetime(2000, 1, 1, 12, 30, tzinfo=UTC)


def test_birth_time_unknown_is_degraded():
    instant, known = resolve_birth_instant("2000-01-01", "", "Europe/Moscow")
    assert not known
    assert instant == datetime(2000, 1, 1, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize("date,time,zone", [
    ("2024-02-30", "12:00", "UTC"),
    ("1000-01-01", "12:00", "UTC"),
    ("2024-05-01", "25:00", "UTC"),
    ("2024-03-31", "02:30", "Europe/Berlin"),
    ("2024-10-27", "02:30", "Europe/Berlin"),
    ("2024-05-01", "12:00", "../etc/passwd"),
])
def test_invalid_or_ambiguous_birth_input_is_rejected(date, time, zone):
    with pytest.raises(AstroInputError):
        resolve_birth_instant(date, time, zone)


def test_dst_fold_requires_explicit_choice():
    first, _ = resolve_birth_instant("2024-10-27", "02:30", "Europe/Berlin", fold=0)
    second, _ = resolve_birth_instant("2024-10-27", "02:30", "Europe/Berlin", fold=1)
    assert (second - first).total_seconds() == 3600


def test_aspects_use_angular_distance_and_orbs():
    bodies = [
        {"name": "Sun", "longitude_deg": 359.5},
        {"name": "Moon", "longitude_deg": 0.0},
        {"name": "Mars", "longitude_deg": 180.0},
        {"name": "Saturn", "longitude_deg": 87.0},
    ]
    aspects = major_aspects(bodies)
    assert any(a["kind"] == "conjunction" and a["orb_deg"] == 0.5 for a in aspects)
    assert any(a["kind"] == "opposition" and a["orb_deg"] == 0.5 for a in aspects)
    assert any(a["kind"] == "square" for a in aspects)


class FakeEngine:
    class Body:
        Sun = "Sun"
        Moon = "Moon"
        Mercury = "Mercury"
        Venus = "Venus"
        Mars = "Mars"
        Jupiter = "Jupiter"
        Saturn = "Saturn"
        Uranus = "Uranus"
        Neptune = "Neptune"
        Pluto = "Pluto"

    class Time:
        @staticmethod
        def Parse(value):
            return value

    @staticmethod
    def GeoVector(body, time, aberration):
        return SimpleNamespace(body=body, time=time)

    @staticmethod
    def Ecliptic(vector):
        values = {"Sun": 0, "Moon": 3, "Mercury": 60, "Venus": 120,
                  "Mars": 90, "Jupiter": 150, "Saturn": 180,
                  "Uranus": 210, "Neptune": 270, "Pluto": 300}
        return SimpleNamespace(lon=values[vector.body])


def test_unknown_birth_time_omits_moon_and_houses():
    result = build_natal_positions("2000-01-01", None, "UTC", engine=FakeEngine)
    assert result["schema_version"] == "astro.natal.positions.v1"
    assert result["houses"] is None
    assert result["angles"] is None
    assert not result["birth_time_known"]
    assert "Moon" not in [p["name"] for p in result["positions"]]
    assert all(p["accuracy"] == "approximate_local_noon" for p in result["positions"])


def test_known_time_keeps_moon_without_invented_ascendant():
    result = build_natal_positions("2000-01-01", "12:00", "UTC", engine=FakeEngine)
    assert result["birth_time_known"]
    assert "Moon" in [p["name"] for p in result["positions"]]
    assert all(p["accuracy"] == "exact_instant" for p in result["positions"])
    assert result["angles"] is None


def test_real_sun_equinox_tropical_sign():
    pytest.importorskip("astronomy")
    result = build_natal_positions("2024-03-20", "12:00", "UTC")
    sun = next(x for x in result["positions"] if x["name"] == "Sun")
    assert sun["sign"] == "Овен"
    assert 0 <= sun["degree_in_sign"] < 2
    assert len(result["positions"]) == 10
