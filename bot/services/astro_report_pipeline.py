"""Sectioned astrological *interpretation* engine, isolated from astronomy and billing.

This module does NOT authorize access, provision durable storage, bill users, or
claim astrological interpretation as evidence-based. Production integration
must supply an atomic, owner-scoped checkpoint storage adapter.
"""

from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_PLAN_PATH = Path(__file__).resolve().parents[1] / "astro_report_plans.json"
_WORD_RE = re.compile(r"\b[\wА-Яа-яЁё]+(?:[-’][\wА-Яа-яЁё]+)*\b", re.UNICODE)


class AstroReportError(RuntimeError):
    """Failed or incomplete report. Never return partial text as complete."""


class AstroSectionValidationError(AstroReportError):
    """A generated section failed validation; safe reason contains no report text."""

    def __init__(self, message: str, *, reason: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SectionSpec:
    id: str
    title: str
    instruction: str
    min_words: int


@dataclass(frozen=True, slots=True)
class DynamicPeriodSpec:
    kind: str
    fact_list: str
    title_prefix: str
    instruction: str
    min_words: int


@dataclass(frozen=True, slots=True)
class ReportPlan:
    service_id: str
    version: str
    system_prompt: str
    sections: tuple[SectionSpec, ...]
    min_total_words: int
    dynamic_period: DynamicPeriodSpec | None = None


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
    try:
        raw_sections = item["sections"]
        min_total_words = item["min_total_words"]
        version = item["version"]
        global_policy = raw["system_prompt"]
        service_policy = item.get("service_instructions", "")
        if (
            not isinstance(raw_sections, list)
            or type(min_total_words) is not int
            or not 1 <= min_total_words <= 20_000
            or not isinstance(version, str) or not version.strip()
            or not isinstance(global_policy, str) or not global_policy.strip()
            or not isinstance(service_policy, str) or len(service_policy) > 120_000
        ):
            raise ValueError("Invalid report plan metadata")
        specs = tuple(
            SectionSpec(
                id=section["id"],
                title=section["title"],
                instruction=section["instruction"],
                min_words=section["min_words"],
            )
            for section in raw_sections
        )
        dynamic_config = item.get("dynamic_period")
        dynamic_period = None
        if dynamic_config is not None:
            if not isinstance(dynamic_config, dict):
                raise ValueError("Invalid dynamic section config")
            dynamic_period = DynamicPeriodSpec(
                kind=dynamic_config["kind"],
                fact_list=dynamic_config["fact_list"],
                title_prefix=dynamic_config["title_prefix"],
                instruction=dynamic_config["instruction"],
                min_words=dynamic_config["min_words"],
            )
            if (
                dynamic_period.kind not in ("day", "month")
                or dynamic_period.fact_list not in ("days", "samples", "periods")
                or not isinstance(dynamic_period.title_prefix, str)
                or not dynamic_period.title_prefix.strip()
                or not isinstance(dynamic_period.instruction, str)
                or not dynamic_period.instruction.strip()
                or type(dynamic_period.min_words) is not int
                or not 1 <= dynamic_period.min_words <= 2000
            ):
                raise ValueError("Invalid dynamic report section policy")
        if (
            not specs
            or len(specs) > 100
            or len({section.id for section in specs}) != len(specs)
            or any(
                not isinstance(section.id, str)
                or not section.id.isidentifier()
                or not isinstance(section.title, str)
                or not section.title.strip()
                or not isinstance(section.instruction, str)
                or not section.instruction.strip()
                or type(section.min_words) is not int
                or not 1 <= section.min_words <= 5000
                for section in specs
            )
            or sum(section.min_words for section in specs) < min_total_words
        ):
            raise ValueError("Invalid report sections")
    except (KeyError, TypeError, ValueError) as exc:
        raise AstroReportError("Неполная или противоречивая конфигурация отчёта.") from exc

    # Never allow service source templates to override this unambiguous
    # anti-hallucination policy; the user-authored spec is task data.
    effective_policy = global_policy
    if service_policy.strip():
        effective_policy += "\n\nТребования по услуге (только при наличии расчётных фактов):\n" + service_policy
        effective_policy += "\n\nПРИОРИТЕТ: " + global_policy
    return ReportPlan(
        service_id=service_id,
        version=version,
        system_prompt=effective_policy,
        sections=specs,
        min_total_words=min_total_words,
        dynamic_period=dynamic_period,
    )


def _fact_catalog(facts: dict) -> dict[str, Any]:
    """Expose only curated versioned astronomical evidence, not arbitrary PII."""
    if not isinstance(facts, dict) or "schema_version" not in facts:
        raise AstroReportError("Отсутствуют исходные расчётные факты.")
    # High-level data are versioned separately, so an interpreter cannot
    # invent planets or aspects by reading user-entered free text.
    fields = (
        "schema_version", "chart", "first", "second", "aspects", "indicators",
        "house_overlays",
        "natal_chart", "solar_chart", "samples", "events", "days", "periods",
        "accuracy", "first_accuracy", "second_accuracy", "period",
        "solar_return_at_utc", "solar_return_at_local", "return_location", "engine",
        # Current MIT ephemerides output (natal #550, compatibility #553).
        # Only these deterministic result fields may reach the interpreter;
        # never forward arbitrary client form/profile text.
        "positions", "cross_aspects", "person_a", "person_b",
        "birth_time_known", "not_calculated", "warnings", "aspect_orbs_deg",
        "utc_reference", "local_reference", "timezone",
    )
    selected = {name: facts[name] for name in fields if name in facts}
    if "house_overlays" in selected:
        overlays = selected["house_overlays"]
        allowed = {"first_in_second", "second_in_first", "natal_in_solar", "solar_in_natal"}
        if not isinstance(overlays, dict) or not overlays or set(overlays) - allowed:
            raise AstroReportError("Некорректные наложения домов.")
        for placements in overlays.values():
            if placements is None:
                continue
            if not isinstance(placements, dict) or len(placements) > 100:
                raise AstroReportError("Некорректные наложения домов.")
            for name, house in placements.items():
                if (not isinstance(name, str)
                    or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", name)
                    or type(house) is not int or not 1 <= house <= 12):
                    raise AstroReportError("Некорректные наложения домов.")
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
    # The plan's text, minimums and dynamically expanded section policy
    # are part of the cache identity, even if an admin forgets to bump version.
    policy = json.dumps(
        {"system": plan.system_prompt, "sections": [
            {"id": section.id, "title": section.title, "instruction": section.instruction,
             "min_words": section.min_words} for section in plan.sections
        ], "min_total_words": plan.min_total_words,
         "dynamic_period": (
             {"kind": plan.dynamic_period.kind, "fact_list": plan.dynamic_period.fact_list,
              "title_prefix": plan.dynamic_period.title_prefix,
              "instruction": plan.dynamic_period.instruction,
              "min_words": plan.dynamic_period.min_words}
             if plan.dynamic_period else None
         )},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    canonical = json.dumps(
        {"owner": owner_id, "service": plan.service_id, "plan": plan.version,
         "policy_digest": hashlib.sha256(policy).hexdigest(),
         "facts": _fact_catalog(facts)},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _word_count(value: str) -> int:
    return len(_WORD_RE.findall(value))


def _validate_written_facts(text: str, facts: dict) -> None:
    """Conservative proof gate for numerical zodiac claims and ISO dates.

    This rejects invented *explicit* degrees and ISO dates. It is not a
    substitute for human review of all natural-language interpretations.
    """
    values: list[float] = []

    def visit(item):
        if type(item) in (float, int):
            values.append(float(item))
        elif isinstance(item, dict):
            for value in item.values():
                visit(value)
        elif isinstance(item, list):
            for value in item:
                visit(value)

    visit(facts)
    for match in re.finditer(r"(?<![\w.])(\d{1,3}(?:[.,]\d{1,6})?)\s*°", text):
        claimed = float(match.group(1).replace(",", "."))
        if not any(abs(claimed - actual) <= 0.11 for actual in values):
            raise AstroSectionValidationError("В тексте найден неподтверждённый градус.", reason="unsupported_claim")
    source_json = json.dumps(facts, ensure_ascii=False, allow_nan=False)
    allowed_dates = set(re.findall(r"\b(?:19|20|21)\d{2}-\d{2}-\d{2}\b", source_json))
    for date_str in re.findall(r"\b(?:19|20|21)\d{2}-\d{2}-\d{2}\b", text):
        if date_str not in allowed_dates:
            raise AstroSectionValidationError("В тексте найдена неподтверждённая дата.", reason="unsupported_claim")


def _parse_section(raw: str, spec: SectionSpec, facts: dict | None = None) -> str:
    """Require structured section, not hallucinated external citations."""
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AstroSectionValidationError("Неверный формат текстового раздела.", reason="invalid_format") from exc
    if not isinstance(doc, dict) or doc.get("section_id") != spec.id:
        raise AstroSectionValidationError("Ответ модели относится к другому разделу.", reason="wrong_section")
    text = doc.get("text")
    if not isinstance(text, str) or _word_count(text) < spec.min_words:
        raise AstroSectionValidationError("Раздел недостаточно подробный; не отмечаем готовым.", reason="too_short")
    if len(text) > 180_000 or "\x00" in text:
        raise AstroSectionValidationError("Повреждённый раздел отчёта.", reason="invalid_text")
    if facts is not None:
        _validate_written_facts(text, facts)
    return text.strip()


def _expand_period_sections(plan: ReportPlan, facts: dict) -> tuple[SectionSpec, ...]:
    """No daily/monthly narrative may silently skip a real calendar day/month.

    Reject missing, duplicated, out-of-range and nonchronological facts.
    Never use client-provided date titles or unverified model-generated dates.
    """
    dynamic = plan.dynamic_period
    if dynamic is None:
        return plan.sections
    period = facts.get("period")
    if not isinstance(period, str):
        raise AstroReportError("Нет проверенного периода календаря.")
    if plan.service_id == "solar":
        from bot.services.astro_report_periods import build_solar_report_periods

        calculated = build_solar_report_periods(facts)
        expected_rows = calculated["periods"]
        if facts.get("periods") != expected_rows or calculated["period"] != period:
            raise AstroReportError("Солярные месяцы не соответствуют точному возвращению.")
        rows = facts["periods"]
        return plan.sections + tuple(SectionSpec(
            id=f"solar_month_{i + 1:02d}",
            title=f"{dynamic.title_prefix} {row['start_at_local']} — {row['end_at_local']}",
            instruction=(
                dynamic.instruction + "\nИнтервал рассчитан как календарный месяц от точного "
                "солнцевозвращения. Это условная интерпретационная разбивка, "
                "а не прогноз точных астрономических событий."
            ),
            min_words=dynamic.min_words,
        ) for i, row in enumerate(rows))
    if dynamic.kind == "day":
        match = re.fullmatch(r"([0-9]{4})-(0[1-9]|1[0-2])", period)
        if not match:
            raise AstroReportError("Некорректный месяц исходных фактов.")
        year, month = map(int, match.groups())
        if not 1900 <= year <= 2100:
            raise AstroReportError("Период вне поддерживаемого диапазона.")
        expected = [
            date(year, month, n).isoformat()
            for n in range(1, calendar.monthrange(year, month)[1] + 1)
        ]
    else:
        if not re.fullmatch(r"[0-9]{4}", period) or not 1900 <= int(period) <= 2100:
            raise AstroReportError("Некорректный год исходных фактов.")
        expected = [f"{period}-{month:02d}-01" for month in range(1, 13)]
    rows = facts.get(dynamic.fact_list)
    if not isinstance(rows, list):
        raise AstroReportError("Отсутствуют детальные расчётные факты для каждого периода.")
    actual = [row.get("date") if isinstance(row, dict) else None for row in rows]
    if actual != expected:
        raise AstroReportError("Календарные периоды неполны, дублированы или перепутаны.")
    expanded: list[SectionSpec] = []
    for day in expected:
        suffix = day.replace("-", "")
        expanded.append(SectionSpec(
            id=f"{dynamic.kind}_{suffix}",
            title=f"{dynamic.title_prefix} {day}",
            instruction=dynamic.instruction + "\nТолько расчётные факты для даты " + day +
            ". Если нет персональных данных, не создавай фальшивый прогноз.",
            min_words=dynamic.min_words,
        ))
    return plan.sections + tuple(expanded)


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
    try:
        validation_retries = int(os.getenv("ASTRO_REPORT_SECTION_VALIDATION_RETRIES", "1"))
    except ValueError as exc:
        raise ValueError("Invalid Astro section validation retry configuration") from exc
    if not 0 <= validation_retries <= 2:
        raise ValueError("Invalid Astro section validation retry configuration")
    sections: list[dict] = []
    for section in _expand_period_sections(plan, available):
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
            for attempt in range(validation_retries + 1):
                response = await provider.analyze_text(
                    user_instruction=json.dumps(request, ensure_ascii=False),
                    system_prompt=plan.system_prompt,
                    json_response=True,
                )
                try:
                    candidate = _parse_section(response, section, available)
                    break
                except AstroSectionValidationError as exc:
                    logger.warning(
                        "astro_section_validation_failed service=%s section=%s reason=%s retry=%s",
                        plan.service_id, section.id, exc.reason, attempt,
                    )
                    if attempt >= validation_retries:
                        raise
                    # Preserve all original astronomical facts and the proof gate.
                    # The next response must satisfy the exact same contract.
                    request["validation_feedback"] = {
                        "reason": exc.reason,
                        "minimum_words": section.min_words,
                        "retry_number": attempt + 1,
                    }
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
