"""Isolated actual-source upload clock regression; no application/DB adapter imports."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import hashlib
import json
import logging
import re
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
STORAGE_PATH = ROOT / "bot/services/wan3_prime_storage.py"
RETENTION_PATH = ROOT / "bot/services/wan3_prime_retention.py"


class ValidationError(ValueError):
    def __init__(self, message, *, status=400):
        super().__init__(message)
        self.status = status


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowcount = cursor.rowcount

    async def fetchone(self):
        return self.cursor.fetchone()

    async def fetchall(self):
        return self.cursor.fetchall()


class Database:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.calls = []
        # Deliberately wrong defaults detect dependence on a database-local clock.
        self.connection.executescript("""
          CREATE TABLE wan3_prime_upload_sessions (
            upload_id TEXT PRIMARY KEY, user_id INTEGER, telegram_id INTEGER,
            kind TEXT, filename TEXT, content_type TEXT, declared_size INTEGER,
            total_chunks INTEGER, received_chunks INTEGER DEFAULT 0,
            chunk_hashes TEXT DEFAULT '{}', completed_result TEXT,
            status TEXT DEFAULT 'open', expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT '1900-01-01 01:00:00',
            updated_at TIMESTAMP DEFAULT '1900-01-01 01:00:00');
          CREATE TABLE wan3_prime_media (id INTEGER PRIMARY KEY, public_url TEXT,
            local_path TEXT, created_at TIMESTAMP);
          CREATE TABLE wan3_prime_cleanup_cursor (id INTEGER, last_media_id INTEGER);
          INSERT INTO wan3_prime_cleanup_cursor VALUES (1, 0);
        """)

    @contextlib.asynccontextmanager
    async def connect(self, *_):
        try:
            yield self
        finally:
            self.connection.rollback()

    async def execute(self, sql, args=()):
        self.calls.append((sql, args))
        return Cursor(self.connection.execute(sql, args))

    async def commit(self):
        self.connection.commit()

    async def rollback(self):
        self.connection.rollback()


class SessionClockTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Database()
        self.addCleanup(self.db.connection.close)
        self.actor = types.SimpleNamespace(user_id=7, telegram_id=17)
        self.now = datetime(2026, 7, 15, 12, 0, 0, 123456, tzinfo=UTC)
        test = self

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return test.now.astimezone(tz) if tz else test.now.replace(tzinfo=None)

        async def lock_storage(db):
            await db.execute("BEGIN IMMEDIATE")

        async def capacity(*_, **__):
            return None

        def child(root, name):
            return Path(root) / name

        def write_chunk(path, data, digest):
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        def assemble(directory, path, hashes, total, size):
            data = b"".join((directory / f"{index:06d}.part").read_bytes() for index in range(total))
            self.assertEqual(len(data), size)
            path.write_bytes(data)

        self.policy = types.ModuleType("bot.services.wan3_prime_storage_policy")
        self.policy.ACTIVE_UPLOAD_STATES = "('open', 'assembling', 'importing', 'rejected')"
        self.policy.assert_capacity = capacity
        self.policy.lock_storage = lock_storage
        self.policy.positive_setting = lambda _, default: default
        files = types.ModuleType("bot.services.wan3_prime_files")
        files.write_chunk = write_chunk
        files.assemble_chunks = assemble
        files.Wan3PrimeDocumentError = type("DocumentError", (Exception,), {})
        self.modules = patch.dict(sys.modules, {
            "bot.services.wan3_prime_storage_policy": self.policy,
            "bot.services.wan3_prime_files": files,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        backend = types.SimpleNamespace(connect=self.db.connect, Row=sqlite3.Row, is_postgres=lambda: False)
        self.namespace = dict(  # noqa: C408 - explicit injected symbol namespace
            asyncio=asyncio, contextlib=contextlib, hashlib=hashlib, json=json,
            datetime=FixedDateTime, UTC=UTC, timedelta=timedelta, re=re, uuid=uuid,
            Path=Path, shutil=shutil, Any=object, Wan3PrimeValidationError=ValidationError,
            CHUNK_SIZE=7*1024*1024, MAX_UNFINISHED_SESSIONS=5,
            CHUNK_ROOT=Path(self.directory.name)/"chunks", UPLOAD_ROOT=Path(self.directory.name)/"media",
            db_backend=backend, _sqlite_path=lambda: ":memory:",
            _kind_limit=lambda _: 20*1024*1024, _allowed_ext=lambda _: {".jpg"},
            _safe_basename=lambda name: name, canonical_child_path=child,
        )
        tree = ast.parse(STORAGE_PATH.read_text())
        methods = {"init_upload", "cancel_upload", "save_chunk", "complete_upload", "discard_import"}
        selected = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in {"_now", "_expires"}:
                selected.append(node)
            elif isinstance(node, ast.ClassDef) and node.name == "Wan3PrimeStorage":
                node.body = [method for method in node.body if isinstance(method, ast.AsyncFunctionDef) and method.name in methods]
                selected.append(node)
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(STORAGE_PATH), "exec"), self.namespace)  # noqa: S102 - isolated actual source without app imports
        self.storage = self.namespace["Wan3PrimeStorage"]()
        self.storage.init_schema = capacity
        storage_module = types.ModuleType("bot.services.wan3_prime_storage")
        for key in ("_now", "CHUNK_ROOT", "UPLOAD_ROOT"):
            setattr(storage_module, key, self.namespace[key])
        self.storage_module_patch = patch.dict(sys.modules, {"bot.services.wan3_prime_storage": storage_module})
        self.storage_module_patch.start()
        self.addCleanup(self.storage_module_patch.stop)
        retention_namespace = dict(  # noqa: C408 - explicit injected symbol namespace
            asyncio=asyncio, shutil=shutil, datetime=datetime, UTC=UTC, timedelta=timedelta,
            Path=Path, db_backend=backend, database=types.SimpleNamespace(DATABASE_PATH=":memory:"),
            canonical_child_path=child, lock_storage=lock_storage,
            positive_setting=self.policy.positive_setting, logger=logging.getLogger(__name__),
        )
        retention_tree = ast.parse(RETENTION_PATH.read_text())
        selected_retention = [node for node in retention_tree.body if isinstance(node, ast.AsyncFunctionDef)]
        exec(compile(ast.Module(body=selected_retention, type_ignores=[]), str(RETENTION_PATH), "exec"), retention_namespace)  # noqa: S102 - isolated actual source without app imports
        self.cleanup = retention_namespace["cleanup_expired"]

    async def init(self, **kwargs):
        return await self.storage.init_upload(self.actor, kind="image", filename="test.jpg", size=3,
                                              content_type="image/jpeg", **kwargs)

    def row(self, upload_id):
        return self.db.connection.execute("SELECT * FROM wan3_prime_upload_sessions WHERE upload_id=?", (upload_id,)).fetchone()

    async def test_new_session_one_hour_and_first_chunk_across_dst_dates(self):
        dates = [(1, 15, 12), (7, 15, 12), (3, 29, 0), (3, 29, 1), (10, 25, 0), (10, 25, 1)]
        for month, day, hour in dates:
            with self.subTest(date=(month, day, hour)):
                self.now = datetime(2026, month, day, hour, 30, tzinfo=UTC)
                result = await self.init()
                row = self.row(result["upload_id"])
                self.assertEqual(row["created_at"], self.namespace["_now"]())
                self.assertEqual(row["updated_at"], row["created_at"])
                self.assertEqual(datetime.fromisoformat(row["expires_at"])-datetime.fromisoformat(row["created_at"]), timedelta(hours=1))
                await self.storage.save_chunk(self.actor, upload_id=result["upload_id"], index=0, total=1, chunk=b"abc")
                self.assertEqual(self.row(result["upload_id"])["received_chunks"], 1)
                await self.storage.cancel_upload(self.actor, upload_id=result["upload_id"])

    async def test_existing_utc_expiry_remains_valid_without_rewriting_history(self):
        result = await self.init()
        self.db.connection.execute("UPDATE wan3_prime_upload_sessions SET created_at=?, updated_at=?", ("2026-07-15 13:00:00",)*2)
        self.db.connection.commit()
        self.now += timedelta(minutes=59)
        await self.storage.save_chunk(self.actor, upload_id=result["upload_id"], index=0, total=1, chunk=b"abc")
        row = self.row(result["upload_id"])
        self.assertEqual(row["created_at"], "2026-07-15 13:00:00")
        self.assertEqual(row["updated_at"], self.namespace["_now"]())

    async def test_expiry_boundary_rejects_chunk_complete_and_init_replay(self):
        upload_id = uuid.uuid4().hex
        await self.init(upload_id=upload_id)
        await self.storage.save_chunk(self.actor, upload_id=upload_id, index=0, total=1, chunk=b"abc")
        self.now += timedelta(hours=1)
        for expected, operation in [
            (404, lambda: self.storage.save_chunk(self.actor, upload_id=upload_id, index=0, total=1, chunk=b"abc")),
            (410, lambda: self.storage.complete_upload(self.actor, upload_id=upload_id)),
            (409, lambda: self.init(upload_id=upload_id)),
        ]:
            with self.subTest(status=expected):
                with self.assertRaises(ValidationError) as caught:
                    await operation()
                self.assertEqual(caught.exception.status, expected)

    async def test_owner_idempotency_and_hash_guards_survive(self):
        upload_id = uuid.uuid4().hex
        first = await self.init(upload_id=upload_id)
        self.now += timedelta(minutes=1)
        self.assertEqual(await self.init(upload_id=upload_id), first)
        await self.storage.save_chunk(self.actor, upload_id=upload_id, index=0, total=1, chunk=b"abc")
        await self.storage.save_chunk(self.actor, upload_id=upload_id, index=0, total=1, chunk=b"abc")
        self.assertEqual(self.row(upload_id)["received_chunks"], 1)
        for actor, content, status in [(types.SimpleNamespace(user_id=8), b"abc", 404), (self.actor, b"def", 409)]:
            with self.assertRaises(ValidationError) as caught:
                await self.storage.save_chunk(actor, upload_id=upload_id, index=0, total=1, chunk=content)
            self.assertEqual(caught.exception.status, status)

    async def test_assembly_lease_and_failure_recovery_share_utc_clock(self):
        result = await self.init()
        upload_id = result["upload_id"]
        await self.storage.save_chunk(self.actor, upload_id=upload_id, index=0, total=1, chunk=b"abc")
        self.db.connection.execute("UPDATE wan3_prime_upload_sessions SET status='assembling'")
        self.db.connection.commit()
        with self.assertRaises(ValidationError) as caught:
            await self.storage.complete_upload(self.actor, upload_id=upload_id)
        self.assertEqual(caught.exception.status, 409)
        self.now += timedelta(minutes=6)

        async def fail(*args, **kwargs):
            self.assertEqual(kwargs["assembly_stamp"], self.namespace["_now"]())
            raise RuntimeError("simulated local persistence failure")

        self.storage.save_owned_file = fail
        with self.assertRaises(RuntimeError):
            await self.storage.complete_upload(self.actor, upload_id=upload_id)
        self.assertEqual(self.row(upload_id)["status"], "open")
        self.assertEqual(self.row(upload_id)["updated_at"], self.namespace["_now"]())

    async def test_cancel_and_failed_import_use_utc_clock(self):
        result = await self.init()
        self.now += timedelta(minutes=1)
        await self.storage.cancel_upload(self.actor, upload_id=result["upload_id"])
        self.assertEqual(self.row(result["upload_id"])["updated_at"], self.namespace["_now"]())
        result = await self.init(importing=True)
        self.now += timedelta(minutes=1)
        await self.storage.discard_import(self.actor, result["upload_id"])
        row = self.row(result["upload_id"])
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["updated_at"], self.namespace["_now"]())

    async def test_gc_keeps_live_session_and_removes_only_expired_stale_bytes(self):
        result = await self.init()
        upload_id = result["upload_id"]
        await self.storage.save_chunk(self.actor, upload_id=upload_id, index=0, total=1, chunk=b"abc")
        self.now += timedelta(minutes=59)
        self.assertEqual((await self.cleanup())["removed_sessions"], 0)
        self.assertTrue((self.namespace["CHUNK_ROOT"]/upload_id).exists())
        self.now += timedelta(minutes=1)
        self.assertEqual((await self.cleanup())["removed_sessions"], 1)
        self.assertEqual(self.row(upload_id)["status"], "expired")
        self.assertEqual(self.row(upload_id)["updated_at"], self.namespace["_now"]())
        self.assertFalse((self.namespace["CHUNK_ROOT"]/upload_id).exists())

    async def test_gc_preserves_recent_assembly_lease_and_cancel_grace(self):
        await self.init()
        self.now += timedelta(minutes=59)
        self.db.connection.execute("UPDATE wan3_prime_upload_sessions SET status='assembling', updated_at=?", (self.namespace["_now"](),))
        self.db.connection.commit()
        self.now += timedelta(minutes=1)
        self.assertEqual((await self.cleanup())["removed_sessions"], 0)
        self.now += timedelta(minutes=4)
        self.assertEqual((await self.cleanup())["removed_sessions"], 1)
        other = await self.init()
        await self.storage.cancel_upload(self.actor, upload_id=other["upload_id"])
        self.assertEqual((await self.cleanup())["removed_sessions"], 0)
        self.now += timedelta(minutes=5)
        self.assertEqual((await self.cleanup())["removed_sessions"], 1)

    async def test_session_runtime_sql_has_no_database_local_clock(self):
        for path in (STORAGE_PATH, RETENTION_PATH):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    sql = node.value.lower()
                    if ("update wan3_prime_upload_sessions" in sql or "select" in sql and "expires_at" in sql):
                        self.assertNotIn("current_timestamp", sql)


if __name__ == "__main__":
    unittest.main()
