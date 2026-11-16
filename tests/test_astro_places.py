"""GeoNames Astro places: selected IDs, historical tz, ambiguity and SQL defenses."""

from __future__ import annotations

import sqlite3
import zipfile

import pytest

from bot.services.astro_lunar import AstroInputError
from bot.services.astro_places import (
    AstroPlacesUnavailable,
    get_place,
    resolve_birth_place,
    search_places,
)
from scripts.astro_build_places import build


def _geonames_row(geoid, name, ascii_name, lat, lon, country, population, tz, alt=""):
    fields = [
        str(geoid), name, ascii_name, alt, str(lat), str(lon),
        "P", "PPL", country, "", "01", "", "", "",
        str(population), "", "", tz, "2026-01-01",
    ]
    assert len(fields) == 19
    return "\t".join(fields)


@pytest.fixture
def city_db(tmp_path):
    source = tmp_path / "cities1000.zip"
    lines = [
        _geonames_row(524901, "Москва", "Moscow", 55.75, 37.62, "RU", 12000000, "Europe/Moscow", "Moskva,Москоу"),
        _geonames_row(6167865, "Moscow", "Moscow", 46.73, -117.00, "US", 26000, "America/Los_Angeles"),
        _geonames_row(5128581, "New York City", "New York City", 40.714, -74.006, "US", 8300000, "America/New_York", "NYC"),
        _geonames_row(588409, "Tallinn", "Tallinn", 59.437, 24.753, "EE", 430000, "Europe/Tallinn", "Таллин,Reval"),
    ]
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("cities1000.txt", "\n".join(lines) + "\n")
    db = tmp_path / "cities.sqlite3"
    receipt = build(source, db)
    assert receipt["rows"] == len(lines)
    assert len(receipt["source_sha256"]) == 64
    assert len(receipt["output_sha256"]) == 64
    return db


def test_russian_and_latin_names_and_alias_search(city_db):
    ru = search_places("Москва", db_path=city_db)
    assert len(ru) == 1
    assert ru[0]["place_id"] == 524901
    assert ru[0]["latitude"] == 55.75
    assert ru[0]["source"] == "GeoNames"
    assert any(p["place_id"] == 524901 for p in search_places("Moscow", db_path=city_db))
    assert any(p["place_id"] == 588409 for p in search_places("Таллин", db_path=city_db))
    assert get_place(524901, db_path=city_db)["timezone"] == "Europe/Moscow"



@pytest.mark.parametrize("query,expected_country,expected_place", [
    ("Россия, Москва", "RU", 524901),
    ("Москва, Россия", "RU", 524901),
    ("Russian Federation, Moscow", "RU", 524901),
    ("РФ, Москва", "RU", 524901),
    ("Moscow, US", "US", 6167865),
    ("United States, Moscow", "US", 6167865),
    ("Эстония, Таллин", "EE", 588409),
])
def test_country_names_are_resolved_from_offline_country_catalog(
    query, expected_country, expected_place, city_db,
):
    results = search_places(query, db_path=city_db)
    assert results
    assert all(r["country_code"] == expected_country for r in results)
    assert results[0]["place_id"] == expected_place


def test_unsupported_country_does_not_return_random_city(city_db):
    assert search_places("Wakanda, Moscow", db_path=city_db) == []


def test_ambiguous_moscow_requires_explicit_place_id(city_db):
    hits = search_places("Moscow", db_path=city_db)
    assert {p["country_code"] for p in hits} == {"RU", "US"}
    assert hits[0]["place_id"] == 524901
    us = get_place(6167865, db_path=city_db)
    assert us["timezone"] == "America/Los_Angeles"


def test_historical_offset_and_dst_overlap(city_db):
    ny = 5128581
    winter = resolve_birth_place(
        ny, date="15.01.2024", time="12:00", db_path=city_db
    )
    summer = resolve_birth_place(
        ny, date="15.07.2024", time="12:00", db_path=city_db
    )
    assert winter["utc_reference"].endswith("17:00:00+00:00")
    assert summer["utc_reference"].endswith("16:00:00+00:00")
    assert winter["place"]["latitude"] == 40.714
    with pytest.raises(AstroInputError, match="fold"):
        resolve_birth_place(ny, date="03.11.2024", time="01:30", db_path=city_db)
    a = resolve_birth_place(ny, date="03.11.2024", time="01:30", fold=0, db_path=city_db)
    b = resolve_birth_place(ny, date="03.11.2024", time="01:30", fold=1, db_path=city_db)
    assert a["utc_reference"] != b["utc_reference"]
    with pytest.raises(AstroInputError, match="не существовало"):
        resolve_birth_place(ny, date="10.03.2024", time="02:30", db_path=city_db)


@pytest.mark.parametrize("bad", ["", "A", "' OR 1=1 --", "NYC\x00", "../etc", 1234, None])
def test_invalid_search_does_not_leak_data(bad, city_db):
    with pytest.raises(AstroInputError):
        search_places(bad, db_path=city_db)


@pytest.mark.parametrize("bad", [0, -1, "524901", None, True, 2**50])
def test_invalid_place_id_is_rejected(bad, city_db):
    with pytest.raises(AstroInputError):
        get_place(bad, db_path=city_db)


def test_unknown_city_and_missing_db_fail_closed(city_db, tmp_path):
    with pytest.raises(AstroInputError, match="не найден"):
        get_place(999999, db_path=city_db)
    with pytest.raises(AstroPlacesUnavailable):
        search_places("Москва", db_path=tmp_path / "does-not-exist.sqlite3")


def test_reject_wrong_schema_without_reading_place_data(tmp_path):
    fake = tmp_path / "bad.sqlite3"
    with sqlite3.connect(fake) as conn:
        conn.execute("CREATE TABLE place_meta (key TEXT, value TEXT)")
        conn.execute("INSERT INTO place_meta VALUES ('schema_version','astro.places.v0')")
    with pytest.raises(AstroPlacesUnavailable, match="Несовместимая"):
        search_places("Moscow", db_path=fake)


def test_importer_never_overwrites_existing_db(city_db, tmp_path):
    source = tmp_path / "cities.zip"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("cities1000.txt", "")
    before = city_db.read_bytes()
    with pytest.raises(FileExistsError):
        build(source, city_db)
    assert city_db.read_bytes() == before


def test_db_metadata_and_local_read_only_open(city_db):
    with sqlite3.connect(f"file:{city_db}?mode=ro", uri=True) as conn:
        metadata = dict(conn.execute("SELECT key, value FROM place_meta"))
    assert metadata["schema_version"] == "astro.places.v1"
    assert metadata["source"] == "GeoNames cities1000, CC BY 4.0"
