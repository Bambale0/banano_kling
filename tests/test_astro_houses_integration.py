"""House annotations must be part of actual versioned chart output."""

from types import SimpleNamespace

from bot.services.astro_chart_core import (
    BODIES,
    build_natal_facts,
    build_synastry_facts,
)

PROFILE = {
    "date": "29.02.2000", "time": "13:45",
    "latitude": 59.93, "longitude": 30.33, "timezone": "Europe/Moscow",
}


class Engine:
    def resolve(self, **kwargs):
        return SimpleNamespace(warnings=[], time_known=kwargs.get("time") is not None)

    def assemble(self, moment, **kwargs):
        return {
            "bodies": {
                name: {"lon": float((index * 20) % 360), "speed": 1}
                for index, name in enumerate(BODIES)
            },
            "cusps": [(350 + index * 30) % 360 for index in range(12)]
            if moment.time_known else None,
            "angles": {"asc": 350, "mc": 260} if moment.time_known else None,
            "aspects": [],
        }

    def cross_aspects(self, first, second):
        return []


def test_natal_outputs_twelve_house_rulers_and_exact_body_placements():
    result = build_natal_facts(PROFILE, engine=Engine(), kernel="fake.bsp")
    assert len(result["chart"]["houses"]) == 12
    assert result["chart"]["houses"][0]["ruler"] == "Jupiter"
    assert result["chart"]["body_houses"]["Sun"] == 1
    assert result["chart"]["body_houses"]["Mercury"] == 2
    assert result["chart"]["ruler_scheme"] == "traditional"


def test_unknown_birth_time_never_gets_fake_house_placement():
    result = build_natal_facts(
        {**PROFILE, "time": None}, engine=Engine(), kernel="fake.bsp",
    )
    assert result["chart"]["houses"] is None
    assert result["chart"]["body_houses"] is None


def test_synastry_includes_directional_house_overlays():
    result = build_synastry_facts(
        PROFILE, {**PROFILE, "date": "02.06.2001"},
        engine=Engine(), kernel="fake.bsp",
    )
    assert result["house_overlays"]["first_in_second"]["Sun"] == 1
    assert result["house_overlays"]["second_in_first"]["Mercury"] == 2


def test_no_fictitious_partner_houses_when_time_missing():
    result = build_synastry_facts(
        PROFILE, {**PROFILE, "time": None},
        engine=Engine(), kernel="fake.bsp",
    )
    assert result["house_overlays"]["first_in_second"] is None
    assert result["house_overlays"]["second_in_first"]["Sun"] == 1
