"""Deterministic natal planet positions and major longitude aspects.

Astronomy Engine is MIT-licensed. This module does NOT calculate Placidus
houses, angles, lunar nodes, asteroids, or interpret astrological claims.
Birth time uncertainty is explicit; it never invents a birth-time-dependent ASC.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.services.astro_lunar import (
    AstroEngineUnavailable,
    AstroInputError,
    resolve_timezone,
)

NATAL_SCHEMA = "astro.natal.facts.v1"
_DATE = re.compile(r"^(0[1-9]|[12][0-9]|3[01])\.(0[1-9]|1[0-2])\.([0-9]{4})$")
_TIME = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
_SIGNS = (
    "Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
    "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы",
)
# The celestial bodies and aspect angles are intrinsic definitions; mutable
# aspect orbs come from data/astro_settings.json, not Python constants.
_BODIES = (
    "Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn",
    "Uranus", "Neptune", "Pluto",
)
_ANGLES = {
    "conjunction": 0, "sextile": 60, "square": 90,
    "trine": 120, "opposition": 180,
}
_SETTINGS_FILE = Path(__file__).resolve().parents[2] / "data" / "astro_settings.json"


def _parse_birth_date(raw: object) -> tuple[int, int, int]:
    match = _DATE.fullmatch(raw if isinstance(raw, str) else "")
    if not match:
        raise AstroInputError("Укажите дату рождения в формате ДД.ММ.ГГГГ.")
    day, month, year = map(int, match.groups())
    if not (1900 <= year <= 2100):
        raise AstroInputError("Год вне поддерживаемого диапазона 1900–2100.")
    try:
        datetime(year, month, day)
    except ValueError as exc:
        raise AstroInputError("Такой календарной даты не существует.") from exc
    return year, month, day


def _parse_birth_time(raw: object) -> tuple[int, int] | None:
    if raw is None or raw == "":
        return None
    match = _TIME.fullmatch(raw if isinstance(raw, str) else "")
    if not match:
        raise AstroInputError("Время рождения должно быть в формате ЧЧ:ММ.")
    return int(match[1]), int(match[2])


def _resolve_civil_time(
    *,
    date: object,
    time: object,
    timezone_name: object,
    fold: object = None,
) -> tuple[datetime, bool, str]:
    year, month, day = _parse_birth_date(date)
    hours_minutes = _parse_birth_time(time)
    zone: ZoneInfo = resolve_timezone(timezone_name)
    # For unknown time use local noon as an explicit approximation, not a
    # fabricated birth time. Omit the Moon and its aspects in that case.
    hour, minute = hours_minutes if hours_minutes is not None else (12, 0)
    naive = datetime(year, month, day, hour, minute)
    options = [naive.replace(tzinfo=zone, fold=value) for value in (0, 1)]
    valid = [
        option.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == naive
        for option in options
    ]
    if not any(valid):
        raise AstroInputError("Это локальное время не существовало (переход часов).")
    ambiguous = all(valid) and options[0].utcoffset() != options[1].utcoffset()
    if ambiguous and fold not in (0, 1):
        raise AstroInputError("Это время повторилось при переводе часов. Выберите fold 0 или 1.")
    if isinstance(fold, bool) or fold not in (None, 0, 1):
        raise AstroInputError("Параметр fold должен быть 0 либо 1.")
    selected = int(fold or 0)
    if not valid[selected]:
        raise AstroInputError("Выбранное смещение недействительно для этой даты.")
    local = options[selected]
    return local.astimezone(UTC), hours_minutes is not None, local.isoformat()


def load_aspect_orbs(settings_file: Path = _SETTINGS_FILE) -> dict[str, float]:
    """Load runtime-changeable orb policy; malformed/missing config fails closed."""
    try:
        config = json.loads(settings_file.read_text(encoding="utf-8"))
        policy = config["aspects"]["orbs_deg"]
        if not isinstance(policy, dict) or set(policy) != set(_ANGLES):
            raise ValueError("incorrect orb names")
        result = {}
        for key in _ANGLES:
            value = policy[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("invalid orb type")
            numeric = float(value)
            if not math.isfinite(numeric) or not 0.0 < numeric <= 15.0:
                raise ValueError("invalid orb range")
            result[key] = numeric
        return result
    except (ValueError, KeyError, OSError, TypeError) as exc:
        raise AstroEngineUnavailable("Настройки астрологических аспектов недоступны.") from exc


def _ecliptic_longitude(engine, name: str, instant: datetime) -> float:
    at = engine.Time.Parse(instant.strftime("%Y-%m-%dT%H:%M:%SZ"))
    if name == "Sun":
        value = engine.SunPosition(at).elon
    elif name == "Moon":
        value = engine.EclipticGeoMoon(at).lon
    else:
        value = engine.Ecliptic(engine.GeoVector(getattr(engine.Body, name), at, True)).elon
    result = float(value) % 360.0
    if not math.isfinite(result):
        raise AstroEngineUnavailable("Недопустимое положение небесного тела.")
    return result


def _angular_delta(later: float, earlier: float) -> float:
    """Signed shortest movement, safe across the 0°/360° zodiac boundary."""
    return (later - earlier + 540.0) % 360.0 - 180.0


def major_aspects(
    positions: dict[str, dict],
    orbs: dict[str, float],
) -> list[dict]:
    names = tuple(positions)
    aspects: list[dict] = []
    for index, first in enumerate(names):
        for second in names[index + 1:]:
            separation = abs(_angular_delta(positions[second]["longitude_deg"], positions[first]["longitude_deg"]))
            candidates = [
                (abs(separation - angle), aspect, angle)
                for aspect, angle in _ANGLES.items()
                if abs(separation - angle) <= orbs[aspect]
            ]
            if not candidates:
                continue
            distance, kind, angle = min(candidates)
            aspects.append({
                "a": first,
                "b": second,
                "kind": kind,
                "angle_deg": angle,
                "orb_deg": round(distance, 3),
                "separation_deg": round(separation, 3),
            })
    return sorted(aspects, key=lambda row: (row["orb_deg"], row["a"], row["b"]))


def build_natal_facts(
    *,
    date: object,
    time: object,
    timezone_name: object,
    fold: object = None,
    engine=None,
    orbs: dict[str, float] | None = None,
) -> dict:
    utc, time_known, local_reference = _resolve_civil_time(
        date=date, time=time, timezone_name=timezone_name, fold=fold
    )
    if engine is None:
        try:
            import astronomy as engine  # type: ignore[no-redef]
        except ImportError as exc:
            raise AstroEngineUnavailable("Астрономический движок недоступен.") from exc
    orb_rules = orbs if orbs is not None else load_aspect_orbs()
    positions: dict[str, dict] = {}
    for name in _BODIES:
        if name == "Moon" and not time_known:
            continue
        try:
            longitude = _ecliptic_longitude(engine, name, utc)
            past = _ecliptic_longitude(engine, name, utc - timedelta(hours=12))
            future = _ecliptic_longitude(engine, name, utc + timedelta(hours=12))
            daily_motion = _angular_delta(future, past)
        except (AttributeError, ValueError, OverflowError) as exc:
            raise AstroEngineUnavailable("Не удалось рассчитать положение планеты.") from exc
        positions[name] = {
            "longitude_deg": round(longitude, 4),
            "sign": _SIGNS[int(longitude // 30)],
            "degree_in_sign": round(longitude % 30, 4),
            "speed_deg_per_day": round(daily_motion, 5),
            "retrograde": daily_motion < 0,
            "approximate": not time_known,
        }

    aspects = major_aspects(positions, orb_rules) if time_known else []
    warnings = ["Дома и ASC/MC не рассчитаны: отдельный расчёт домов не подключён."]
    if not time_known:
        warnings.extend([
            "Время рождения неизвестно: для остальных планет указан расчёт на местный полдень, а не точный момент рождения.",
            "Луна, аспекты и углы не представлены, чтобы не выдавать приближения за точные данные.",
        ])
    return {
        "schema_version": NATAL_SCHEMA,
        "engine": {
            "name": "astronomy-engine",
            "version": "2.1.19",
            "coordinates": "tropical geocentric true ecliptic of date",
            "aberration": True,
        },
        "utc_reference": utc.isoformat(),
        "local_reference": local_reference,
        "timezone": timezone_name,
        "birth_time_known": time_known,
        "positions": positions,
        "aspects": aspects,
        "aspect_orbs_deg": orb_rules,
        "not_calculated": ["placidus_houses", "asc", "mc", "nodes", "lilith", "chiron", "asteroids"],
        "warnings": warnings,
        "disclaimer": "Астрологическая интерпретация не имеет научно установленной прогностической силы.",
    }
