"""NEUROMIX ASTROLOGY PRO karma instruction and historical HMAC job regression."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.services.astro_report_pipeline import load_report_plan, report_fingerprint
from bot.services.astro_report_worker import resolve_astro_job_plan

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/astro/karma-system-pro-20261120.md"
CONFIG = ROOT / "bot/astro_report_plans.json"
ARCHIVE = ROOT / "bot/astro_report_plans_karma_v2_legacy.json"


def test_complete_owner_karma_instruction_active_only_for_karma():
    source = SOURCE.read_text(encoding="utf-8")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    karma = config["services"]["karma"]
    plan = load_report_plan("karma")

    assert karma["service_instructions"] == source
    assert plan.version == "3.0.0-astrology-pro-karma-20261120"
    assert source in plan.system_prompt
    assert plan.system_prompt.startswith(config["system_prompt"])
    assert plan.system_prompt.endswith(config["system_prompt"])
    assert "Обращайся к пользователю на «Вы»" in source
    assert "Северный и Южный лунные узлы" in source
    assert "8-й и 12-й дома" in source
    assert "если время рождения надёжно" in source
    assert "не приписывай человеку конкретные события" in source.lower()
    assert "научно доказанный" in source
    assert "5–10 реалистичных рекомендаций" in source
    assert "разделяй исходные расчётные данные" in source.lower()
    assert len(plan.sections) == 17
    assert [s.id for s in plan.sections] == [f"section_{n:02d}" for n in range(1, 18)]
    assert plan.min_total_words == 765
    assert sum(s.min_words for s in plan.sections) == 765
    assert plan.dynamic_period is None
    assert all(f"{n}.\t{section.title}" in source for n, section in enumerate(plan.sections, 1))

    for service_id in ("natal", "compatibility", "year", "month", "solar", "lunar"):
        assert "МОДУЛЬ: КАРМА, КАРМИЧЕСКИЕ УРОКИ" not in load_report_plan(service_id).system_prompt


@pytest.mark.parametrize("per_generation", [False, True])
def test_existing_signed_karma_v2_jobs_keep_original_template(per_generation):
    legacy = load_report_plan("karma", path=ARCHIVE)
    assert legacy.version == "2.0.0-full-original-20261115"
    assert len(legacy.sections) == 27
    assert legacy.min_total_words == 8_000
    facts = {
        "schema_version": "astro.karma.facts.v1",
        "chart": {"bodies": {"Sun": {"lon": 32.5}}},
    }
    owner, job_id, secret = 423, "k" * 32, "karma-v2-only-hmac-test-key"
    signature = report_fingerprint(
        owner_id=owner, plan=legacy, facts=facts, secret=secret,
        generation_id=job_id if per_generation else None,
    )
    job = SimpleNamespace(job_id=job_id, owner_id=owner,
                          service_id="karma", facts=facts, fingerprint=signature)
    selected, generation = resolve_astro_job_plan(job, secret)
    assert selected.version == legacy.version
    assert selected.sections == legacy.sections
    assert selected.system_prompt == legacy.system_prompt
    assert generation == (job_id if per_generation else None)


def test_new_karma_hmac_authentic_and_tampering_fails_closed():
    plan = load_report_plan("karma")
    facts = {"schema_version": "astro.karma.facts.v1", "chart": {}}
    owner, job_id, secret = 423, "z" * 32, "karma-v3-only-hmac-test-key"
    signature = report_fingerprint(
        owner_id=owner, plan=plan, facts=facts, secret=secret, generation_id=job_id,
    )
    job = SimpleNamespace(job_id=job_id, owner_id=owner,
                          service_id="karma", facts=facts, fingerprint=signature)
    selected, generation = resolve_astro_job_plan(job, secret)
    assert selected.version == plan.version
    assert generation == job_id
    job.fingerprint = "0" * 64
    with pytest.raises(ValueError, match="template changed"):
        resolve_astro_job_plan(job, secret)
