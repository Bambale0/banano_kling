"""Regression: the submitted 19 Nov NEUROMIX natal system instruction.

Input file's chat-export timestamps and Markdown line escapes are not model
instructions. Its substantive content must be used only for the natal service.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.services.astro_report_pipeline import load_report_plan, report_fingerprint
from bot.services.astro_report_worker import resolve_astro_job_plan

EXPECTED_NATAL_PROMPT_SHA256 = "6cd0f785293bffbdfa24f36cc95bae83c7fd45c326ccd8102fc5507046b3f714"
LEGACY_PATH = Path(__file__).resolve().parents[1] / "bot/astro_report_plans_natal_v2_legacy.json"
NEW_BLOCKS = (
    "ТВОЙ ГЛАВНЫЙ ПОРТРЕТ",
    "ХАРАКТЕР И ВНУТРЕННИЙ МИР",
    "ЛЮБОВЬ И ОТНОШЕНИЯ",
    "ДЕНЬГИ И ФИНАНСЫ",
    "КАРЬЕРА И РЕАЛИЗАЦИЯ",
    "ТАЛАНТЫ И СИЛЬНЫЕ СТОРОНЫ",
    "СЛОЖНЫЕ СТОРОНЫ И ТОЧКИ РОСТА",
    "ГЛАВНЫЙ ВЫВОД",
)


def test_natal_uses_uploaded_system_instruction_exactly_after_chat_export_cleanup():
    import json
    raw = json.loads(
        (Path(__file__).resolve().parents[1] / "bot/astro_report_plans.json")
        .read_text(encoding="utf-8")
    )
    prompt = raw["services"]["natal"]["service_instructions"]
    assert hashlib.sha256((prompt.rstrip() + "\n").encode("utf-8")).hexdigest() == EXPECTED_NATAL_PROMPT_SHA256
    plan = load_report_plan("natal")
    assert prompt in plan.system_prompt
    assert plan.system_prompt.startswith(raw["system_prompt"])
    assert plan.system_prompt.endswith(raw["system_prompt"])  # fact gate wins
    assert "Научно доказанным" not in prompt  # source retains actual casing
    assert "Астрология является символической системой" in prompt
    assert "Не выдумывай точные даты" in prompt
    assert "Only Tm:" not in prompt


def test_natal_sections_match_submitted_eight_block_format():
    p = load_report_plan("natal")
    assert len(p.sections) == len(NEW_BLOCKS)
    assert tuple(section.title for section in p.sections) == NEW_BLOCKS
    assert p.min_total_words < 2000
    assert sum(x.min_words for x in p.sections) >= p.min_total_words
    assert p.version != load_report_plan("natal", path=LEGACY_PATH).version


def test_other_six_service_prompts_remain_isolated():
    natal = load_report_plan("natal")
    for key in ("compatibility", "karma", "year", "month", "solar", "lunar"):
        p = load_report_plan(key)
        assert p.version == "2.0.0-full-original-20261115"
        assert "РОЛЬ И ЗАДАЧА" not in p.system_prompt
        assert natal.system_prompt != p.system_prompt


@pytest.mark.parametrize("isolated", [True, False])
def test_old_natal_job_can_resume_against_archived_verified_template(isolated):
    plan = load_report_plan("natal", path=LEGACY_PATH)
    facts = {"schema_version": "astro.natal-facts.v1",
             "chart": {"bodies": {"Sun": {"lon": 34.5}}}}
    job_id = "0123456789abcdef0123456789abcdef"
    secret = "test-fingerprint-secret"
    fp = report_fingerprint(
        owner_id=101, plan=plan, facts=facts, secret=secret,
        generation_id=job_id if isolated else None,
    )
    job = SimpleNamespace(job_id=job_id, owner_id=101, facts=facts,
                          fingerprint=fp, service_id="natal")
    selected, generation = resolve_astro_job_plan(job, secret)
    assert selected.version == plan.version
    assert len(selected.sections) == 18
    assert generation == (job_id if isolated else None)


def test_new_natal_job_uses_latest_plan_without_legacy_fallback():
    plan = load_report_plan("natal")
    facts = {"schema_version": "astro.natal-facts.v1",
             "chart": {"bodies": {"Sun": {"lon": 34.5}}}}
    job_id = "fedcba9876543210fedcba9876543210"
    secret = "test-fingerprint-secret"
    fp = report_fingerprint(
        owner_id=101, plan=plan, facts=facts, secret=secret,
        generation_id=job_id,
    )
    job = SimpleNamespace(job_id=job_id, owner_id=101, facts=facts,
                          fingerprint=fp, service_id="natal")
    selected, generation = resolve_astro_job_plan(job, secret)
    assert selected.version == plan.version
    assert len(selected.sections) == 8
    assert generation == job_id


def test_tampered_fingerprint_fails_closed():
    job = SimpleNamespace(
        job_id="fedcba9876543210fedcba9876543210",
        owner_id=101,
        facts={"schema_version": "astro.natal-facts.v1", "chart": {"bodies": {}}},
        fingerprint="0" * 64,
        service_id="natal",
    )
    with pytest.raises(ValueError, match="template changed"):
        resolve_astro_job_plan(job, "test-fingerprint-secret")
