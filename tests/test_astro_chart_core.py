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
        return SimpleNamespace(warnings=list(self.warning), time_known=kwargs.get("time") is not None)

    def assemble(self, moment, **kwargs):
        self.calls.append(("assemble", kwargs))
        return {
            "bodies": {
                name: {"lon": i * 20.0 % 360.0, "speed": 0.0}
                for i, name in enumerate(BODIES) if name != self.omit
            },
            "angles": {"asc": 42.0, "mc": 17.0} if moment.time_known else None,
            "cusps": None if self.omit_houses or not moment.time_known else [i * 30.0 for i in range(12)],
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
        {"date": "01.01.1800"}, {"time": "unknown"}, {"time": "25:99"},
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


def test_real_mit_engine_placidus_houses_offline():
    """Real library smoke: house math must run without downloading a kernel."""
    pytest.importorskip("openephem")
    from openephem.houses import houses_from_jd

    h = houses_from_jd(2451545.0, 51.5, -0.1, "Placidus")
    assert len(h.cusps) == 12
    assert all(0 <= longitude < 360 for longitude in h.cusps)
    assert abs((h.cusps[0] - h.asc + 180) % 360 - 180) < 0.01
    assert abs((h.cusps[9] - h.mc + 180) % 360 - 180) < 0.01


def test_karma_indicators_are_positions_not_invented_past_life_claims():
    from bot.services.astro_chart_core import build_karma_indicators

    result = build_karma_indicators(PROFILE, engine=FakeEngine(), kernel="de440.bsp")
    assert result["schema_version"] == "astro.karma-indicators.v1"
    assert set(result["indicators"]) == {"TrueNode", "MeanLilith", "Saturn", "Pluto"}
    assert result["interpretation"] is None


class FakePlanetEngine:
    def ecliptic_longitude(self, jd, name):
        return list(BODIES).index(name) * 23.0 + jd % 29.0


def test_yearly_and_monthly_snapshots_have_real_sample_timestamps():
    from datetime import UTC, datetime

    from bot.services.astro_chart_core import build_transit_snapshots

    engine = FakeEngine()
    engine.returns = SimpleNamespace(
        jd_from_datetime=lambda dt: (dt - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds() / 86400.0 + 2440587.5,
    )
    planet = FakePlanetEngine()
    monthly = build_transit_snapshots(
        PROFILE, year=2024, month=2, engine=engine,
        kernel="de440.bsp", planetary_engine=planet,
    )
    annual = build_transit_snapshots(
        PROFILE, year=2024, engine=engine,
        kernel="de440.bsp", planetary_engine=planet,
    )
    assert monthly["scope"] == "month"
    assert len(monthly["samples"]) == 29
    assert monthly["samples"][-1]["date"] == "2024-02-29"
    assert annual["scope"] == "year"
    assert len(annual["samples"]) == 12
    assert annual["samples"][-1]["date"] == "2024-12-01"
    assert monthly["interpretation"] is None
    assert monthly["samples"][0]["at_local"].endswith("+03:00")


def test_solar_return_uses_true_sun_crossing_and_separate_location():
    from datetime import UTC, datetime

    from bot.services.astro_chart_core import build_solar_return_facts

    engine = FakeEngine()
    used = {}

    def search_solar(lon, near, *, engine):
        used["sun"] = lon
        return near + 0.1234

    engine.returns = SimpleNamespace(
        jd=lambda *args: 2460000.0,
        solar_return=search_solar,
        datetime_from_jd=lambda jd: datetime(2024, 2, 28, 19, 30, tzinfo=UTC),
    )
    result = build_solar_return_facts(
        PROFILE, target_year=2024,
        return_location={
            "latitude": 40.7128, "longitude": -74.006,
            "timezone": "America/New_York",
        },
        engine=engine, kernel="de440.bsp", planetary_engine=FakePlanetEngine(),
    )
    assert result["schema_version"] == "astro.solar-facts.v1"
    assert result["target_year"] == 2024
    assert result["solar_return_at_local"].endswith("-05:00")
    assert result["return_location"]["timezone"] == "America/New_York"
    assert used["sun"] == 0.0
    assert result["interpretation"] is None


def test_solar_return_rejects_incomplete_planetary_facts():
    from bot.services.astro_chart_core import AstroChartInputError, build_solar_return_facts

    with pytest.raises(AstroChartInputError):
        build_solar_return_facts(
            PROFILE, target_year=2024,
            return_location={"latitude": float("nan"), "longitude": 0, "timezone": "UTC"},
            engine=FakeEngine(), kernel="de440.bsp",
        )


@pytest.mark.parametrize("clock", ["", None])
def test_unknown_birth_time_omits_moon_houses_and_natal_moon_aspects(clock):
    payload = PROFILE | {"time": clock}
    result = build_natal_facts(payload, engine=FakeEngine(), kernel="de440.bsp")
    assert result["accuracy"] == {
        "birth_time_known": False,
        "moon_position_known": False,
        "houses_available": False,
    }
    assert result["chart"]["cusps"] is None
    assert result["chart"]["angles"] is None
    assert "Moon" not in result["chart"]["bodies"]
    assert all(
        item.get("a") != "Moon" and item.get("b") != "Moon"
        for item in result["chart"]["aspects"]
    )


def test_unknown_time_cannot_produce_precision_solar_return():
    from bot.services.astro_chart_core import build_solar_return_facts

    with pytest.raises(AstroChartInputError, match="время рождения"):
        build_solar_return_facts(
            PROFILE | {"time": ""},
            target_year=2024,
            return_location={
                "latitude": 40.7128, "longitude": -74.006,
                "timezone": "America/New_York",
            },
            engine=FakeEngine(), kernel="de440.bsp",
        )
