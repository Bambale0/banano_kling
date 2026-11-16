"""Deterministic lunar calendar backed by MIT-licensed Astronomy Engine.

No astrology readings or predictive health/financial claims are created here.
Times are calculated in UTC and rendered for the requested IANA timezone.
"""

from __future__ import annotations

import calendar
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ASTRO_LUNAR_SCHEMA = "astro.lunar.v1"
PHASE_NAMES = ("Новолуние", "Первая четверть", "Полнолуние", "Последняя четверть")
SIGNS = (
    "Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
    "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы",
)
_PERIOD_RE = re.compile(r"^([0-9]{4})-(0[1-9]|1[0-2])$")
_TZ_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+./-]{0,79}$")


class AstroInputError(ValueError):
    """Invalid user input; never include raw birth data in log messages."""


class AstroEngineUnavailable(RuntimeError):
    """An astronomical fact cannot be calculated by the active engine."""


def parse_period(period: str) -> tuple[int, int]:
    match = _PERIOD_RE.fullmatch(period if isinstance(period, str) else "")
    if not match:
        raise AstroInputError("Некорректный месяц. Ожидается ГГГГ-ММ.")
    year, month = map(int, match.groups())
    if not (1900 <= year <= 2100):
        raise AstroInputError("Месяц вне поддерживаемого диапазона 1900–2100.")
    return year, month


def resolve_timezone(name: str) -> ZoneInfo:
    if not isinstance(name, str) or not _TZ_RE.fullmatch(name):
        raise AstroInputError("Укажите корректную IANA timezone, например Europe/Moscow.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise AstroInputError("Указанная временная зона не найдена.") from exc


def _astro_time(astro, instant: datetime):
    # Astronomy Engine accepts UTC ISO-8601 timestamps ending in Z.
    return astro.Time.Parse(instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))


def _instant(value: object) -> datetime:
    # Astronomy Engine Time.__str__() returns an ISO UTC timestamp.
    raw = str(value)
    if not raw.endswith("Z"):
        raise AstroEngineUnavailable("Эфемерида вернула дату без указания UTC.")
    return datetime.fromisoformat(raw)


def build_lunar_calendar(period: str, timezone_name: str, *, engine=None) -> dict:
    """Compute factual daily lunar state and exact quarter events.

    Lunar-day number uses elapsed *24-hour UTC intervals* after exact new moon,
    and is NOT the traditional moonrise-based lunar day. This convention is
    deliberately explicit and never portrayed as an observational fact.
    """
    year, month = parse_period(period)
    tz = resolve_timezone(timezone_name)
    if engine is None:
        try:
            import astronomy as engine  # type: ignore[no-redef]  # astronomy-engine==2.1.19
        except ImportError as exc:
            raise AstroEngineUnavailable("Астрономический движок недоступен.") from exc

    n_days = calendar.monthrange(year, month)[1]
    first_local = datetime(year, month, 1, tzinfo=tz)
    last_local = first_local + timedelta(days=n_days)
    start_utc = first_local.astimezone(UTC)
    end_utc = last_local.astimezone(UTC)

    # Collect *actual* quarter instants, including days near month boundaries.
    quarter = engine.SearchMoonQuarter(_astro_time(engine, start_utc - timedelta(days=2)))
    events: list[dict] = []
    for _ in range(8):
        instant = _instant(quarter.time)
        if instant > end_utc + timedelta(days=1):
            break
        if start_utc <= instant < end_utc:
            local = instant.astimezone(tz)
            events.append({
                "kind": PHASE_NAMES[int(quarter.quarter)],
                "at_utc": instant.isoformat(),
                "at_local": local.isoformat(),
                "local_date": local.date().isoformat(),
            })
        quarter = engine.NextMoonQuarter(quarter)
    else:
        raise AstroEngineUnavailable("Не удалось ограничить поиск лунных четвертей.")

    # Search for new moons far enough before the first day to determine the
    # 24-hour synodic-day ordinal without extrapolating from phase percentage.
    new_moons: list[datetime] = []
    scan = start_utc - timedelta(days=36)
    for _ in range(5):
        found = engine.SearchMoonPhase(0.0, _astro_time(engine, scan), 40.0)
        if found is None:
            raise AstroEngineUnavailable("Не удалось найти точное новолуние.")
        instant = _instant(found)
        if new_moons and instant <= new_moons[-1]:
            raise AstroEngineUnavailable("Некорректный порядок новолуний.")
        new_moons.append(instant)
        if instant > end_utc:
            break
        scan = instant + timedelta(minutes=5)

    days: list[dict] = []
    for day in range(1, n_days + 1):
        # Local noon is representative; sign/phase may change within a day.
        local_noon = datetime(year, month, day, 12, tzinfo=tz)
        utc_noon = local_noon.astimezone(UTC)
        at = _astro_time(engine, utc_noon)
        moon_lon = float(engine.EclipticGeoMoon(at).lon) % 360.0
        angle = float(engine.MoonPhase(at)) % 360.0
        illumination = float(engine.Illumination(engine.Body.Moon, at).phase_fraction)
        if not (0.0 <= illumination <= 1.0):
            raise AstroEngineUnavailable("Некорректная доля освещённости Луны.")
        previous_new = next((nm for nm in reversed(new_moons) if nm <= utc_noon), None)
        if previous_new is None:
            raise AstroEngineUnavailable("Новолуние до дня не найдено.")
        synodic_day = int((utc_noon - previous_new).total_seconds() // 86400) + 1
        days.append({
            "date": local_noon.date().isoformat(),
            "observed_at_local": local_noon.isoformat(),
            "moon_ecliptic_longitude_deg": round(moon_lon, 4),
            "moon_sign": SIGNS[int(moon_lon // 30)],
            "moon_phase_angle_deg": round(angle, 4),
            "illumination_percent": round(illumination * 100, 2),
            "synodic_day": synodic_day,
            "phase": "растущая" if angle < 180 else "убывающая",
            "events": [
                event["kind"] for event in events
                if event["local_date"] == local_noon.date().isoformat()
            ],
        })

    return {
        "schema_version": ASTRO_LUNAR_SCHEMA,
        "engine": {
            "name": "astronomy-engine",
            "version": "2.1.19",
            "coordinate_system": "tropical geocentric / true ecliptic of date",
        },
        "period": period,
        "timezone": timezone_name,
        "reference_time": "12:00 local time each day",
        "lunar_day_convention": (
            "elapsed complete 24-hour UTC intervals since exact new moon + 1; "
            "not moonrise-based"
        ),
        "not_calculated": ["void_of_course", "planetary_aspects", "eclipses", "haircut_advice"],
        "events": events,
        "days": days,
        "disclaimer": "Астрономические данные и традиционные интерпретации не одно и то же.",
    }
