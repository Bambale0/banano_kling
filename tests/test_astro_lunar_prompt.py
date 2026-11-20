"""Regression for the owner-authored lunar calendar prompt and data-driven rows."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.services.astro_report_pipeline import (
    AstroReportError,
    _expand_period_sections,
    compose_report,
    load_report_plan,
    report_fingerprint,
)
from bot.services.astro_report_worker import resolve_astro_job_plan

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/astro/lunar-system-pro-20261120.md"
CONFIG = ROOT / "bot/astro_report_plans.json"
ARCHIVE = ROOT / "bot/astro_report_plans_lunar_v2_legacy.json"


def _facts(*, leap=True):
    month = "2024-02" if leap else "2026-11"
    total = 29 if leap else 30
    return {
        "schema_version": "astro.lunar.v1",
        "period": month,
        "timezone": "Europe/Berlin",
        "engine": {"name": "astronomy-engine", "version": "2.1.19"},
        "lunar_day_convention": "elapsed UTC 24h since new Moon; not moonrise-based",
        "calendar_place": {
            "name": "Berlin", "country_code": "DE", "place_id": 2950159,
            "timezone": "Europe/Berlin", "source": "GeoNames",
        },
        "days": [
            {"date": f"{month}-{n:02d}", "moon_sign": "Овен",
             "phase": "растущая", "synodic_day": n}
            for n in range(1, total + 1)
        ],
        "ingresses": [{
            "at_utc": f"{month}-05T10:00:00+00:00",
            "at_local": f"{month}-05T11:00:00+01:00",
            "moon_sign": "Телец",
        }],
        "events": [{
            "kind": "новолуние",
            "at_utc": f"{month}-10T10:00:00+00:00",
            "at_local": f"{month}-10T11:00:00+01:00",
            "local_date": f"{month}-10",
        }],
        "not_calculated": ["void_of_course", "planetary_aspects"],
    }


def test_complete_lunar_source_active_and_isolated():
    source = SOURCE.read_text(encoding="utf-8")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    plan = load_report_plan("lunar")
    assert config["services"]["lunar"]["service_instructions"] == source
    assert source in plan.system_prompt
    assert plan.version == "3.0.0-astrology-pro-lunar-20261120"
    assert plan.system_prompt.startswith(config["system_prompt"])
    assert plan.system_prompt.endswith(config["system_prompt"])
    assert "Обращайся к пользователю на «Вы»" in source
    assert "Если запрос общий, не требуй данные рождения" in source
    assert "Календарная таблица должна быть полной" in source
    assert "неблагоприятными для медицинских процедур" in source
    assert len(plan.sections) == 10
    assert [s.id for s in plan.sections] == [f"section_{n:02d}" for n in range(1, 11)]
    assert all(f"{i}.\t{section.title}" in source
               for i, section in enumerate(plan.sections, 1))
    assert plan.dynamic_period is None
    assert plan.min_total_words == 405
    assert sum(s.min_words for s in plan.sections[:9]) == plan.min_total_words
    for name in ("natal", "compatibility", "karma", "year", "month", "solar"):
        assert "МОДУЛЬ: ПЕРСОНАЛЬНЫЙ ЛУННЫЙ КАЛЕНДАРЬ" not in load_report_plan(name).system_prompt


def test_generic_calendar_only_nine_sections_personal_only_with_natal_facts():
    plan = load_report_plan("lunar")
    generic = _expand_period_sections(plan, _facts())
    assert len(generic) == 9
    assert generic[2].id == "section_03"
    personal = _expand_period_sections(plan, {
        **_facts(), "natal_chart": {"bodies": {"Moon": {"lon": 123.4}}},
    })
    assert len(personal) == 10
    assert personal[-1].id == "section_10"


@pytest.mark.parametrize("bad", ["missing", "duplicated", "reversed", "out_of_month"])
def test_lunar_calendar_must_have_every_civil_day_exactly_once(bad):
    plan, facts = load_report_plan("lunar"), _facts()
    rows = list(facts["days"])
    if bad == "missing":
        rows.pop()
    elif bad == "duplicated":
        rows.append(rows[-1])
    elif bad == "reversed":
        rows.reverse()
    elif bad == "out_of_month":
        rows[-1] = {**rows[-1], "date": "2024-03-01"}
    with pytest.raises(AstroReportError, match="неполны|дублированы|перепутаны"):
        _expand_period_sections(plan, {**facts, "days": rows})


@pytest.mark.parametrize("per_generation", [False, True])
def test_lunar_old_signed_jobs_keep_v2_template_and_fingerprint(per_generation):
    legacy = load_report_plan("lunar", path=ARCHIVE)
    assert legacy.version == "2.0.0-full-original-20261115"
    assert len(legacy.sections) == 14
    assert legacy.dynamic_period is not None
    assert legacy.min_total_words == 5_000
    facts = _facts()
    secret, job_id = "lunar-legacy-signed-test-key", "a" * 32
    signature = report_fingerprint(
        owner_id=62, plan=legacy, facts=facts, secret=secret,
        generation_id=job_id if per_generation else None,
    )
    job = SimpleNamespace(owner_id=62, job_id=job_id,
                          service_id="lunar", facts=facts, fingerprint=signature)
    resolved, generation_id = resolve_astro_job_plan(job, secret)
    assert resolved.sections == legacy.sections
    assert resolved.system_prompt == legacy.system_prompt
    assert generation_id == (job_id if per_generation else None)


def test_new_lunar_signature_authenticates_exact_events_and_rejects_tampering():
    plan, facts = load_report_plan("lunar"), _facts()
    secret, job_id = "lunar-v3-signed-test-key", "b" * 32
    signature = report_fingerprint(
        owner_id=62, plan=plan, facts=facts, secret=secret, generation_id=job_id,
    )
    job = SimpleNamespace(owner_id=62, job_id=job_id, service_id="lunar",
                          facts=facts, fingerprint=signature)
    assert resolve_astro_job_plan(job, secret)[0].version == plan.version
    altered = {**facts, "ingresses": [{**facts["ingresses"][0], "moon_sign": "Рак"}]}
    job.facts = altered
    with pytest.raises(ValueError, match="template changed"):
        resolve_astro_job_plan(job, secret)
    job.fingerprint = "0" * 64
    with pytest.raises(ValueError, match="template changed"):
        resolve_astro_job_plan(job, secret)


class Store:
    def __init__(self):
        self.saved = {}

    async def read(self, *, owner_id, fingerprint, section_id):
        return self.saved.get((owner_id, fingerprint, section_id))

    async def save_if_absent(self, *, owner_id, fingerprint, section_id, text):
        return self.saved.setdefault((owner_id, fingerprint, section_id), text)


class Provider:
    def __init__(self, *, truncate_first=False):
        self.calls = []
        self.truncate_first = truncate_first

    async def analyze_text(self, *, user_instruction, system_prompt, json_response):
        request = json.loads(user_instruction)
        self.calls.append((request, system_prompt))
        assert json_response is True
        if request["section_id"] == "section_03":
            rows = request["astronomical_facts"]["days"]
            if self.truncate_first:
                self.truncate_first = False
                rows = rows[:-1]
            text = "| Дата | Фаза | Знак | Совет |\n| --- | --- | --- | --- |\n"
            text += "".join(
                f"| {row['date']} | растущая | Овен | Планируйте бережно. |\n"
                for row in rows
            )
            text += "Астрономический расчёт отличается от символического совета. " * 40
        else:
            text = "Это символическая традиция, а не установленное влияние на судьбу. " * 20
        return json.dumps({"section_id": request["section_id"], "text": text},
                          ensure_ascii=False)


def test_complete_short_month_passes_new_real_pipeline_with_all_rows_and_ingresses():
    facts = _facts()
    provider = Provider()
    plan = load_report_plan("lunar")
    report = asyncio.run(compose_report(
        owner_id=62, plan=plan, facts=facts,
        secret="lunar-integration-test-only", store=Store(), provider=provider,
    ))
    assert report["status"] == "completed"
    assert len(report["sections"]) == 9
    assert len(provider.calls) == 9
    assert all(call[1] == plan.system_prompt for call in provider.calls)
    supplied = provider.calls[0][0]["astronomical_facts"]
    assert supplied["calendar_place"]["name"] == "Berlin"
    assert supplied["lunar_day_convention"] == facts["lunar_day_convention"]
    assert supplied["ingresses"] == facts["ingresses"]
    table = report["sections"][2]["text"]
    assert all(f"| {row['date']} |" in table for row in facts["days"])


def test_incomplete_llm_table_rejected_and_retried_before_completion():
    provider = Provider(truncate_first=True)
    report = asyncio.run(compose_report(
        owner_id=62, plan=load_report_plan("lunar"), facts=_facts(),
        secret="lunar-incomplete-table-test", store=Store(), provider=provider,
    ))
    assert report["status"] == "completed"
    attempts = [call for call, _ in provider.calls
                if call["section_id"] == "section_03"]
    assert len(attempts) == 2
    assert attempts[-1]["validation_feedback"]["reason"] == "incomplete_lunar_table"
