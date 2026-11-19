"""Annual forecast instructions, factual period policy, and historical job HMAC compatibility."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.services.astro_report_pipeline import (
    AstroReportError,
    _expand_period_sections,
    load_report_plan,
    report_fingerprint,
)
from bot.services.astro_report_worker import resolve_astro_job_plan

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/astro/year-system-20261119.md"
CONFIG = ROOT / "bot/astro_report_plans.json"
ARCHIVE = ROOT / "bot/astro_report_plans_year_v2_legacy.json"


def test_current_annual_prompt_is_original_source_and_isolation():
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    source = SOURCE.read_text(encoding="utf-8")
    plan = load_report_plan("year")
    assert raw["services"]["year"]["service_instructions"] == source
    assert source in plan.system_prompt
    assert plan.system_prompt.startswith(raw["system_prompt"])
    assert plan.system_prompt.endswith(raw["system_prompt"])
    assert plan.version == "3.0.0-personal-year-forecast-20261119"
    assert "Обращайся к пользователю на «Вы»" in source
    assert "Не подменяй годовой прогноз соляром" in source
    assert "качество" in source.lower()
    for other in ("natal", "compatibility", "karma", "month", "solar", "lunar"):
        assert source not in load_report_plan(other).system_prompt


def test_annual_new_twelve_sections_are_not_padded_with_monthly_events():
    plan = load_report_plan("year")
    assert len(plan.sections) == 12
    assert plan.dynamic_period is None
    assert [s.id for s in plan.sections] == [f"section_{i:02d}" for i in range(1, 13)]
    assert plan.min_total_words == 2500
    assert sum(s.min_words for s in plan.sections) >= plan.min_total_words
    assert "НЕ точные даты аспектов" in plan.sections[8].instruction
    assert "соляр" not in plan.sections[0].title.lower()
    assert "только при" in plan.sections[9].instruction.lower()


def _year_facts(samples=None):
    return {"schema_version": "astro.transit-snapshots.v1", "scope": "year",
            "period": "2028", "samples": (
                samples if samples is not None else
                [{"date": f"2028-{m:02d}-01"} for m in range(1, 13)]
            )}


def test_twelve_snapshots_verified_but_not_promoted_to_event_chapters():
    plan = load_report_plan("year")
    facts = _year_facts()
    assert _expand_period_sections(plan, facts) == plan.sections
    for invalid in (facts["samples"][:11], list(reversed(facts["samples"])),
                    facts["samples"] + [facts["samples"][-1]]):
        with pytest.raises(AstroReportError, match="неполны|дублированы|перепутаны"):
            _expand_period_sections(plan, _year_facts(invalid))
    with pytest.raises(AstroReportError, match="Отсутствуют"):
        _expand_period_sections(plan, {"period": "2028"})


@pytest.mark.parametrize("isolated_generation_id", [False, True])
def test_existing_year_jobs_retain_original_signed_plan(isolated_generation_id):
    old = load_report_plan("year", path=ARCHIVE)
    current = load_report_plan("year")
    assert old.version == "2.0.0-full-original-20261115"
    assert len(old.sections) == 29
    assert old.dynamic_period is not None
    facts = _year_facts()
    job_id = "0123456789abcdef0123456789abcdef"
    secret = "test-only-year-hmac-secret"
    fp = report_fingerprint(
        owner_id=21, plan=old, facts=facts, secret=secret,
        generation_id=job_id if isolated_generation_id else None,
    )
    job = SimpleNamespace(job_id=job_id, owner_id=21, facts=facts,
                          fingerprint=fp, service_id="year")
    plan, generation_id = resolve_astro_job_plan(job, secret)
    assert plan.version == old.version
    assert plan.sections == old.sections
    assert generation_id == (job_id if isolated_generation_id else None)
    job.fingerprint = report_fingerprint(
        owner_id=21, plan=current, facts=facts, secret=secret, generation_id=job_id)
    selected, gen = resolve_astro_job_plan(job, secret)
    assert selected.version == current.version and gen == job_id
    job.fingerprint = "a" * 64
    with pytest.raises(ValueError, match="template changed"):
        resolve_astro_job_plan(job, secret)
