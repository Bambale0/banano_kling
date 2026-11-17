"""Twelve *civil-time* solar report intervals anchored at exact Sun return.

This is a transparent symbolic monthly grouping, NOT 12 exact transits or
predictions of events. We refuse ambiguous/nonexistent clock boundaries.
"""
from __future__ import annotations

import calendar
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bot.services.astro_report_pipeline import AstroReportError


def _month_from_return(anchor: datetime, offset: int, zone: ZoneInfo) -> datetime:
    total_months = anchor.year * 12 + anchor.month - 1 + offset
    year, zero_month = divmod(total_months, 12)
    month = zero_month + 1
    if not 1900 <= year <= 2101:
        raise AstroReportError("Период соляра вне диапазона вычислений.")
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    naive = datetime(year, month, day, anchor.hour, anchor.minute, anchor.second,
                     anchor.microsecond)
    local = naive.replace(tzinfo=zone, fold=0)
    if local.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive:
        raise AstroReportError("Месячная граница попала в несуществующее время DST.")
    return local


def build_solar_report_periods(facts: dict) -> dict:
    if not isinstance(facts, dict):
        raise AstroReportError("Отсутствует рассчитанный соляр.")
    raw = facts.get("solar_return_at_local")
    location = facts.get("return_location")
    if not isinstance(raw, str) or not isinstance(location, dict):
        raise AstroReportError("Отсутствуют расчётные факты точного времени и города соляра.")
    tz_name = location.get("timezone")
    if not isinstance(tz_name, str):
        raise AstroReportError("Нет IANA timezone места соляра.")
    try:
        tz = ZoneInfo(tz_name)
        instant = datetime.fromisoformat(raw)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise AstroReportError("Некорректное точное время возвращения.") from exc
    if instant.tzinfo is None:
        raise AstroReportError("Солярное возвращение без UTC смещения.")
    anchor = instant.astimezone(tz)
    if anchor.isoformat() != raw:
        raise AstroReportError("Часовой пояс соляра не соответствует моменту возвращения.")
    boundaries = [_month_from_return(anchor, i, tz) for i in range(13)]
    if not all(boundaries[i] < boundaries[i + 1] for i in range(12)):
        raise AstroReportError("Неверный порядок месяцев соляра.")
    result = dict(facts)
    result["period"] = str(anchor.year)
    result["periods"] = [{
        "date": boundaries[i].date().isoformat(),
        "start_at_local": boundaries[i].isoformat(),
        "end_at_local": boundaries[i + 1].isoformat(),
        "convention": "twelve_civil_months_anchored_to_exact_solar_return",
    } for i in range(12)]
    return result
