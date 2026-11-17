"""Solar report month intervals begin at the real return, not January 1."""
from datetime import datetime

import pytest

from bot.services.astro_report_periods import build_solar_report_periods
from bot.services.astro_report_pipeline import (
    AstroReportError,
    _expand_period_sections,
    load_report_plan,
)


def solar():
    return {"schema_version": "astro.solar-facts.v1",
            "solar_return_at_local": "2028-02-29T05:45:00+01:00",
            "return_location": {"timezone": "Europe/Berlin"},
            "solar_chart": {"bodies": {"Sun": {"lon": 340}}}}


def test_real_local_solar_year_covers_12_intervals_across_dst_and_leap_day():
    facts = build_solar_report_periods(solar())
    periods = facts["periods"]
    assert len(periods) == 12
    assert facts["period"] == "2028"
    assert periods[0]["start_at_local"] == "2028-02-29T05:45:00+01:00"
    assert periods[0]["end_at_local"] == "2028-03-29T05:45:00+02:00"
    assert periods[-1]["end_at_local"] == "2029-02-28T05:45:00+01:00"
    assert all(datetime.fromisoformat(p["start_at_local"]).tzinfo for p in periods)
    plan = load_report_plan("solar")
    sections = _expand_period_sections(plan, facts)
    assert len(sections) == len(plan.sections) + 12
    assert "2028-02-29" in sections[len(plan.sections)].title
    assert "2029-01-29" in sections[-1].title


def test_forged_calendar_year_months_are_not_accepted_as_solar_intervals():
    facts = build_solar_report_periods(solar())
    facts["periods"] = [{"date": f"2028-{month:02d}-01"} for month in range(1, 13)]
    with pytest.raises(AstroReportError):
        _expand_period_sections(load_report_plan("solar"), facts)


def test_missing_return_time_cannot_create_fake_solar_intervals():
    with pytest.raises(AstroReportError):
        build_solar_report_periods({"schema_version": "astro.solar-facts.v1"})
