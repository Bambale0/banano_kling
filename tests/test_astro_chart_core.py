"""Natal and synastry adapter regression tests (pure mock, no JPL download)."""

from types import SimpleNamespace

import pytest

from bot.services.astro_chart_core import (
    BODIES,
    AstroChartInputError,
    AstroChartUnavailable,
    build_natal_facts,
    build_synastry_facts,
    parse_birth_profile,
)

PROFILE = {
    "date": "29.02.2000",
    "time": "13:45",
    "latitude": 59.9343,
    "longitude": 30.3351,
    "timezone": "Europe/Moscow",
}


class FakeEngine:
    __version__ = "0.5.0"

    def __init__(self):
        self.calls = []
        self.warning = []
        self.omit = None
        self.omit_houses = False

    def resolve(self, **kwargs):
        self.calls.append(("resolve", kwargs))
        return SimpleNamespace(warnings=list(self.warning))

    def assemble(self, moment, **kwargs):
        self.calls.append(("assemble", kwargs))
        return {
            "bodies": {
                name: {"lon": i * 20.0 % 360.0, "speed": 0.0}
                for i, name in enumerate(BODIES) if name != self.omit
            },
            "angles": {"asc": 42.0, "mc": 17.0},
            "cusps": None if self.omit_houses else [i * 30.0 for i in range(12)],
            "aspects": [{"a": "Sun", "b": "Moon", "aspect": "conjunction"}],
            "warnings": [],
        }

    def cross_aspects(self, first, second):
        assert "Sun" in first["bodies"] and "Sun" in second["bodies"]
        return [{"a": "Sun", "b": "Moon", "aspect": "trine", "chart_a": "inner", "chart_b": "outer"}]


@pytest.mark.parametrize(
    "delta",
    [
        {"date": "31.02.2000"}, {"date": "2000-02-29"},
        {"date": "01.01.1800"}, {"time": ""}, {"time": "25:99"},
        {"latitude": float("nan")}, {"longitude": 181},
        {"latitude": True}, {"timezone": "Mars/Olympus"},
        {"timezone": "../etc/passwd"}, {"fold": 5}, {"fold": False},
    ],
)
def test_invalid_profiles_rejected(delta):
    with pytest.raises(AstroChartInputError):
        parse_birth_profile(PROFILE | delta)


def test_feb29_and_historical_iana_timezone_parsed():
    birth = parse_birth_profile(PROFILE)
    assert (birth.year, birth.month, birth.day, birth.hour, birth.minute) == (2000, 2, 29, 13, 45)
    assert birth.timezone == "Europe/Moscow"


def test_facts_are_real_engine_data_not_interpretations():
    engine = FakeEngine()
    result = build_natal_facts(PROFILE, engine=engine, kernel="/preprovisioned/de440.bsp")
    assert result["schema_version"] == "astro.natal-facts.v1"
    assert result["chart"]["bodies"]["Mars"]["lon"] == 80.0
    assert result["interpretation"] is None
    assert engine.calls[0][1]["tz"] == "Europe/Moscow"
    assert engine.calls[1][1]["house_system"] == "Placidus"
    assert engine.calls[1][1]["de440"] == "/preprovisioned/de440.bsp"


def test_natal_fails_closed_when_jpl_asset_is_not_configured(monkeypatch):
    monkeypatch.delenv("ASTRO_DE440_PATH", raising=False)
    with pytest.raises(AstroChartUnavailable, match="not configured"):
        build_natal_facts(PROFILE, engine=FakeEngine())


def test_missing_planets_or_unavailable_placidus_fail_closed():
    engine = FakeEngine()
    engine.omit = "Sun"
    with pytest.raises(AstroChartUnavailable, match="mandatory"):
        build_natal_facts(PROFILE, engine=engine, kernel="de440.bsp")
    engine.omit = None
    engine.omit_houses = True
    with pytest.raises(AstroChartUnavailable, match="Placidus"):
        build_natal_facts(PROFILE, engine=engine, kernel="de440.bsp")


def test_ambiguous_and_nonexistent_local_time_require_resolution():
    engine = FakeEngine()
    engine.warning = ["ambiguous local time (DST fold)"]
    with pytest.raises(AstroChartInputError, match="повторяющийся"):
        build_natal_facts(PROFILE, engine=engine, kernel="de440.bsp")
    assert build_natal_facts(PROFILE | {"fold": 1}, engine=engine, kernel="de440.bsp")
    engine.warning = ["nonexistent local time (DST spring-forward gap)"]
    with pytest.raises(AstroChartInputError, match="не существовало"):
        build_natal_facts(PROFILE | {"fold": 1}, engine=engine, kernel="de440.bsp")


def test_synastry_has_two_distinct_charts_and_no_fake_relationship_score():
    engine = FakeEngine()
    other = PROFILE | {"date": "13.11.1997", "time": "21:30"}
    result = build_synastry_facts(PROFILE, other, engine=engine, kernel="de440.bsp")
    assert result["schema_version"] == "astro.synastry-facts.v1"
    assert result["aspects"][0]["chart_a"] == "inner"
    assert result["interpretation"] is None
    assert "score" not in result
    assert [call[0] for call in engine.calls].count("resolve") == 2
