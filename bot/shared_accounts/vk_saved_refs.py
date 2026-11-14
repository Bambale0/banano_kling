"""Private saved-reference metadata for a verified native VK actor.

The authoritative image bytes remain in the existing upload/S3 service.
No Telegram user row, copied image, new wallet or provider request is created.
"""
from __future__ import annotations

import hashlib
import os
import re
from uuid import uuid4

from bot import db as db_backend

from .vk_image_refs import verified_image_urls

_REF_ID = re.compile(r"[0-9a-f]{32}\Z")


def _actor(value: object) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError("Invalid verified VK actor")
    return value


def _limit() -> int:
    try:
        limit = int(os.getenv("VK_MINIAPP_SAVED_REF_MAX_ITEMS", "100"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("VK saved-reference quota is unavailable") from exc
    if not 1 <= limit <= 1000:
        raise RuntimeError("VK saved-reference quota is unavailable")
    return limit


def _name(value: object) -> str:
    if type(value) is not str:
        raise ValueError("Invalid saved reference label")
    clean = value.strip()
    if not clean or len(clean) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in clean):
        raise ValueError("Invalid saved reference label")
    return clean


def _url(value: object) -> str:
    if type(value) is not str or not 1 <= len(value) <= 2048:
        raise ValueError("Invalid saved reference URL")
    return value


def _row(row) -> dict:
    return {
        "reference_id": str(row[0]),
        "url": str(row[1]),
        "name": str(row[2]),
        "created_at": str(row[3]),
    }


async def _owner_lock(db, actor: int) -> None:
    # SQLite BEGIN IMMEDIATE serializes claims; PostgreSQL uses a transaction
    # scoped advisory lock so the count+insert quota is atomic per VK actor.
    if db_backend.is_postgres():
        key = int.from_bytes(
            hashlib.sha256(b"shared-vk-saved-ref\0" + str(actor).encode()).digest()[:8],
            "big", signed=True,
        )
        await db.execute("SELECT pg_advisory_xact_lock(?)", (key,))
    else:
        await db.execute("BEGIN IMMEDIATE")


async def list_vk_references(vk_user_id: int) -> list[dict]:
    owner = _actor(vk_user_id)
    async with db_backend.connect() as db:
        cursor = await db.execute(
            """SELECT reference_id, file_url, display_name, created_at
               FROM shared_vk_saved_references WHERE vk_user_id = ?
               ORDER BY created_at DESC, reference_id DESC LIMIT ?""",
            (owner, _limit()),
        )
        rows = await cursor.fetchall()
    return [_row(row) for row in rows]


async def save_vk_reference(vk_user_id: int, file_url: str, name: str) -> dict:
    owner = _actor(vk_user_id)
    url = _url(file_url)
    label = _name(name)
    # This calls the existing S3-aware owner+object existence verification.
    # A URL, even one that points to public media, is NOT an authorization.
    if verified_image_urls(owner, [url]) != [url]:
        raise ValueError("VK saved reference is not owned by this account")
    digest = hashlib.sha256(url.encode()).hexdigest()
    async with db_backend.connect() as db:
        await _owner_lock(db, owner)
        try:
            cursor = await db.execute(
                """SELECT reference_id, file_url, display_name, created_at
                   FROM shared_vk_saved_references
                   WHERE vk_user_id = ? AND url_hash = ?""",
                (owner, digest),
            )
            existing = await cursor.fetchone()
            if existing is not None:
                await db.commit()
                return _row(existing)
            cursor = await db.execute(
                "SELECT COUNT(*) FROM shared_vk_saved_references WHERE vk_user_id = ?",
                (owner,),
            )
            count = await cursor.fetchone()
            if int(count[0]) >= _limit():
                raise ValueError("VK saved reference limit reached")
            ref_id = uuid4().hex
            await db.execute(
                """INSERT INTO shared_vk_saved_references
                   (reference_id, vk_user_id, url_hash, file_url, display_name)
                   VALUES (?, ?, ?, ?, ?)""",
                (ref_id, owner, digest, url, label),
            )
            cursor = await db.execute(
                """SELECT reference_id, file_url, display_name, created_at
                   FROM shared_vk_saved_references
                   WHERE vk_user_id = ? AND reference_id = ?""",
                (owner, ref_id),
            )
            saved = await cursor.fetchone()
            await db.commit()
            if saved is None:
                raise RuntimeError("Saved reference was not committed")
            return _row(saved)
        except Exception:
            await db.rollback()
            raise


async def forget_vk_reference(vk_user_id: int, reference_id: str) -> bool:
    owner = _actor(vk_user_id)
    if type(reference_id) is not str or _REF_ID.fullmatch(reference_id) is None:
        raise ValueError("Invalid VK reference ID")
    # Forget metadata only. Deleting shared media might break an in-flight
    # provider task that still references the same S3 upload.
    async with db_backend.connect() as db:
        cursor = await db.execute(
            """DELETE FROM shared_vk_saved_references
               WHERE vk_user_id = ? AND reference_id = ?""",
            (owner, reference_id),
        )
        await db.commit()
        return cursor.rowcount > 0
