"""Regression: NEUROMIX ASTROLOGY PRO solar prompt and historical tasks."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.services.astro_report_pipeline import load_report_plan, report_fingerprint
from bot.services.astro_report_worker import resolve_astro_job_plan

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/astro/solar-system-pro-20261120.md"
CONFIG = ROOT / "bot/astro_report_plans.json"
ARCHIVE = ROOT / "bot/astro_report_plans_solar_v2_legacy.json"


def test_exact_owner_solar_instruction_active_and_isolated():
    source = SOURCE.read_text(encoding="utf-8")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    plan = load_report_plan("solar")

    assert source == config["services"]["solar"]["service_instructions"]
    assert plan.version == "3.0.0-astrology-pro-solar-20261120"
    assert source in plan.system_prompt
    assert plan.system_prompt.startswith(config["system_prompt"])
    assert plan.system_prompt.endswith(config["system_prompt"])
    assert "Обращайся к пользователю на «Вы»" in source
    assert "точный момент возвращения Солнца к натальной долготе" in source
    assert "место рождения и место соляра совпадают" in source
    assert "символическую интерпретацию" in source
    assert "а не механическое деление на месяцы" in source
    assert "источник/версию расчётного движка" in source
    assert len(plan.sections) == 17
    assert [sec.id for sec in plan.sections] == [
        f"section_{n:02d}" for n in range(1, 18)
    ]
    assert plan.dynamic_period is None
    assert plan.min_total_words == 765
    assert sum(section.min_words for section in plan.sections) == 765
    for i, section in enumerate(plan.sections, start=1):
        assert f"{i}.\t{section.title}" in source

    for other in ("natal", "compatibility", "karma", "year", "month", "lunar"):
        assert "МОДУЛЬ: СОЛЯР — ПЕРСОНАЛЬНЫЙ ПРОГНОЗ" not in load_report_plan(other).system_prompt


@pytest.mark.parametrize("generation_scoped", [False, True])
def test_existing_solar_v2_job_keeps_signed_template(generation_scoped):
    old = load_report_plan("solar", path=ARCHIVE)
    assert old.version == "2.0.0-full-original-20261115"
    assert len(old.sections) == 21
    assert old.dynamic_period is not None
    assert old.min_total_words == 12_000

    facts = {
        "schema_version": "astro.solar.facts.v1",
        "solar_return_at_utc": "2026-11-20T12:00:00+00:00",
    }
    secret, job_id, owner_id = "fixture-for-solar-legacy-hmac", "a" * 32, 741
    signature = report_fingerprint(
        owner_id=owner_id, plan=old, facts=facts, secret=secret,
        generation_id=job_id if generation_scoped else None,
    )
    job = SimpleNamespace(job_id=job_id, owner_id=owner_id,
                          service_id="solar", facts=facts, fingerprint=signature)
    selected, effective_generation_id = resolve_astro_job_plan(job, secret)
    assert selected.version == old.version
    assert selected.system_prompt == old.system_prompt
    assert selected.sections == old.sections
    assert effective_generation_id == (job_id if generation_scoped else None)


def test_new_solar_signed_plan_and_tamper_rejection():
    current = load_report_plan("solar")
    facts = {"schema_version": "astro.solar.facts.v1", "period": "2026"}
    secret, job_id = "fixture-for-new-solar-hmac", "b" * 32
    signed = report_fingerprint(owner_id=77, plan=current, facts=facts,
                                secret=secret, generation_id=job_id)
    job = SimpleNamespace(job_id=job_id, owner_id=77,
                          service_id="solar", facts=facts, fingerprint=signed)
    selected, generation_id = resolve_astro_job_plan(job, secret)
    assert selected.version == current.version
    assert generation_id == job_id
    job.fingerprint = "0" * 64
    with pytest.raises(ValueError, match="template changed"):
        resolve_astro_job_plan(job, secret)
