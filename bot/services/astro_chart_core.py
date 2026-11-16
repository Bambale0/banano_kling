"""Strict astronomical natal/synastry facts, no speculative text or billing.

This module is an isolated engine adapter. Expose it only after a secured
admin-only route, pre-provisioned JPL kernel and chart-fixture validation exist.
No network downloads, geocoding, or personal-data persistence are performed.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CHART_SCHEMA = "astro.natal-facts.v1"
SYNASTRY_SCHEMA = "astro.synastry-facts.v1"
BODIES = (
    "Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter",
    "Saturn", "Uranus", "Neptune", "Pluto", "TrueNode", "MeanLilith",
)
_TIME_PATTERN = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
_DATE_PATTERN = re.compile(r"^[0-9]{2}\.[0-9]{2}\.[0-9]{4}$")
_TZ_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_+./-]{0,79}$")


class AstroChartInputError(ValueError):
    """Wrong birth input; never includes raw sensitive fields in error messages."""


class AstroChartUnavailable(RuntimeError):
    """Required source data or chart calculation missing; never fabricate facts."""


@dataclass(frozen=True, slots=True)
class BirthMoment:
    year: int
    month: int
    day: int
    hour: int
    minute: int
    latitude: float
    longitude: float
    timezone: str
    fold: int | None = None


def _coordinate(value: Any, *, maximum: float, label: str) -> float:
    if isinstance(value, bool):
        raise AstroChartInputError(f"Некорректное значение: {label}.")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AstroChartInputError(f"Некорректное значение: {label}.") from exc
    if not math.isfinite(parsed) or not -maximum <= parsed <= maximum:
        raise AstroChartInputError(f"Координаты {label} вне допустимого диапазона.")
    return parsed


def parse_birth_profile(payload: Any) -> BirthMoment:
    if not isinstance(payload, dict):
        raise AstroChartInputError("Нужен объект с данными рождения.")

    date_text = payload.get("date")
    time_text = payload.get("time")
    if not isinstance(date_text, str) or not _DATE_PATTERN.fullmatch(date_text):
        raise AstroChartInputError("Укажите дату рождения в формате ДД.ММ.ГГГГ.")
    if not isinstance(time_text, str) or not _TIME_PATTERN.fullmatch(time_text):
        raise AstroChartInputError(
            "Для домов Плацидуса требуется точное время рождения ЧЧ:ММ."
        )
    try:
        birth = datetime.strptime(date_text + " " + time_text, "%d.%m.%Y %H:%M")
    except ValueError as exc:
        raise AstroChartInputError("Дата или время рождения не существует.") from exc
    if not 1900 <= birth.year <= 2100:
        raise AstroChartInputError("Дата рождения вне диапазона 1900–2100.")

    tz_name = payload.get("timezone")
    if not isinstance(tz_name, str) or not _TZ_PATTERN.fullmatch(tz_name):
        raise AstroChartInputError("Нужен IANA-часовой пояс места рождения.")
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise AstroChartInputError("Часовой пояс не найден.") from exc

    fold = payload.get("fold")
    if fold is not None and (type(fold) is not int or fold not in (0, 1)):
        raise AstroChartInputError("Выбор повторяющегося часа должен быть 0 или 1.")
    latitude = _coordinate(payload.get("latitude"), maximum=90, label="широты")
    longitude = _coordinate(payload.get("longitude"), maximum=180, label="долготы")
    return BirthMoment(
        birth.year, birth.month, birth.day, birth.hour, birth.minute,
        latitude, longitude, tz_name, fold,
    )


def _kernel_path() -> str:
    raw = os.getenv("ASTRO_DE440_PATH", "").strip()
    if not raw:
        raise AstroChartUnavailable("JPL ephemeris path not configured")
    path = Path(raw).expanduser()
    if not path.is_file() or path.suffix.lower() != ".bsp":
        raise AstroChartUnavailable("JPL ephemeris asset not present")
    if path.stat().st_size == 0:
        raise AstroChartUnavailable("JPL ephemeris asset is empty")
    return str(path.resolve())


def _load_engine():
    try:
        import openephem
    except ImportError as exc:
        raise AstroChartUnavailable("MIT chart calculation engine missing") from exc
    if str(getattr(openephem, "__version__", "")) != "0.5.0":
        raise AstroChartUnavailable("Unsupported chart calculation engine version")
    return openephem


def _assemble_birth(profile: BirthMoment, *, engine, kernel: str) -> dict:
    try:
        moment = engine.resolve(
            date=(profile.year, profile.month, profile.day),
            time=(profile.hour, profile.minute),
            lat=profile.latitude,
            lon=profile.longitude,
            tz=profile.timezone,
            **({"fold": profile.fold} if profile.fold is not None else {}),
        )
    except Exception as exc:
        raise AstroChartInputError("Не удалось однозначно определить время рождения.") from exc

    warnings = [str(item).lower() for item in getattr(moment, "warnings", ())]
    if any("nonexistent" in warn or "gap" in warn for warn in warnings):
        raise AstroChartInputError("Это время не существовало из-за перевода часов.")
    if profile.fold is None and any("ambiguous" in warn or "fold" in warn for warn in warnings):
        raise AstroChartInputError("Время попало на повторяющийся час. Уточните переход часов.")

    try:
        chart = engine.assemble(
            moment,
            house_system="Placidus",
            bodies=list(BODIES),
            de440=kernel,
        )
    except Exception as exc:
        raise AstroChartUnavailable("Chart computation failed") from exc
    if not isinstance(chart, dict):
        raise AstroChartUnavailable("Chart engine returned invalid type")
    bodies = chart.get("bodies")
    if not isinstance(bodies, dict) or any(body not in bodies for body in BODIES):
        raise AstroChartUnavailable("Chart missing mandatory planetary positions")
    for body in BODIES:
        position = bodies[body]
        if not isinstance(position, dict):
            raise AstroChartUnavailable("Invalid planetary position")
        lon = position.get("lon")
        if not isinstance(lon, (int, float)) or not math.isfinite(lon) or not 0 <= lon < 360:
            raise AstroChartUnavailable("Invalid planetary longitude")

    cusps = chart.get("cusps")
    angles = chart.get("angles")
    if not isinstance(cusps, list) or len(cusps) != 12 or not isinstance(angles, dict):
        # Placidus can be undefined at high latitudes; don't silently change systems.
        raise AstroChartUnavailable("Placidus houses not available for this birth moment")
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in cusps):
        raise AstroChartUnavailable("Invalid Placidus house positions")
    for essential in ("asc", "mc"):
        if essential not in angles or not math.isfinite(float(angles[essential])):
            raise AstroChartUnavailable("Invalid chart angle")

    aspects = chart.get("aspects")
    if not isinstance(aspects, list):
        raise AstroChartUnavailable("Natal aspects missing")
    return chart


def build_natal_facts(payload: Any, *, engine=None, kernel=None) -> dict:
    """Return actual astronomical birth-chart facts, never invented claims."""
    profile = parse_birth_profile(payload)
    ephem = engine or _load_engine()
    asset = kernel or _kernel_path()
    chart = _assemble_birth(profile, engine=ephem, kernel=asset)
    return {
        "schema_version": CHART_SCHEMA,
        "calculation": "tropical-geocentric-placidus",
        "engine": {"name": "openephem", "version": "0.5.0", "kernel": "JPL-DE440"},
        "chart": chart,
        "interpretation": None,
        "disclaimer": "Астрологические трактовки символичны и не являются научными прогнозами.",
    }


def build_synastry_facts(left: Any, right: Any, *, engine=None, kernel=None) -> dict:
    """Two complete natal charts plus mathematically exact inter-chart aspects."""
    ephem = engine or _load_engine()
    asset = kernel or _kernel_path()
    left_chart = build_natal_facts(left, engine=ephem, kernel=asset)
    right_chart = build_natal_facts(right, engine=ephem, kernel=asset)
    try:
        aspects = ephem.cross_aspects(left_chart["chart"], right_chart["chart"])
    except Exception as exc:
        raise AstroChartUnavailable("Synastry aspects computation failed") from exc
    if not isinstance(aspects, list):
        raise AstroChartUnavailable("Synastry aspects missing")
    return {
        "schema_version": SYNASTRY_SCHEMA,
        "engine": {"name": "openephem", "version": "0.5.0", "kernel": "JPL-DE440"},
        "first": left_chart["chart"],
        "second": right_chart["chart"],
        "aspects": aspects,
        "interpretation": None,
        "disclaimer": "Совместимость по астрологическим схемам — символическая интерпретация.",
    }


def _year(value: Any) -> int:
    if type(value) is not int or not 1900 <= value <= 2100:
        raise AstroChartInputError("Год должен быть числом в пределах 1900–2100.")
    return value


def _location(value: Any) -> tuple[float, float, str]:
    if not isinstance(value, dict):
        raise AstroChartInputError("Нужно указать координаты и часовой пояс места.")
    lat = _coordinate(value.get("latitude"), maximum=90, label="широты")
    lon = _coordinate(value.get("longitude"), maximum=180, label="долготы")
    zone = value.get("timezone")
    if not isinstance(zone, str) or not _TZ_PATTERN.fullmatch(zone):
        raise AstroChartInputError("Нужен IANA-часовой пояс места.")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise AstroChartInputError("Часовой пояс не найден.") from exc
    return lat, lon, zone


def build_karma_indicators(birth: Any, *, engine=None, kernel=None) -> dict:
    """Actual nodes/Saturn/Pluto placements; karmic *meaning* is symbolic."""
    facts = build_natal_facts(birth, engine=engine, kernel=kernel)
    chart = facts["chart"]
    names = {"TrueNode", "MeanLilith", "Saturn", "Pluto"}
    indicators = {name: chart["bodies"][name] for name in names}
    aspects = [
        a for a in chart["aspects"]
        if isinstance(a, dict) and (a.get("a") in names or a.get("b") in names)
    ]
    return {
        "schema_version": "astro.karma-indicators.v1",
        "chart": chart,
        "indicators": indicators,
        "aspects": aspects,
        "interpretation": None,
        "disclaimer": "Кармические значения астрологических символов не подтверждены наукой.",
    }


def _planet_engine(engine, kernel):
    try:
        return engine.planets_skyfield.SkyfieldPlanetEngine(kernel)
    except Exception as exc:
        raise AstroChartUnavailable("JPL planetary ephemeris unavailable") from exc


def _sample_transits(
    profile: BirthMoment,
    first_date: datetime,
    *,
    count: int,
    step: str,
    natal_chart: dict,
    engine,
    kernel: str,
    planetary_engine=None,
) -> list[dict]:
    """Sample *instantaneous* transits, not pretend to list exact crossings.

    Construct the JPL engine once per report; 31 local-noon samples then
    reuse the same ephemeris, avoiding one 114MB load per day.
    """
    from datetime import UTC, timedelta

    planet_engine = planetary_engine or _planet_engine(engine, kernel)
    samples: list[dict] = []
    tz = ZoneInfo(profile.timezone)
    for index in range(count):
        if step == "day":
            local = first_date + timedelta(days=index)
        elif step == "month":
            month_idx = first_date.month - 1 + index
            year = first_date.year + month_idx // 12
            month = month_idx % 12 + 1
            local = first_date.replace(year=year, month=month)
        else:
            raise AstroChartInputError("Некорректный шаг прогноза.")
        local = local.replace(tzinfo=tz)
        utc = local.astimezone(UTC)
        jd = engine.returns.jd_from_datetime(utc)
        positions: dict[str, dict] = {}
        for name in BODIES:
            try:
                lon = float(planet_engine.ecliptic_longitude(jd, name))
            except Exception as exc:
                raise AstroChartUnavailable("Transit body calculation failed") from exc
            if not math.isfinite(lon):
                raise AstroChartUnavailable("Nonfinite transit longitude")
            positions[name] = {"lon": lon % 360}
        transit_chart = {"bodies": positions}
        try:
            aspects = engine.cross_aspects(transit_chart, natal_chart)
        except Exception as exc:
            raise AstroChartUnavailable("Transit aspect calculation failed") from exc
        if not isinstance(aspects, list):
            raise AstroChartUnavailable("Transit aspect engine returned invalid data")
        samples.append({
            "date": local.date().isoformat(),
            "at_local": local.isoformat(),
            "at_utc": utc.isoformat(),
            "bodies": positions,
            "aspects_to_natal": aspects,
        })
    return samples


def build_transit_snapshots(
    birth: Any,
    *,
    year: int,
    month: int | None = None,
    engine=None,
    kernel=None,
    planetary_engine=None,
) -> dict:
    """Factual annual monthly samples or daily month samples, never a prediction."""
    import calendar

    target_year = _year(year)
    if month is not None and (type(month) is not int or not 1 <= month <= 12):
        raise AstroChartInputError("Месяц должен быть в пределах 1–12.")
    profile = parse_birth_profile(birth)
    ephem = engine or _load_engine()
    asset = kernel or _kernel_path()
    chart = _assemble_birth(profile, engine=ephem, kernel=asset)
    first = datetime(target_year, month or 1, 1, 12)
    count = calendar.monthrange(target_year, month)[1] if month else 12
    step = "day" if month else "month"
    samples = _sample_transits(
        profile, first, count=count, step=step, natal_chart=chart,
        engine=ephem, kernel=asset, planetary_engine=planetary_engine,
    )
    return {
        "schema_version": "astro.transit-snapshots.v1",
        "scope": "month" if month else "year",
        "period": f"{target_year:04d}-{month:02d}" if month else str(target_year),
        "time_convention": "12:00 local time; aspects may change between samples",
        "samples": samples,
        "natal_chart": chart,
        "interpretation": None,
        "disclaimer": "Точки транзитов рассчитаны на отдельные даты, не являются полным расписанием точных аспектов.",
    }


def build_solar_return_facts(
    birth: Any,
    *,
    target_year: int,
    return_location: Any,
    engine=None,
    kernel=None,
    planetary_engine=None,
) -> dict:
    """Compute the exact natal-Sun longitude return, relocated chart separately."""
    target_year = _year(target_year)
    profile = parse_birth_profile(birth)
    lat, lon, zone = _location(return_location)
    ephem = engine or _load_engine()
    asset = kernel or _kernel_path()
    natal = _assemble_birth(profile, engine=ephem, kernel=asset)
    solar_lon = natal["bodies"]["Sun"]["lon"]
    planet_engine = planetary_engine or _planet_engine(ephem, asset)
    try:
        # Feb 29 birthdays have no Feb 29 in nonleap years: use Feb 28 to seed,
        # then find the *astronomically exact* Sun-longitude crossing.
        import calendar

        seed_day = min(profile.day, calendar.monthrange(target_year, profile.month)[1])
        near = ephem.returns.jd(target_year, profile.month, seed_day, 12)
        found_jd = ephem.returns.solar_return(solar_lon, near, engine=planet_engine)
        instant_utc = ephem.returns.datetime_from_jd(found_jd)
        if instant_utc.tzinfo is None:
            raise AstroChartUnavailable("Solar return instant missing timezone")
        local = instant_utc.astimezone(ZoneInfo(zone))
        resolved = ephem.resolve(
            date=(local.year, local.month, local.day),
            time=(local.hour, local.minute, local.second),
            lat=lat, lon=lon, tz=zone,
            fold=local.fold,
        )
        solar_chart = ephem.assemble(
            resolved, house_system="Placidus", bodies=list(BODIES), de440=asset,
        )
    except AstroChartUnavailable:
        raise
    except Exception as exc:
        raise AstroChartUnavailable("Solar return computation failed") from exc

    if not isinstance(solar_chart, dict) or any(
        name not in solar_chart.get("bodies", {}) for name in BODIES
    ):
        raise AstroChartUnavailable("Solar return chart incomplete")
    if not isinstance(solar_chart.get("cusps"), list) or len(solar_chart["cusps"]) != 12:
        raise AstroChartUnavailable("Solar return Placidus houses unavailable")
    return {
        "schema_version": "astro.solar-facts.v1",
        "target_year": target_year,
        "solar_return_at_utc": instant_utc.isoformat(),
        "solar_return_at_local": local.isoformat(),
        "return_location": {"latitude": lat, "longitude": lon, "timezone": zone},
        "natal_sun_longitude_deg": solar_lon,
        "solar_chart": solar_chart,
        "interpretation": None,
        "disclaimer": "Соляр — астрономическая карта точного возвращения солнечной долготы; её трактовки символичны.",
    }
