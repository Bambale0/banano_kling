"""Offline GeoNames place search: explicit city selection and historical IANA zones.

Never guess a user's birthplace. A place_id selected from search results is
required; the database is an immutable operator-provisioned artifact (CC BY 4.0).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from functools import lru_cache
from pathlib import Path

from bot.services.astro_lunar import AstroInputError, resolve_timezone
from bot.services.astro_natal import _resolve_civil_time

PLACES_SCHEMA = "astro.places.v1"
_TOKENS = re.compile(r"[^\W_]+", re.UNICODE)


def _normalize_country(text: str) -> str:
    return " ".join(_TOKENS.findall(unicodedata.normalize("NFKC", text).casefold()))


@lru_cache(maxsize=1)
def _country_aliases() -> dict[str, str]:
    # Frozen CLDR country-name catalog. No network or optional Babel runtime.
    with Path(__file__).with_name("astro_country_names.json").open(encoding="utf-8") as handle:
        source = json.load(handle)
    return {_normalize_country(alias): code for code, aliases in source.items()
            for alias in aliases if alias}


def _city_and_country(query: str) -> tuple[str, str | None]:
    parts = [part.strip() for part in query.split(",")]
    if len(parts) == 2 and all(parts):
        codes = _country_aliases()
        first = codes.get(_normalize_country(parts[0]))
        last = codes.get(_normalize_country(parts[1]))
        if first and not last:
            return parts[1], first
        if last and not first:
            return parts[0], last
    return query, None



class AstroPlacesUnavailable(RuntimeError):
    """The trusted offline city database cannot be read or is incompatible."""


def _db_path(path: str | Path | None) -> Path:
    configured = str(path or os.environ.get("ASTRO_PLACES_DB_PATH", "")).strip()
    if not configured:
        raise AstroPlacesUnavailable("Справочник городов не настроен.")
    p = Path(configured).expanduser()
    if not p.is_file():
        raise AstroPlacesUnavailable("Справочник городов недоступен.")
    return p


def _connect(path: str | Path | None) -> sqlite3.Connection:
    p = _db_path(path)
    # No implicit creation: an unavailable dataset must never produce a fake place.
    uri = p.resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2)
        conn.execute("PRAGMA query_only=ON")
        version = conn.execute(
            "SELECT value FROM place_meta WHERE key='schema_version'"
        ).fetchone()
        if not version or version[0] != PLACES_SCHEMA:
            conn.close()
            raise AstroPlacesUnavailable("Несовместимая версия справочника городов.")
        return conn
    except (sqlite3.DatabaseError, OSError) as exc:
        raise AstroPlacesUnavailable("Ошибка чтения справочника городов.") from exc


def _row_to_place(row: tuple) -> dict:
    (place_id, name, ascii_name, country_code, admin1, lat, lon, zone, population) = row
    resolve_timezone(zone)  # Reject stale or invalid zoneinfo values.
    return {
        "place_id": place_id,
        "name": name,
        "ascii_name": ascii_name,
        "country_code": country_code,
        "admin1": admin1,
        "latitude": lat,
        "longitude": lon,
        "timezone": zone,
        "population": population,
        "display_name": f"{name}, {country_code}",
        "source": "GeoNames",
    }


def search_places(query: object, *, db_path: str | Path | None = None, limit: int = 10) -> list[dict]:
    """Search city names and aliases without SQL/FTS injection or online requests."""
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 80:
        raise AstroInputError("Введите название города от 2 до 80 символов.")
    if type(limit) is not int or not 1 <= limit <= 20:
        raise AstroInputError("Недопустимый размер списка городов.")
    normalized = unicodedata.normalize("NFKC", query)
    if any(unicodedata.category(ch).startswith("C") for ch in normalized):
        raise AstroInputError("Название города содержит управляющие символы.")
    if any(ch in normalized for ch in ("/", "\\", "=", ";", "<", ">")):
        raise AstroInputError("Введите корректное название города.")
    city_text, country_code = _city_and_country(normalized)
    tokens = _TOKENS.findall(city_text.casefold())
    if not tokens or len(tokens) > 8:
        raise AstroInputError("Введите корректное название города.")
    expression = " AND ".join(f'"{word}"*' for word in tokens)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT p.geoname_id, p.name, p.ascii_name, p.country_code, p.admin1,
                   p.latitude, p.longitude, p.timezone, p.population
            FROM places_fts
            JOIN places AS p ON p.geoname_id = places_fts.rowid
            WHERE places_fts MATCH ? AND (? IS NULL OR p.country_code = ?)
            ORDER BY p.population DESC, p.geoname_id ASC
            LIMIT ?
            """,
            (expression, country_code, country_code, limit),
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise AstroPlacesUnavailable("Не удалось выполнить поиск города.") from exc
    finally:
        conn.close()
    return [_row_to_place(row) for row in rows]


def get_place(place_id: object, *, db_path: str | Path | None = None) -> dict:
    """Resolve a canonical selected GeoNames id, never an unverified free-text city."""
    if type(place_id) is not int or not 1 <= place_id <= 2_147_483_647:
        raise AstroInputError("Выберите город из списка.")
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """SELECT geoname_id, name, ascii_name, country_code, admin1,
                      latitude, longitude, timezone, population
               FROM places WHERE geoname_id=?""",
            (place_id,),
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise AstroPlacesUnavailable("Не удалось открыть запись о городе.") from exc
    finally:
        conn.close()
    if row is None:
        raise AstroInputError("Выбранный город не найден.")
    return _row_to_place(row)


def resolve_birth_place(
    place_id: object,
    *,
    date: object,
    time: object,
    fold: object = None,
    db_path: str | Path | None = None,
) -> dict:
    """Use the selected place's timezone on the BIRTH date, never today's UTC offset."""
    place = get_place(place_id, db_path=db_path)
    instant, known, local = _resolve_civil_time(
        date=date, time=time, timezone_name=place["timezone"], fold=fold,
    )
    return {
        "place": place,
        "birth_time_known": known,
        "utc_reference": instant.isoformat(),
        "local_reference": local,
        "timezone": place["timezone"],
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "source": "GeoNames+IANA-tzdb",
    }
