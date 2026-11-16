"""Config-driven Astro report assembly; checkpoint and failure contracts."""

import asyncio
import json
from dataclasses import replace

import pytest

from bot.services.astro_report_pipeline import (
    AstroReportError,
    ReportPlan,
    SectionSpec,
    compose_report,
    load_report_plan,
    report_fingerprint,
)


class Checkpoints:
    def __init__(self):
        self.saved = {}

    async def read(self, *, owner_id, fingerprint, section_id):
        return self.saved.get((owner_id, fingerprint, section_id))

    async def save_if_absent(self, *, owner_id, fingerprint, section_id, text):
        key = (owner_id, fingerprint, section_id)
        return self.saved.setdefault(key, text)


class Provider:
    def __init__(self, fail_at=None, short=False):
        self.calls = []
        self.fail_at = fail_at
        self.short = short

    async def analyze_text(self, *, user_instruction, system_prompt, json_response):
        payload = json.loads(user_instruction)
        self.calls.append(payload)
        assert json_response is True
        assert system_prompt
        if len(self.calls) == self.fail_at:
            raise TimeoutError("provider temporarily unavailable")
        words = "Мягкая интерпретация проверенных данных без прогнозов. " * (
            1 if self.short else 4
        )
        return json.dumps({"section_id": payload["section_id"], "text": words})


def plan():
    return ReportPlan(
        "natal", "1.0-test", "Тестовая роль: не придумывай факты.",
        (
            SectionSpec("one", "Начало", "Обзор", 5),
            SectionSpec("two", "Продолжение", "Детали", 5),
        ),
        10,
    )


def facts():
    return {
        "schema_version": "astro.natal-facts.v1",
        "chart": {"bodies": {"Sun": {"lon": 42.5}}},
    }


def compose(*, owner=19, given_plan=None, given_facts=None, store=None, provider=None):
    return asyncio.run(compose_report(
        owner_id=owner,
        plan=given_plan or plan(),
        facts=given_facts or facts(),
        secret="fake-secret-for-test-only",
        store=store or Checkpoints(),
        provider=provider or Provider(),
    ))


def test_seven_services_have_versioned_long_report_plans():
    for name in ("natal", "compatibility", "karma", "year", "month", "solar", "lunar"):
        loaded = load_report_plan(name)
        assert loaded.service_id == name
        assert loaded.version
        assert len(loaded.sections) >= 8
        assert sum(section.min_words for section in loaded.sections) >= loaded.min_total_words
        assert loaded.min_total_words >= 5000


def test_complete_report_has_stable_fingerprint_and_no_fictional_state():
    provider, store = Provider(), Checkpoints()
    result = compose(store=store, provider=provider)
    assert result["status"] == "completed"
    assert result["schema_version"] == "astro.report.v1"
    assert len(result["sections"]) == 2
    assert result["word_count"] >= 10
    assert len(provider.calls) == 2
    assert "provider" not in result
    assert "birthplace" not in provider.calls[0]["astronomical_facts"]


def test_resume_after_provider_error_reuses_checkpoint_instead_of_charging_again():
    store = Checkpoints()
    first = Provider(fail_at=2)
    with pytest.raises(TimeoutError):
        compose(store=store, provider=first)
    assert len(store.saved) == 1
    second = Provider()
    result = compose(store=store, provider=second)
    assert result["status"] == "completed"
    assert len(second.calls) == 1
    assert second.calls[0]["section_id"] == "two"
    assert len(store.saved) == 2
    third = Provider()
    compose(store=store, provider=third)
    assert not third.calls


def test_owner_and_source_data_are_part_of_scoped_identity():
    report_plan = plan()
    a = report_fingerprint(owner_id=19, plan=report_plan, facts=facts(), secret="s")
    b = report_fingerprint(owner_id=20, plan=report_plan, facts=facts(), secret="s")
    c = report_fingerprint(
        owner_id=19, plan=report_plan,
        facts={"schema_version": "astro.natal-facts.v1", "chart": {"bodies": {"Sun": {"lon": 41}}}},
        secret="s",
    )
    d = report_fingerprint(
        owner_id=19, plan=replace(report_plan, version="1.1"),
        facts=facts(), secret="s",
    )
    assert len({a, b, c, d}) == 4


def test_short_response_does_not_commit_or_fake_completion():
    store = Checkpoints()
    with pytest.raises(AstroReportError, match="недостаточно"):
        compose(store=store, provider=Provider(short=True), given_plan=replace(
            plan(), sections=(SectionSpec("one", "Начало", "Обзор", 45),),
            min_total_words=45,
        ))
    assert not store.saved


def test_corrupt_existing_checkpoint_fails_closed():
    store = Checkpoints()
    fp = report_fingerprint(owner_id=19, plan=plan(), facts=facts(), secret="fake-secret-for-test-only")
    store.saved[(19, fp, "one")] = "коротко"
    with pytest.raises(AstroReportError, match="целостности"):
        compose(store=store)


@pytest.mark.parametrize("service_id", ["", "unknown", "../../secret", None])
def test_unknown_service_cannot_select_external_template(service_id):
    with pytest.raises(AstroReportError):
        load_report_plan(service_id)


@pytest.mark.parametrize("owner", [0, -1, True, "19"])
def test_invalid_owner_fails_before_provider(owner):
    store, provider = Checkpoints(), Provider()
    with pytest.raises(AstroReportError):
        compose(owner=owner, store=store, provider=provider)
    assert not provider.calls
