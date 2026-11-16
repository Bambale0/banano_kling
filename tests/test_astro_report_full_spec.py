"""Regression: seven full original owner specifications, not a 12-card generic horoscope."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from bot.services.astro_report_pipeline import (
    AstroReportError,
    load_report_plan,
    report_fingerprint,
)

# Source-derived report sections, excluding computation input and format-only chapters.
REPORT_SPECS = {
    "natal": (18, 10_000),
    "compatibility": (25, 10_000),
    "karma": (27, 8_000),
    "year": (29, 12_000),
    "month": (23, 5_000),
    "solar": (21, 12_000),
    "lunar": (14, 5_000),
}


@pytest.mark.parametrize("service_id,expected", REPORT_SPECS.items())
def test_full_owner_spec_coverage_and_minimum_words(service_id, expected):
    expected_count, expected_min = expected
    plan = load_report_plan(service_id)
    assert len(plan.sections) == expected_count
    assert plan.min_total_words == expected_min
    assert sum(s.min_words for s in plan.sections) >= expected_min
    assert [s.id for s in plan.sections] == [f"section_{i:02d}" for i in range(3, expected_count + 3)]
    assert all(s.instruction and s.title for s in plan.sections)
    assert "astronomical_facts" in plan.system_prompt
    assert "КРИТИЧЕСКОЕ ПРАВИЛО" in plan.system_prompt
    assert "неизвестн" in plan.system_prompt.lower() or "отсутствующ" in plan.system_prompt.lower()


def test_malformed_mutable_config_fails_closed(tmp_path):
    source = Path(__file__).resolve().parents[1] / "bot/astro_report_plans.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    data["services"]["natal"]["sections"][0]["min_words"] = True
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(AstroReportError, match="конфигурация"):
        load_report_plan("natal", path=path)



def test_real_lunar_calendar_requires_every_date_and_handles_leap_year():
    from bot.services.astro_report_pipeline import _expand_period_sections
    plan = load_report_plan("lunar")
    facts = {
        "period": "2024-02",
        "days": [{"date": f"2024-02-{day:02d}"} for day in range(1, 30)],
    }
    full = _expand_period_sections(plan, facts)
    dynamic = full[len(plan.sections):]
    assert len(dynamic) == 29
    assert dynamic[0].id == "day_20240201"
    assert dynamic[-1].id == "day_20240229"
    assert all(section.min_words >= 1 for section in dynamic)

    for bad in (
        facts["days"][:-1], facts["days"] + [facts["days"][-1]],
        list(reversed(facts["days"])),
    ):
        with pytest.raises(AstroReportError, match="неполны|дублированы|перепутаны"):
            _expand_period_sections(plan, {**facts, "days": bad})


def test_yearly_months_require_exact_twelve_calculated_rows():
    from bot.services.astro_report_pipeline import _expand_period_sections
    plan = load_report_plan("year")
    facts = {
        "period": "2026",
        "samples": [{"date": f"2026-{month:02d}-01"} for month in range(1, 13)],
    }
    result = _expand_period_sections(plan, facts)
    assert len(result) == len(plan.sections) + 12
    assert result[-1].id == "month_20261201"
    with pytest.raises(AstroReportError, match="неполны|дублированы|перепутаны"):
        _expand_period_sections(plan, {**facts, "samples": facts["samples"][:11]})
    with pytest.raises(AstroReportError, match="Отсутствуют"):
        _expand_period_sections(plan, {**facts, "samples": None})


def test_solar_requires_real_twelve_periods_not_a_fake_template():
    from bot.services.astro_report_pipeline import _expand_period_sections
    with pytest.raises(AstroReportError, match="расчётные факты"):
        _expand_period_sections(load_report_plan("solar"), {"period": "2026"})


def test_report_fingerprint_changes_when_prompt_changes_without_version_bump():
    plan = load_report_plan("natal")
    facts = {
        "schema_version": "astro.natal.facts.v1",
        "positions": {"Sun": {"longitude_deg": 29.1}},
    }
    a = report_fingerprint(owner_id=777, plan=plan, facts=facts, secret="local-test-only")
    b = report_fingerprint(owner_id=777, plan=replace(plan, system_prompt=plan.system_prompt + " changed"), facts=facts, secret="local-test-only")
    assert a != b
