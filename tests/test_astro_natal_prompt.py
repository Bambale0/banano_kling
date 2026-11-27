"""NEUROMIX ASTROLOGY PRO prompt and natal historical compatibility."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.services.astro_report_pipeline import load_report_plan, report_fingerprint
from bot.services.astro_report_worker import resolve_astro_job_plan

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/astro/natal-system-pro-20261127.md"
CONFIG = ROOT / "bot/astro_report_plans.json"
ARCHIVE_V2 = ROOT / "bot/astro_report_plans_natal_v2_legacy.json"
ARCHIVE_V3 = ROOT / "bot/astro_report_plans_natal_v3_legacy.json"
ARCHIVE_V4 = ROOT / "bot/astro_report_plans_natal_v4_legacy.json"
EXPECTED_SHA256 = "3266f907aad9c2c096bcbf850c1bc15cc0a78ed101f406e09e1ba1414149d60c"


def test_complete_uploaded_master_prompt_loaded_only_for_natal():
    source = SOURCE.read_text(encoding="utf-8")
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == EXPECTED_SHA256
    assert raw["services"]["natal"]["service_instructions"] == source
    plan = load_report_plan("natal")
    assert plan.version == "5.0.0-astrology-pro-20261127"
    assert source in plan.system_prompt
    assert plan.system_prompt.startswith(raw["system_prompt"])
    assert plan.system_prompt.endswith(raw["system_prompt"])
    assert "Обращайся к человеку на «вы»" in source
    assert "Никакой непонятной астрологической геометрии" in source
    for service in ("compatibility", "karma", "year", "month", "solar", "lunar"):
        assert source not in load_report_plan(service).system_prompt


def test_natal_plan_guarantees_all_nineteen_topics_and_twelve_houses():
    plan = load_report_plan("natal")
    assert len(plan.sections) == 30
    assert [s.id for s in plan.sections] == [f"section_{n:02d}" for n in range(1, 31)]
    assert [s.title.split(" — ")[0] for s in plan.sections[13:25]] == [f"ДОМ {n}" for n in range(1, 13)]
    import re
    source = SOURCE.read_text(encoding="utf-8")
    topics = source.split("ОБЯЗАТЕЛЬНАЯ СТРУКТУРА НАТАЛЬНОЙ КАРТЫ", 1)[1].split(
        "ОБЯЗАТЕЛЬНЫЙ ФОРМАТ КАЖДОГО ТЕМАТИЧЕСКОГО РАЗДЕЛА", 1
    )[0]
    headings = re.findall(r"^\d+\. ([А-ЯЁ][А-ЯЁ ,0-9—-]+)$", topics, re.MULTILINE)
    assert len(headings) == 19
    assert [s.title for s in (*plan.sections[:13], *plan.sections[25:])] == headings[:13] + headings[14:]
    assert "не составляй прогноз" in plan.sections[27].instruction
    assert all("без технических названий аспектов" in s.instruction for s in plan.sections)
    assert "birth_place" in plan.sections[0].instruction
    assert plan.min_total_words == 11_000
    assert sum(s.min_words for s in plan.sections) >= plan.min_total_words


@pytest.mark.parametrize("archived", [ARCHIVE_V2, ARCHIVE_V3, ARCHIVE_V4])
@pytest.mark.parametrize("with_generation_id", [False, True])
def test_old_natal_jobs_resolve_original_signed_prompt(archived, with_generation_id):
    plan = load_report_plan("natal", path=archived)
    facts = {"schema_version": "astro.natal-facts.v1", "chart": {"bodies": {"Sun": {"lon": 42.5}}}}
    job_id, secret = "0123456789abcdef0123456789abcdef", "test-only-key"
    signature = report_fingerprint(owner_id=17, plan=plan, facts=facts, secret=secret,
                                   generation_id=job_id if with_generation_id else None)
    job = SimpleNamespace(job_id=job_id, owner_id=17, service_id="natal", facts=facts, fingerprint=signature)
    selected, generation_id = resolve_astro_job_plan(job, secret)
    assert selected.version == plan.version
    assert selected.sections == plan.sections
    assert selected.system_prompt == plan.system_prompt
    assert generation_id == (job_id if with_generation_id else None)


def test_new_natal_jobs_use_v5_and_tampering_is_rejected():
    plan = load_report_plan("natal")
    facts = {"schema_version": "astro.natal-facts.v1", "chart": {"bodies": {"Sun": {"lon": 42.5}}}}
    jid, secret = "fedcba9876543210fedcba9876543210", "test-only-key"
    signature = report_fingerprint(owner_id=17, plan=plan, facts=facts, secret=secret, generation_id=jid)
    job = SimpleNamespace(job_id=jid, owner_id=17, service_id="natal", facts=facts, fingerprint=signature)
    selected, generation_id = resolve_astro_job_plan(job, secret)
    assert selected.version == plan.version
    assert len(selected.sections) == 30
    assert generation_id == jid
    job.fingerprint = "a" * 64
    with pytest.raises(ValueError, match="template changed"):
        resolve_astro_job_plan(job, secret)


def test_v4_archive_preserves_owner_source():
    old = load_report_plan("natal", path=ARCHIVE_V4)
    source = (ROOT / "docs/astro/natal-system-pro-20261119.md").read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == "2365573dd620e423e0183963d478f9602d26cb6257ab07dfd9f6c0721aba91a7"
    assert old.version == "4.0.0-astrology-pro-20261119"
    assert source in old.system_prompt
    assert len(old.sections) == 30
    assert old.min_total_words == 11_000
