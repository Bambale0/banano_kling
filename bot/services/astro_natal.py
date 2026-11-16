"""Astro natal astronomical facts (no divination, no houses without verified chart).

Uses the same MIT Astronomy Engine already installed for the lunar calendar.
Never manufacture birth time, houses, lunar position, or planet coordinates.
"""
from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from bot.services.astro_lunar import (
    SIGNS,
    AstroEngineUnavailable,
    AstroInputError,
    _astro_time,
    resolve_timezone,
)

NATAL_SCHEMA = "astro.natal.positions.v1"
_BODIES = ("Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter",
           "Saturn", "Uranus", "Neptune", "Pluto")
_MAJOR_ASPECTS = {"conjunction": (0, 8), "sextile": (60, 4),
                  "square": (90, 6), "trine": (120, 6),
                  "opposition": (180, 8)}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def resolve_birth_instant(date: str, birth_time: str | None, timezone_name: str,
                          *, fold: int | None = None) -> tuple[datetime, bool]:
    """Return UTC moment; reject DST gaps and ambiguous civil times.

    For an unknown birth time use local noon only as a *labelled*
    approximation for slow planets and Sun; exclude the Moon and houses.
    """
    if not isinstance(date, str) or not _DATE_RE.fullmatch(date):
        raise AstroInputError("Дата рождения должна быть в формате ГГГГ-ММ-ДД.")
    tz = resolve_timezone(timezone_name)
    try:
        civil_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise AstroInputError("Невозможная календарная дата рождения.") from exc
    if not 1900 <= civil_date.year <= 2100:
        raise AstroInputError("Год рождения должен быть в диапазоне 1900–2100.")
    if birth_time is None or birth_time == "":
        hour, minute, time_known = 12, 0, False
    elif isinstance(birth_time, str) and (match := _TIME_RE.fullmatch(birth_time)):
        hour, minute, time_known = int(match[1]), int(match[2]), True
    else:
        raise AstroInputError("Время рождения должно быть в формате ЧЧ:ММ.")
    local = civil_date.replace(hour=hour, minute=minute)
    a = local.replace(tzinfo=tz, fold=0)
    z = local.replace(tzinfo=tz, fold=1)
    if a.utcoffset() != z.utcoffset() and fold is None:
        raise AstroInputError("Время попадает на перевод часов; выберите первый или второй интервал.")
    if fold is not None and (type(fold) is not int or fold not in (0, 1)):
        raise AstroInputError("Интервал перевода часов должен быть 0 или 1.")
    chosen = local.replace(tzinfo=tz, fold=fold or 0)
    moment = chosen.astimezone(UTC)
    if moment.astimezone(tz).replace(tzinfo=None) != local:
        raise AstroInputError("Указанное местное время не существовало из-за перевода часов.")
    if moment > datetime.now(UTC):
        raise AstroInputError("Дата рождения не может быть в будущем.")
    return moment, time_known


def _ecliptic_longitude(engine, body, instant: datetime) -> float:
    at = _astro_time(engine, instant)
    vector = engine.GeoVector(body, at, True)
    lon = float(engine.Ecliptic(vector).lon)
    if not math.isfinite(lon):
        raise AstroEngineUnavailable("Эфемериды вернули некорректную координату.")
    return lon % 360


def _angular_delta(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def major_aspects(positions: list[dict]) -> list[dict]:
    """Match real computed ecliptic longitudes, not zodiac sign heuristics."""
    result = []
    for index, left in enumerate(positions):
        for right in positions[index+1:]:
            sep = abs(_angular_delta(left["longitude_deg"], right["longitude_deg"]))
            for name, (angle, max_orb) in _MAJOR_ASPECTS.items():
                orb = abs(sep - angle)
                if orb <= max_orb:
                    result.append({
                        "a": left["name"], "b": right["name"],
                        "kind": name, "angle_deg": angle, "orb_deg": round(orb, 3),
                    })
                    break
    return sorted(result, key=lambda item: (item["orb_deg"], item["a"], item["b"]))


def build_natal_positions(date: str, birth_time: str | None, timezone_name: str,
                          *, fold: int | None = None, engine=None) -> dict:
    moment, time_known = resolve_birth_instant(date, birth_time, timezone_name, fold=fold)
    if engine is None:
        try:
            import astronomy as engine
        except ImportError as exc:
            raise AstroEngineUnavailable("Астрономический движок недоступен.") from exc
    # A date without a birth time cannot support a precise lunar zodiac sign.
    bodies = _BODIES if time_known else tuple(x for x in _BODIES if x != "Moon")
    positions: list[dict] = []
    for name in bodies:
        try:
            body = getattr(engine.Body, name)
            lon = _ecliptic_longitude(engine, body, moment)
            future = _ecliptic_longitude(engine, body, moment + timedelta(hours=12))
            past = _ecliptic_longitude(engine, body, moment - timedelta(hours=12))
            speed = _angular_delta(future, past)
        except AstroEngineUnavailable:
            raise
        except Exception as exc:
            raise AstroEngineUnavailable("Не удалось вычислить координаты планет.") from exc
        positions.append({
            "name": name, "longitude_deg": round(lon, 4),
            "sign": SIGNS[int(lon // 30)],
            "degree_in_sign": round(lon % 30, 4),
            "retrograde": speed < 0,
            "speed_deg_per_day": round(speed, 5),
            "accuracy": "exact_instant" if time_known else "approximate_local_noon",
        })
    return {
        "schema_version": NATAL_SCHEMA,
        "engine": {"name": "astronomy-engine", "version": "2.1.19",
                   "coordinate_system": "tropical geocentric true ecliptic of date"},
        "birth_time_known": time_known,
        "birth_date": date, "timezone": timezone_name,
        "computed_for_utc": moment.isoformat(),
        "time_convention": "exact local civil time" if time_known else "12:00 local approximation",
        "positions": positions,
        "aspects": major_aspects(positions),
        "houses": None,
        "angles": None,
        "not_calculated": ["Placidus houses", "Ascendant/MC", "nodes", "Chiron",
                           "Lilith", "asteroids", "interpretation"],
        "warnings": (
            ["Время рождения неизвестно: Луна и угловые/домовые данные исключены; "
             "другие положения приблизительны."] if not time_known else []
        ) + ["Дома и углы не вычислялись: географические координаты не подтверждены."],
        "disclaimer": "Астрологическая символика не является научным прогнозом.",
    }
