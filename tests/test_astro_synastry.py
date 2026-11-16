"""Synastry cross-aspects use two independent natal charts."""

import pytest

from bot.services.astro_lunar import AstroInputError
from bot.services.astro_synastry import build_compatibility_facts, cross_aspects

ORBS = {"conjunction": 8.0, "sextile": 4.0, "square": 6.0, "trine": 6.0, "opposition": 8.0}


def test_cross_chart_same_planet_and_wrap():
    a = {"Sun": {"longitude_deg": 359}, "Venus": {"longitude_deg": 20}}
    b = {"Sun": {"longitude_deg": 1}, "Moon": {"longitude_deg": 200}}
    aspects = cross_aspects(a, b, orbs=ORBS)
    assert any(
        item["person_a_body"] == "Sun" and item["person_b_body"] == "Sun"
        and item["kind"] == "conjunction" and item["orb_deg"] == 2
        for item in aspects
    )
    assert any(
        item["person_a_body"] == "Venus" and item["person_b_body"] == "Moon"
        and item["kind"] == "opposition" and item["orb_deg"] == 0
        for item in aspects
    )


def test_tight_orbs_prevent_fabricated_aspects():
    a = {"Sun": {"longitude_deg": 30}}
    b = {"Moon": {"longitude_deg": 50}}
    assert cross_aspects(a, b, orbs=ORBS) == []


def test_invalid_profiles_are_rejected():
    with pytest.raises(AstroInputError):
        build_compatibility_facts(None, {}, orbs=ORBS)
    with pytest.raises(AstroInputError):
        build_compatibility_facts({}, [], orbs=ORBS)


def test_compatibility_real_charts_and_unknown_time():
    astro = pytest.importorskip("astronomy")
    first = {"date": "20.03.2024", "time": "12:00", "timezone": "UTC"}
    second = {"date": "20.03.1999", "time": "", "timezone": "Europe/Moscow"}
    result = build_compatibility_facts(first, second, engine=astro, orbs=ORBS)
    assert result["schema_version"] == "astro.synastry.facts.v1"
    assert result["person_a"]["birth_time_known"] is True
    assert result["person_b"]["birth_time_known"] is False
    assert "Moon" in result["person_a"]["positions"]
    assert "Moon" not in result["person_b"]["positions"]
    assert result["cross_aspects"]
    assert all(item["approximate"] for item in result["cross_aspects"])
    assert "house_overlays" in result["not_calculated"]
    assert "composite" in result["not_calculated"]


def test_two_people_must_not_be_confused():
    astro = pytest.importorskip("astronomy")
    a = {"date": "20.03.2024", "time": "12:00", "timezone": "UTC"}
    b = {"date": "20.09.2024", "time": "12:00", "timezone": "UTC"}
    result = build_compatibility_facts(a, b, engine=astro, orbs=ORBS)
    assert result["person_a"]["positions"]["Sun"]["sign"] != result["person_b"]["positions"]["Sun"]["sign"]
    assert any(
        item["person_a_body"] == "Sun" and item["person_b_body"] == "Sun"
        and item["kind"] == "opposition"
        for item in result["cross_aspects"]
    )
