#!/usr/bin/env python3
"""Build a versioned read-only Astro city search DB from an offline GeoNames ZIP.

GeoNames license CC BY 4.0; usage attribution: https://www.geonames.org/
No network calls. Never commit the imported data or replace live DB in place.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

VERSION = "astro.places.v1"
MAX_SOURCE_BYTES = 200_000_000
_TZ_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_+./-]{0,79}$")


def build(source_zip: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("Output already exists; create a new versioned DB path.")
    if not source_zip.is_file():
        raise FileNotFoundError(source_zip)
    with source_zip.open("rb") as file_handle:
        src_hash = hashlib.file_digest(file_handle, "sha256").hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".astro_places_", suffix=".sqlite3", dir=output.parent)
    os.close(fd)
    tmp = Path(name)
    count = 0
    try:
        with zipfile.ZipFile(source_zip) as archive:
            names = [entry for entry in archive.infolist() if entry.filename == "cities1000.txt"]
            if len(names) != 1 or not 0 < names[0].file_size <= MAX_SOURCE_BYTES:
                raise ValueError("Expected a bounded GeoNames cities1000.txt ZIP member.")
            with sqlite3.connect(tmp) as conn:
                conn.executescript("""
                PRAGMA journal_mode=OFF;
                PRAGMA synchronous=OFF;
                CREATE TABLE place_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE places (
                    geoname_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    ascii_name TEXT NOT NULL,
                    alt_names TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    country_code TEXT NOT NULL,
                    admin1 TEXT NOT NULL,
                    population INTEGER NOT NULL,
                    timezone TEXT NOT NULL,
                    modified TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE places_fts USING fts5(
                    name, ascii_name, alt_names,
                    content='places', content_rowid='geoname_id',
                    tokenize='unicode61 remove_diacritics 2'
                );
                """)
                with archive.open(names[0]) as raw:
                    stream = io.TextIOWrapper(raw, encoding="utf-8", errors="strict")
                    batch = []
                    for line in stream:
                        fields = line.rstrip("\r\n").split("\t")
                        if len(fields) != 19:
                            raise ValueError("GeoNames source row has wrong column count.")
                        (geoid, pname, ascii_name, aliases, lat, lon, _fclass, _fcode,
                         country, _cc2, admin1, _admin2, _admin3, _admin4,
                         population, _elevation, _dem, tz, modified) = fields
                        if not _TZ_NAME.fullmatch(tz):
                            raise ValueError("Invalid GeoNames IANA timezone")
                        row = (int(geoid), pname, ascii_name, aliases, float(lat),
                               float(lon), country, admin1, int(population), tz, modified)
                        if not (row[0] > 0 and -90 <= row[4] <= 90 and -180 <= row[5] <= 180
                                and len(country) == 2 and pname):
                            raise ValueError("Invalid GeoNames place coordinates or ID")
                        batch.append(row)
                        count += 1
                        if len(batch) >= 1000:
                            conn.executemany(
                                "INSERT INTO places VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch
                            )
                            batch = []
                    if batch:
                        conn.executemany("INSERT INTO places VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)
                conn.execute("INSERT INTO places_fts(places_fts) VALUES ('rebuild')")
                for key, value in (
                    ("schema_version", VERSION),
                    ("source", "GeoNames cities1000, CC BY 4.0"),
                    ("source_sha256", src_hash),
                    ("created_utc", datetime.now(UTC).isoformat()),
                    ("rows", str(count)),
                ):
                    conn.execute("INSERT INTO place_meta VALUES (?,?)", (key, value))
                conn.commit()
        if count == 0:
            raise ValueError("Empty GeoNames input")
        os.replace(tmp, output)
        output.chmod(0o444)
    finally:
        if tmp.exists():
            tmp.unlink()
    with output.open("rb") as file_handle:
        output_hash = hashlib.file_digest(file_handle, "sha256").hexdigest()
    return {"rows": count, "source_sha256": src_hash, "output_sha256": output_hash}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.source_zip, args.output))


if __name__ == "__main__":
    main()
