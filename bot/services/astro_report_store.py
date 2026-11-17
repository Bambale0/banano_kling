"""Owner-scoped resumable Astro report checkpoints for SQLite and PostgreSQL.

Every SQL statement uses the project's bot.db adapter. This store is NOT a
distributed generation lease: callers must serialize duplicate active jobs
before invoking the paid LLM. Permission and consent must be enforced by API.
"""

from __future__ import annotations

import asyncio
import os
import re
import time

from bot import db

_HEX_64 = re.compile(r"^[a-f0-9]{64}$")
_SECTION = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,60}$")


def _retention_seconds() -> int:
    try:
        days = int(os.environ.get("ASTRO_REPORT_RETENTION_DAYS", "90"))
    except ValueError:
        days = 90
    return max(1, min(365, days)) * 86400


def _validate_key(owner_id: int, fingerprint: str, section_id: str) -> None:
    if (
        type(owner_id) is not int or owner_id <= 0
        or not isinstance(fingerprint, str) or not _HEX_64.fullmatch(fingerprint)
        or not isinstance(section_id, str) or not _SECTION.fullmatch(section_id)
    ):
        raise ValueError("Invalid Astro checkpoint owner, fingerprint or section id")


async def _create_astro_table(conn, sql: str) -> None:
    """PostgreSQL adapter skips generic SQLite CREATE; use native DDL."""
    if db.is_postgres():
        await conn.execute_native_ddl(sql)
    else:
        await conn.execute(sql)


class AstroReportSqlStore:
    """Durable INSERT-ON-CONFLICT idempotency scoped by owner, report and section."""

    def __init__(self, *, db_path: str | None = None):
        self._db_path = db_path
        self._initialized = False
        self._init_lock = asyncio.Lock()

    def _connect(self):
        return db.connect(self._db_path)

    async def initialize(self):
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            async with self._connect() as conn:
                await _create_astro_table(conn,
                    """
                    CREATE TABLE IF NOT EXISTS astro_report_sections (
                        owner_id BIGINT NOT NULL,
                        fingerprint TEXT NOT NULL,
                        section_id TEXT NOT NULL,
                        text_content TEXT NOT NULL,
                        created_at BIGINT NOT NULL,
                        expires_at BIGINT NOT NULL,
                        PRIMARY KEY (owner_id, fingerprint, section_id)
                    )
                    """
                )
                await _create_astro_table(conn,
                    "CREATE INDEX IF NOT EXISTS idx_astro_sections_expiry "
                    "ON astro_report_sections (expires_at)"
                )
                await conn.commit()
            self._initialized = True

    async def read(self, *, owner_id: int, fingerprint: str, section_id: str) -> str | None:
        _validate_key(owner_id, fingerprint, section_id)
        await self.initialize()
        now = int(time.time())
        async with self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT text_content FROM astro_report_sections
                WHERE owner_id = ? AND fingerprint = ? AND section_id = ?
                  AND expires_at > ?
                """,
                (owner_id, fingerprint, section_id, now),
            )
            row = await cursor.fetchone()
            return str(row[0]) if row else None

    async def save_if_absent(
        self, *, owner_id: int, fingerprint: str, section_id: str, text: str
    ) -> str:
        _validate_key(owner_id, fingerprint, section_id)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Cannot persist an empty Astro report section")
        await self.initialize()
        now = int(time.time())
        expires_at = now + _retention_seconds()
        async with self._connect() as conn:
            # Another worker may have inserted this section. The first
            # committed result wins; expired entries can be replaced.
            await conn.execute(
                """
                INSERT INTO astro_report_sections (
                    owner_id, fingerprint, section_id, text_content, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (owner_id, fingerprint, section_id)
                DO UPDATE SET
                    text_content = excluded.text_content,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                WHERE astro_report_sections.expires_at <= excluded.created_at
                """,
                (owner_id, fingerprint, section_id, text, now, expires_at),
            )
            cursor = await conn.execute(
                """
                SELECT text_content FROM astro_report_sections
                WHERE owner_id = ? AND fingerprint = ? AND section_id = ?
                  AND expires_at > ?
                """,
                (owner_id, fingerprint, section_id, now),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("Astro checkpoint insert did not persist")
            await conn.commit()
            return str(row[0])

    async def delete_owner(self, *, owner_id: int) -> int:
        """Erase all of an owner's generated interpretations on privacy request."""
        if type(owner_id) is not int or owner_id <= 0:
            raise ValueError("Invalid owner")
        await self.initialize()
        async with self._connect() as conn:
            cursor = await conn.execute(
                "DELETE FROM astro_report_sections WHERE owner_id = ?", (owner_id,)
            )
            await conn.commit()
            return max(0, int(cursor.rowcount or 0))

    async def purge_expired(self) -> int:
        """Bounded periodic maintenance; no full birth details are stored here."""
        await self.initialize()
        async with self._connect() as conn:
            cursor = await conn.execute(
                "DELETE FROM astro_report_sections WHERE expires_at <= ?",
                (int(time.time()),),
            )
            await conn.commit()
            return max(0, int(cursor.rowcount or 0))
