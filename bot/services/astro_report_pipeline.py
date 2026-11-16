"""Sectioned astrological *interpretation* engine, isolated from astronomy and billing.

This module does NOT authorize access, provision durable storage, bill users, or
claim astrological interpretation as evidence-based. Production integration
must supply an atomic, owner-scoped checkpoint storage adapter.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

_PLAN_PATH = Path(__file__).resolve().parents[1] / "astro_report_plans.json"
_WORD_RE = re.compile(r"\b[\wА-Яа-яЁё]+(?:[-’][\wА-Яа-яЁё]+)*\b", re.UNICODE)


class AstroReportError(RuntimeError):
    """Failed or incomplete report. Never return partial text as complete."""


@dataclass(frozen=True, slots=True)
class SectionSpec:
    id: str
    title: str
    instruction: str
    min_words: int


@dataclass(frozen=True, slots=True)
class ReportPlan:
    service_id: str
    version: str
    system_prompt: str
    sections: tuple[SectionSpec, ...]
    min_total_words: int


class CheckpointStore(Protocol):
    """Atomic persistence behind owner/fingerprint key; fail closed on conflicts."""

    async def read(self, *, owner_id: int, fingerprint: str, section_id: str) -> str | None: ...

    async def save_if_absent(
        self, *, owner_id: int, fingerprint: str, section_id: str, text: str
    ) -> str: ...


class SectionTextProvider(Protocol):
    async def analyze_text(
        self,
        *,
        user_instruction: str,
        system_prompt: str | None = None,
        json_response: bool = True,
    ) -> str: ...


def load_report_plan(service_id: str, *, path: Path | None = None) -> ReportPlan:
    """External versioned config; prices/models/URLs never defined here."""
    raw = json.loads((path or _PLAN_PATH).read_text(encoding="utf-8"))
    if raw.get("schema_version") != "astro.report-plans.v1":
        raise AstroReportError("Некорректная версия шаблонов отчёта.")
    item = raw.get("services", {}).get(service_id)
    if not isinstance(item, dict):
        raise AstroReportError("Неизвестная услуга Astro.")
    specs = tuple(
        SectionSpec(
            id=str(section["id"]),
            title=str(section["title"]),
            instruction=str(section["instruction"]),
            min_words=int(section["min_words"]),
        )
        for section in item["sections"]
    )
    if (
        not specs
        or len({section.id for section in specs}) != len(specs)
        or any(not section.id.isidentifier() or section.min_words < 1 for section in specs)
        or sum(section.min_words for section in specs) < int(item["min_total_words"])
    ):
        raise AstroReportError("Неполная или противоречивая конфигурация отчёта.")
    return ReportPlan(
        service_id=service_id,
        version=str(item["version"]),
        system_prompt=str(raw["system_prompt"]),
        sections=specs,
        min_total_words=int(item["min_total_words"]),
    )


def _fact_catalog(facts: dict) -> dict[str, Any]:
    """Expose only curated versioned astronomical evidence, not arbitrary PII."""
    if not isinstance(facts, dict) or "schema_version" not in facts:
        raise AstroReportError("Отсутствуют исходные расчётные факты.")
    # High-level data are versioned separately, so an interpreter cannot
    # invent planets or aspects by reading user-entered free text.
    fields = (
        "schema_version", "chart", "first", "second", "aspects", "indicators",
        "natal_chart", "solar_chart", "samples", "events", "days",
        "accuracy", "first_accuracy", "second_accuracy", "period",
        "solar_return_at_utc", "return_location", "engine",
        # Current MIT ephemerides output (natal #550, compatibility #553).
        # Only these deterministic result fields may reach the interpreter;
        # never forward arbitrary client form/profile text.
        "positions", "cross_aspects", "person_a", "person_b",
        "birth_time_known", "not_calculated", "warnings", "aspect_orbs_deg",
        "utc_reference", "local_reference", "timezone",
    )
    selected = {name: facts[name] for name in fields if name in facts}
    if len(selected) < 2:
        raise AstroReportError("Недостаточно проверенных астрономических фактов.")
    return selected


def report_fingerprint(
    *,
    owner_id: int,
    plan: ReportPlan,
    facts: dict,
    secret: str,
) -> str:
    """HMAC prevents low-entropy dates from being trivially brute-forced."""
    if type(owner_id) is not int or owner_id <= 0 or not secret:
        raise AstroReportError("Не задан владелец или секрет для идемпотентности.")
    canonical = json.dumps(
        {"owner": owner_id, "service": plan.service_id, "plan": plan.version,
         "facts": _fact_catalog(facts)},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _word_count(value: str) -> int:
    return len(_WORD_RE.findall(value))


def _parse_section(raw: str, spec: SectionSpec) -> str:
    """Require structured section, not hallucinated external citations."""
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AstroReportError("Неверный формат текстового раздела.") from exc
    if not isinstance(doc, dict) or doc.get("section_id") != spec.id:
        raise AstroReportError("Ответ модели относится к другому разделу.")
    text = doc.get("text")
    if not isinstance(text, str) or _word_count(text) < spec.min_words:
        raise AstroReportError("Раздел недостаточно подробный; не отмечаем готовым.")
    if len(text) > 180_000 or "\x00" in text:
        raise AstroReportError("Повреждённый раздел отчёта.")
    return text.strip()


async def compose_report(
    *,
    owner_id: int,
    plan: ReportPlan,
    facts: dict,
    secret: str,
    store: CheckpointStore,
    provider: SectionTextProvider,
) -> dict:
    """Resume independent sections from durable store; never return partial as done.

    Requires caller to enforce admin rights before every invocation, and the
    store to atomically bind owner+HMAC+section. No retry loops here: the
    existing configured LLM adapter handles retries. A failure can be resumed
    without regenerating committed sections or double billing.
    """
    fingerprint = report_fingerprint(owner_id=owner_id, plan=plan, facts=facts, secret=secret)
    available = _fact_catalog(facts)
    fact_json = json.dumps(
        available, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    if len(fact_json.encode("utf-8")) > 150_000:
        raise AstroReportError("Слишком большой объём исходных фактов.")
    sections: list[dict] = []
    for section in plan.sections:
        prior = await store.read(owner_id=owner_id, fingerprint=fingerprint, section_id=section.id)
        if prior is not None:
            # Treat tampered/corrupt checkpoint as error; never silently accept it.
            if _word_count(prior) < section.min_words:
                raise AstroReportError("Сохранённый раздел не прошёл проверку целостности.")
            text = prior
        else:
            request = {
                "service": plan.service_id,
                "template_version": plan.version,
                "section_id": section.id,
                "section_title": section.title,
                "section_instruction": section.instruction,
                "minimum_words": section.min_words,
                "astronomical_facts": available,
                "response_schema": {"section_id": section.id, "text": "<русский текст раздела>"},
            }
            response = await provider.analyze_text(
                user_instruction=json.dumps(request, ensure_ascii=False),
                system_prompt=plan.system_prompt,
                json_response=True,
            )
            candidate = _parse_section(response, section)
            text = await store.save_if_absent(
                owner_id=owner_id, fingerprint=fingerprint,
                section_id=section.id, text=candidate,
            )
            if _word_count(text) < section.min_words:
                raise AstroReportError("Недостоверное содержимое контрольной точки.")
        sections.append({"id": section.id, "title": section.title, "text": text})

    total = sum(_word_count(section["text"]) for section in sections)
    if total < plan.min_total_words:
        raise AstroReportError("Отчёт не достигает согласованной полноты.")
    return {
        "schema_version": "astro.report.v1",
        "service_id": plan.service_id,
        "template_version": plan.version,
        "fingerprint": fingerprint,
        "status": "completed",
        "word_count": total,
        "sections": sections,
        "disclaimer": (
            "Астрологический разбор является символической интерпретацией. "
            "Он не заменяет медицинскую, финансовую или профессиональную консультацию."
        ),
    }
