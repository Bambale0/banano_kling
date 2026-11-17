"""FULL report contracts, not just individual section mocks, for seven services.

All 7 original long-form plans must complete every chapter and daily/monthly
calendar item. Source facts are deterministic fixtures; no paid calls here.
"""
import asyncio
import calendar
import json
from datetime import date

import pytest

from bot.services.astro_report_pipeline import (
    _expand_period_sections,
    compose_report,
    load_report_plan,
)


class Store:
    def __init__(self):
        self.saved = {}

    async def read(self, *, owner_id, fingerprint, section_id):
        return self.saved.get((owner_id, fingerprint, section_id))

    async def save_if_absent(self, *, owner_id, fingerprint, section_id, text):
        return self.saved.setdefault((owner_id, fingerprint, section_id), text)


class LongFormFixtureProvider:
    def __init__(self):
        self.section_ids = []

    async def analyze_text(self, *, user_instruction, system_prompt, json_response):
        request = json.loads(user_instruction)
        self.section_ids.append(request["section_id"])
        assert "astronomical_facts" in request and system_prompt and json_response
        text = "символическая " * (request["minimum_words"] + 3)
        return json.dumps({"section_id": request["section_id"], "text": text})


def fixtures(service):
    simple = {"schema_version": "astro.natal-facts.v1", "chart": {
        "bodies": {"Sun": {"lon": 42.3}}, "aspects": [],
    }}
    if service == "natal":
        return simple
    if service == "compatibility":
        return {"schema_version": "astro.synastry-facts.v1",
                "first": simple["chart"], "second": simple["chart"],
                "aspects": [], "house_overlays": {"first_in_second": None,
                                                "second_in_first": None}}
    if service == "karma":
        return {"schema_version": "astro.karma-indicators.v1",
                "chart": simple["chart"], "indicators": {"Saturn": {"lon": 30}}}
    if service == "year":
        return {"schema_version": "astro.transit-snapshots.v1",
                "period": "2028", "samples": [
                    {"date": f"2028-{m:02d}-01", "bodies": {"Sun": {"lon": m}}}
                    for m in range(1, 13)], "natal_chart": simple["chart"]}
    if service == "month":
        return {"schema_version": "astro.transit-snapshots.v1",
                "period": "2028-02", "samples": [
                    {"date": f"2028-02-{d:02d}", "bodies": {"Sun": {"lon": d}}}
                    for d in range(1, calendar.monthrange(2028, 2)[1] + 1)],
                "natal_chart": simple["chart"]}
    if service == "solar":
        from bot.services.astro_report_periods import build_solar_report_periods

        return build_solar_report_periods({
            "schema_version": "astro.solar-facts.v1",
            "solar_return_at_local": "2028-02-29T05:45:00+03:00",
            "return_location": {"timezone": "Europe/Moscow"},
            "solar_chart": simple["chart"],
        })
    if service == "lunar":
        return {"schema_version": "astro.lunar.v1", "period": "2028-02",
                "days": [{"date": date(2028, 2, d).isoformat(), "phase": "растущая"}
                         for d in range(1, 30)], "timezone": "Europe/Moscow"}
    raise AssertionError(service)


@pytest.mark.parametrize("service", (
    "natal", "compatibility", "karma", "year", "month", "solar", "lunar",
))
def test_entire_long_form_report_completes_all_sections_once_and_survives_resume(service):
    async def check():
        plan = load_report_plan(service)
        facts = fixtures(service)
        expected = _expand_period_sections(plan, facts)
        provider = LongFormFixtureProvider()
        store = Store()
        kwargs = {"owner_id": 123, "plan": plan, "facts": facts,
                  "secret": "only-for-tests", "store": store}
        result = await compose_report(**kwargs, provider=provider)
        assert result["status"] == "completed"
        assert result["service_id"] == service
        assert result["word_count"] >= plan.min_total_words
        assert len(result["sections"]) == len(expected)
        assert len(store.saved) == len(expected)
        assert len(provider.section_ids) == len(expected)
        assert [s["id"] for s in result["sections"]] == [s.id for s in expected]
        replay = LongFormFixtureProvider()
        again = await compose_report(**kwargs, provider=replay)
        assert result == again
        assert not replay.section_ids
    asyncio.run(check())
