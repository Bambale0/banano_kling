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
