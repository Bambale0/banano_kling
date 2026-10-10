"""Exact upload methods with synthetic SQLite/auth; never import the app DB."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import sys
import threading
import types
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiosqlite
import pytest
from aiohttp import web

ROOT = Path(__file__).parents[1]


class ValidationError(Exception):
    def __init__(self, message, *, status=400):
        super().__init__(message)
        self.status = status


class LifecycleError(RuntimeError):
    def __init__(self, message, *, status=400, code="wan3_error"):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class FileInfo:
    size_bytes: int
    extension: str = ".txt"
    pages: int = 1


def selected_source(path, names, namespace):
    """Compile unchanged selected definitions, excluding application imports."""
    source = ROOT / path
    tree = ast.parse(source.read_text())
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert {node.name for node in nodes} == set(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)  # noqa: S102 - trusted exact methods, synthetic dependencies
    return namespace


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    database_path = str(tmp_path / "synthetic.sqlite")
    actor = types.SimpleNamespace(user_id=1, telegram_id=101)
    foreign = types.SimpleNamespace(user_id=2, telegram_id=202)

    @asynccontextmanager
    async def connect(_path):
        async with aiosqlite.connect(database_path, timeout=10) as connection:
            yield connection

    db = types.ModuleType("bot.db")
    db.connect, db.Row, db.is_postgres = connect, sqlite3.Row, lambda: False
    database = types.ModuleType("bot.database")
    database.DATABASE_PATH = database_path
    bot = types.ModuleType("bot")
    bot.__path__ = []
    bot.db, bot.database = db, database
    services = types.ModuleType("bot.services")
    services.__path__ = []
    for name, module in (("bot", bot), ("bot.db", db), ("bot.database", database), ("bot.services", services)):
        monkeypatch.setitem(sys.modules, name, module)

    def module(name, values):
        result = types.ModuleType(name)
        result.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, result)
        return result

    def child_path(root, name):
        result = (root / name).resolve()
        assert root.resolve() in result.parents
        return result

    media = module("bot.services.wan3_prime_media", {
        "Wan3PrimeValidationError": ValidationError,
        "canonical_child_path": child_path,
        "_check_dimensions": lambda *args, **kwargs: None,
        "_check_duration": lambda *args, **kwargs: None,
    })
    for path in ("wan3_prime_schema", "wan3_prime_storage_policy", "wan3_prime_files", "wan3_prime_retention"):
        loaded = module("bot.services." + path, {})
        exec(compile((ROOT / f"bot/services/{path}.py").read_text(), path, "exec"), loaded.__dict__)  # noqa: S102 - allowed feature files, synthetic bot/db

    @asynccontextmanager
    async def probe_slot(_user_id):
        yield

    module("bot.services.wan3_prime_probe_cache", {"probe_slot": probe_slot})

    class Probe:
        def __init__(self, **kwargs):
            pass

        async def probe_file(self, path, *, kind):
            return FileInfo(Path(path).stat().st_size)

    storage_module = module("bot.services.wan3_prime_storage", {})
    namespace = storage_module.__dict__
    namespace.update({
        "asyncio": asyncio, "contextlib": contextlib, "hashlib": hashlib,
        "json": json, "mimetypes": mimetypes, "os": os, "re": re,
        "shutil": shutil, "uuid": uuid, "asdict": asdict,
        "UTC": UTC, "datetime": datetime, "timedelta": timedelta,
        "Path": Path, "Any": Any, "db_backend": db, "database": database, "urlparse": urlparse,
        "Wan3PrimeValidationError": ValidationError, "canonical_child_path": child_path,
        "CHUNK_SIZE": 7 * 1024 * 1024, "MAX_UNFINISHED_SESSIONS": 5,
        "CHUNK_ROOT": tmp_path / "chunks", "UPLOAD_ROOT": tmp_path / "references",
        "IMAGE_EXTENSIONS": {".jpg"}, "VIDEO_EXTENSIONS": {".mp4"},
        "AUDIO_EXTENSIONS": {".mp3"}, "DOCUMENT_EXTENSIONS": {".txt"},
        "ActualWan3PrimeProbe": Probe,
        "_public_url_for_path": lambda path: "/uploads/" + Path(path).name,
    })
    selected_source("bot/services/wan3_prime_storage.py", ["_now", "_expires", "_safe_basename", "_kind_limit", "_allowed_ext", "_sqlite_path", "Wan3PrimeStorage"], namespace)
    storage = namespace["Wan3PrimeStorage"]()
    return types.SimpleNamespace(storage=storage, actor=actor, foreign=foreign,
        db_path=database_path, module=storage_module, media=media,
        policy=sys.modules["bot.services.wan3_prime_storage_policy"],
        files=sys.modules["bot.services.wan3_prime_files"],
        retention=sys.modules["bot.services.wan3_prime_retention"], module_factory=module)


async def initialized(harness):
    await harness.storage.init_schema()

    async def no_schema():
        pass

    harness.storage.init_schema = no_schema
    async with aiosqlite.connect(harness.db_path) as db:
        await db.execute("CREATE TABLE generation_tasks (request_data TEXT)")
        await db.commit()
    return harness.storage


async def init(harness, **kwargs):
    return await harness.storage.init_upload(harness.actor, kind="file", filename="Файл.txt", size=4, **kwargs)


async def row(harness, upload_id):
    async with aiosqlite.connect(harness.db_path) as db:
        db.row_factory = sqlite3.Row
        return await (await db.execute("SELECT * FROM wan3_prime_upload_sessions WHERE upload_id = ?", (upload_id,))).fetchone()


@pytest.mark.asyncio
async def test_cancel_retry_releases_five_session_limit_without_dropping_byte_reservations(harness):
    storage = await initialized(harness)
    for _ in range(6):
        upload = await init(harness)
        result = await storage.cancel_upload(harness.actor, upload_id=upload["upload_id"])
        assert result == {"ok": True, "status": "cancelled"}
    for _ in range(5):
        await init(harness)
    with pytest.raises(ValidationError, match="Too many unfinished") as error:
        await init(harness)
    assert error.value.status == 429
    async with aiosqlite.connect(harness.db_path) as db:
        reserved = await (await db.execute(f"SELECT SUM(declared_size) FROM wan3_prime_upload_sessions WHERE status IN {harness.policy.RESERVED_UPLOAD_STATES}")).fetchone()
    assert reserved[0] == 44


@pytest.mark.asyncio
async def test_cancel_is_owner_scoped_idempotent_and_terminal_safe(harness):
    storage = await initialized(harness)
    upload_id = (await init(harness))["upload_id"]
    assert await storage.cancel_upload(harness.foreign, upload_id=upload_id) == {"ok": True, "status": "not_found"}
    assert await storage.cancel_upload(harness.actor, upload_id="a" * 32) == {"ok": True, "status": "not_found"}
    assert (await row(harness, upload_id))["status"] == "open"
    for status in ("open", "assembling", "importing", "rejected", "cancelled", "failed", "expired"):
        async with aiosqlite.connect(harness.db_path) as db:
            await db.execute("UPDATE wan3_prime_upload_sessions SET status = ?, expires_at = '2000-01-01' WHERE upload_id = ?", (status, upload_id))
            await db.commit()
        assert await storage.cancel_upload(harness.actor, upload_id=upload_id) == {"ok": True, "status": "cancelled"}
        assert (await row(harness, upload_id))["status"] in {"cancelled", "failed", "expired"}


@pytest.mark.asyncio
async def test_cancelled_upload_cannot_accept_chunks_or_complete(harness):
    storage = await initialized(harness)
    upload_id = (await init(harness))["upload_id"]
    await storage.save_chunk(harness.actor, upload_id=upload_id, index=0, total=1, chunk=b"test")
    await storage.cancel_upload(harness.actor, upload_id=upload_id)
    with pytest.raises(ValidationError):
        await storage.save_chunk(harness.actor, upload_id=upload_id, index=0, total=1, chunk=b"test")
    with pytest.raises(ValidationError):
        await storage.complete_upload(harness.actor, upload_id=upload_id)
    assert (await row(harness, upload_id))["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancelled_bytes_are_retained_until_existing_cleanup_removes_temporary_files(harness):
    storage = await initialized(harness)
    upload_id = (await init(harness))["upload_id"]
    await storage.save_chunk(harness.actor, upload_id=upload_id, index=0, total=1, chunk=b"test")
    await storage.cancel_upload(harness.actor, upload_id=upload_id)
    directory = harness.module.CHUNK_ROOT / upload_id
    assert directory.exists()
    assert (await harness.retention.cleanup_expired())["removed_sessions"] == 0
    async with aiosqlite.connect(harness.db_path) as db:
        await db.execute("UPDATE wan3_prime_upload_sessions SET updated_at = '2000-01-01' WHERE upload_id = ?", (upload_id,))
        await db.commit()
    assert (await harness.retention.cleanup_expired())["removed_sessions"] == 1
    assert not directory.exists()
    assert (await row(harness, upload_id))["status"] == "expired"


@pytest.mark.asyncio
async def test_failed_temporary_cleanup_retains_cancelled_bytes_and_retries(harness, monkeypatch):
    storage = await initialized(harness)
    upload_id = (await init(harness))["upload_id"]
    await storage.save_chunk(harness.actor, upload_id=upload_id, index=0, total=1, chunk=b"test")
    await storage.cancel_upload(harness.actor, upload_id=upload_id)
    async with aiosqlite.connect(harness.db_path) as db:
        await db.execute("UPDATE wan3_prime_upload_sessions SET updated_at = '2000-01-01' WHERE upload_id = ?", (upload_id,))
        await db.commit()
    original = harness.retention.shutil.rmtree

    def fail(_path):
        raise OSError("synthetic filesystem unavailable")

    monkeypatch.setattr(harness.retention.shutil, "rmtree", fail)
    assert (await harness.retention.cleanup_expired())["removed_sessions"] == 0
    assert (await row(harness, upload_id))["status"] == "cancelled"
    monkeypatch.setattr(harness.retention.shutil, "rmtree", original)
    assert (await harness.retention.cleanup_expired())["removed_sessions"] == 1


@pytest.mark.asyncio
async def test_cancelled_bytes_still_enforce_storage_quota(harness, monkeypatch):
    storage = await initialized(harness)
    monkeypatch.setenv("WAN3_UPLOAD_USER_QUOTA_BYTES", "4")
    upload_id = (await init(harness))["upload_id"]
    await storage.cancel_upload(harness.actor, upload_id=upload_id)
    with pytest.raises(ValidationError, match="storage quota exceeded"):
        await init(harness)


@pytest.mark.asyncio
async def test_completed_media_and_generation_history_survive_cancellation(harness):
    storage = await initialized(harness)
    upload_id = (await init(harness))["upload_id"]
    await storage.save_chunk(harness.actor, upload_id=upload_id, index=0, total=1, chunk=b"test")
    saved = await storage.complete_upload(harness.actor, upload_id=upload_id)
    async with aiosqlite.connect(harness.db_path) as db:
        await db.execute("INSERT INTO generation_tasks VALUES (?)", (json.dumps({"url": saved["url"]}),))
        await db.commit()
    assert await storage.cancel_upload(harness.actor, upload_id=upload_id) == {"ok": True, "status": "completed"}
    assert await storage.complete_upload(harness.actor, upload_id=upload_id) == saved
    async with aiosqlite.connect(harness.db_path) as db:
        assert (await (await db.execute("SELECT COUNT(*) FROM wan3_prime_media")).fetchone())[0] == 1
        assert (await (await db.execute("SELECT COUNT(*) FROM generation_tasks")).fetchone())[0] == 1
    assert next(harness.module.UPLOAD_ROOT.rglob("*.txt")).read_bytes() == b"test"


@pytest.mark.asyncio
async def test_concurrent_same_id_init_creates_one_reservation_and_preserves_original_expiry(harness):
    await initialized(harness)
    upload_id = uuid.uuid4().hex
    first, second = await asyncio.gather(init(harness, upload_id=upload_id), init(harness, upload_id=upload_id))
    assert first == second
    assert (await row(harness, upload_id))["filename"] == "upload.txt"
    async with aiosqlite.connect(harness.db_path) as db:
        assert (await (await db.execute("SELECT COUNT(*) FROM wan3_prime_upload_sessions")).fetchone())[0] == 1


@pytest.mark.asyncio
async def test_init_id_collision_metadata_and_terminal_replays_never_create_reservations(harness):
    storage = await initialized(harness)
    upload_id = uuid.uuid4().hex
    await init(harness, upload_id=upload_id)
    variants = [
        {"actor": harness.foreign, "filename": "Файл.txt", "size": 4},
        {"actor": harness.actor, "filename": "different.txt", "size": 4},
        {"actor": harness.actor, "filename": "Файл.txt", "size": 5},
        {"actor": harness.actor, "filename": "Файл.txt", "size": 4, "content_type": "text/plain"},
    ]
    for kwargs in variants:
        with pytest.raises(ValidationError, match="Upload session conflict") as error:
            await storage.init_upload(kind="file", upload_id=upload_id, **kwargs)
        assert error.value.status == 409
    for status in ("assembling", "completed", "cancelled", "failed", "expired"):
        async with aiosqlite.connect(harness.db_path) as db:
            await db.execute("UPDATE wan3_prime_upload_sessions SET status = ? WHERE upload_id = ?", (status, upload_id))
            await db.commit()
        with pytest.raises(ValidationError, match="Upload session conflict"):
            await init(harness, upload_id=upload_id)


@pytest.mark.asyncio
async def test_init_replay_is_available_even_when_all_five_slots_are_taken(harness):
    await initialized(harness)
    upload_id = uuid.uuid4().hex
    original = await init(harness, upload_id=upload_id)
    for _ in range(4):
        await init(harness)
    assert await init(harness, upload_id=upload_id) == original


@pytest.mark.asyncio
async def test_expired_init_replay_is_a_conflict_and_cancel_can_release_the_slot(harness):
    storage = await initialized(harness)
    upload_id = uuid.uuid4().hex
    await init(harness, upload_id=upload_id)
    async with aiosqlite.connect(harness.db_path) as db:
        await db.execute("UPDATE wan3_prime_upload_sessions SET expires_at = '2000-01-01' WHERE upload_id = ?", (upload_id,))
        await db.commit()
    with pytest.raises(ValidationError, match="Upload session conflict") as error:
        await init(harness, upload_id=upload_id)
    assert error.value.status == 409
    assert (await storage.cancel_upload(harness.actor, upload_id=upload_id))["status"] == "cancelled"


@pytest.mark.asyncio
async def test_delayed_original_init_cannot_reopen_after_reconcile_then_cancel(harness, monkeypatch):
    storage = await initialized(harness)
    upload_id = uuid.uuid4().hex
    entered, resume = asyncio.Event(), asyncio.Event()
    original_lock = harness.policy.lock_storage
    first = True

    async def pause_first_lock(db):
        nonlocal first
        if first:
            first = False
            entered.set()
            await resume.wait()
        await original_lock(db)

    monkeypatch.setattr(harness.policy, "lock_storage", pause_first_lock)
    delayed_init = asyncio.create_task(init(harness, upload_id=upload_id))
    await entered.wait()
    # Cancelling the unknown ID alone is insufficient. A same-ID init replay
    # establishes the reservation before cancel, fencing the delayed request.
    assert (await storage.cancel_upload(harness.actor, upload_id=upload_id))["status"] == "not_found"
    await init(harness, upload_id=upload_id)
    await storage.cancel_upload(harness.actor, upload_id=upload_id)
    resume.set()
    with pytest.raises(ValidationError, match="Upload session conflict"):
        await delayed_init
    assert (await row(harness, upload_id))["status"] == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("upload_id", ["", "../escape", "A" * 32, "a" * 31, 123, True])
async def test_invalid_client_upload_id_never_creates_a_session(harness, upload_id):
    await initialized(harness)
    with pytest.raises(ValidationError, match="Invalid upload ID"):
        await init(harness, upload_id=upload_id)


@pytest.mark.asyncio
async def test_cancel_during_assembly_prevents_publication_and_failure_handler_reopening(harness, monkeypatch):
    storage = await initialized(harness)
    upload_id = (await init(harness))["upload_id"]
    await storage.save_chunk(harness.actor, upload_id=upload_id, index=0, total=1, chunk=b"test")
    entered, resume = threading.Event(), threading.Event()
    original = harness.files.assemble_chunks

    def paused(*args):
        entered.set()
        assert resume.wait(5)
        return original(*args)

    monkeypatch.setattr(harness.files, "assemble_chunks", paused)
    complete = asyncio.create_task(storage.complete_upload(harness.actor, upload_id=upload_id))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert await storage.cancel_upload(harness.actor, upload_id=upload_id) == {"ok": True, "status": "cancelled"}
    finally:
        resume.set()
    with pytest.raises(ValidationError, match="Upload reservation changed"):
        await complete
    assert (await row(harness, upload_id))["status"] == "cancelled"
    async with aiosqlite.connect(harness.db_path) as db:
        assert (await (await db.execute("SELECT COUNT(*) FROM wan3_prime_media")).fetchone())[0] == 0


@pytest.mark.asyncio
async def test_finalize_winning_transaction_returns_completed_and_cancel_cannot_delete_it(harness, monkeypatch):
    storage = await initialized(harness)
    upload_id = (await init(harness))["upload_id"]
    await storage.save_chunk(harness.actor, upload_id=upload_id, index=0, total=1, chunk=b"test")
    entered, resume = threading.Event(), threading.Event()
    original = harness.files.copy_atomic

    def paused(*args):
        entered.set()
        assert resume.wait(5)
        return original(*args)

    monkeypatch.setattr(harness.files, "copy_atomic", paused)
    complete = asyncio.create_task(storage.complete_upload(harness.actor, upload_id=upload_id))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        cancel = asyncio.create_task(storage.cancel_upload(harness.actor, upload_id=upload_id))
        await asyncio.sleep(0.02)
        assert not cancel.done()
    finally:
        resume.set()
    assert (await complete)["ok"] is True
    assert await cancel == {"ok": True, "status": "completed"}
    assert (await row(harness, upload_id))["status"] == "completed"


@pytest.mark.asyncio
async def test_inflight_chunk_finishes_before_cancel_and_future_chunks_are_rejected(harness, monkeypatch):
    storage = await initialized(harness)
    upload_id = (await init(harness))["upload_id"]
    entered, resume = threading.Event(), threading.Event()
    original = harness.files.write_chunk

    def paused(*args):
        entered.set()
        assert resume.wait(5)
        return original(*args)

    monkeypatch.setattr(harness.files, "write_chunk", paused)
    chunk = asyncio.create_task(storage.save_chunk(harness.actor, upload_id=upload_id, index=0, total=1, chunk=b"test"))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        cancel = asyncio.create_task(storage.cancel_upload(harness.actor, upload_id=upload_id))
        await asyncio.sleep(0.02)
        assert not cancel.done()
    finally:
        resume.set()
    await chunk
    assert (await cancel)["status"] == "cancelled"
    assert (await row(harness, upload_id))["received_chunks"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("init_data", "expected_status", "expected_code"), [
    (None, 401, "auth_required"), ("invalid", 401, "auth_invalid"), ("synthetic-signed", 200, None),
])
async def test_cancel_route_requires_existing_signed_auth_before_storage(harness, init_data, expected_status, expected_code):
    calls = []

    async def user_context(_app, value, _start):
        if value != "synthetic-signed":
            raise ValueError("invalid signature")
        return 101, {"user_id": 1}

    async def banned(_telegram_id):
        return False

    async def cancel(actor, *, upload_id):
        calls.append((actor.user_id, upload_id))
        return {"ok": True, "status": "cancelled"}

    miniapp = harness.module_factory("bot.miniapp", {"_get_user_context": user_context})
    sys.modules["bot"].miniapp = miniapp
    sys.modules["bot.database"].is_user_banned = banned
    harness.module_factory("bot.config", {"config": types.SimpleNamespace(is_admin=lambda _: False)})
    namespace = {"web": web, "Any": Any, "Wan3PrimeLifecycleError": LifecycleError,
        "Wan3PrimeValidationError": ValidationError, "Wan3PrimeActor": types.SimpleNamespace,
        "wan3_prime_storage": types.SimpleNamespace(cancel_upload=cancel)}
    selected_source("bot/wan3_prime_api.py", ["_actor_from_request", "_json_body", "_json_ok", "_json_error", "_upload_cancel_route"], namespace)

    class Request:
        def __init__(self):
            self.app = {}
            self.headers = {}

        async def json(self):
            return {"upload_id": "a" * 32, "initData": init_data}

    response = await namespace["_upload_cancel_route"](Request())
    assert response.status == expected_status
    payload = json.loads(response.text)
    assert response.headers["Cache-Control"] == "no-store"
    if expected_code:
        assert payload["code"] == expected_code
        assert not calls
    else:
        assert calls == [(1, "a" * 32)]


@pytest.mark.asyncio
async def test_init_route_forwards_id_and_emits_specific_durable_conflict_code(harness):
    received = []

    async def actor(_request, _body):
        return harness.actor

    async def storage_init(_actor, **kwargs):
        received.append(kwargs)
        raise ValidationError("Upload session conflict", status=409)

    namespace = {"web": web, "Any": Any, "Wan3PrimeLifecycleError": LifecycleError,
        "Wan3PrimeValidationError": ValidationError, "_actor_from_request": actor,
        "wan3_prime_storage": types.SimpleNamespace(init_upload=storage_init)}
    selected_source("bot/wan3_prime_api.py", ["_json_body", "_json_ok", "_json_error", "_upload_init_route"], namespace)

    class Request:
        async def json(self):
            return {"upload_id": "a" * 32, "kind": "file", "filename": "Файл.txt", "size": 4}

    response = await namespace["_upload_init_route"](Request())
    assert response.status == 409
    assert json.loads(response.text)["code"] == "upload_session_conflict"
    assert received == [{"upload_id": "a" * 32, "kind": "file", "filename": "Файл.txt", "size": 4, "content_type": ""}]


def test_cancel_route_registered_at_existing_signed_api_root():
    tree = ast.parse((ROOT / "bot/wan3_prime_api.py").read_text())
    setup = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "setup_wan3_prime_routes")
    routes = [node for node in ast.walk(setup) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_post"]
    cancel = [node for node in routes if "/api/wan3/upload/cancel" in ast.unparse(node.args[0])]
    assert len(cancel) == 1
    assert ast.unparse(cancel[0].args[1]) == "_http_boundary(_upload_cancel_route)"



@pytest.mark.asyncio
async def test_request_abort_cannot_leave_untracked_final_copy(harness, monkeypatch):
    storage = await initialized(harness)
    upload_id = (await init(harness))["upload_id"]
    await storage.save_chunk(harness.actor, upload_id=upload_id, index=0, total=1, chunk=b"test")
    entered, resume, copied = threading.Event(), threading.Event(), threading.Event()
    original = harness.files.copy_atomic

    def paused(*args):
        entered.set()
        assert resume.wait(5)
        result = original(*args)
        copied.set()
        return result

    monkeypatch.setattr(harness.files, "copy_atomic", paused)
    complete = asyncio.create_task(storage.complete_upload(harness.actor, upload_id=upload_id))
    assert await asyncio.to_thread(entered.wait, 5)
    complete.cancel()
    await asyncio.sleep(.05)
    cancel = asyncio.create_task(storage.cancel_upload(harness.actor, upload_id=upload_id))
    await asyncio.sleep(.05)
    resume.set()
    with pytest.raises(asyncio.CancelledError):
        await complete
    outcome = await cancel
    assert await asyncio.to_thread(copied.wait, 5)
    final_files = list(harness.module.UPLOAD_ROOT.rglob("*.txt"))
    async with aiosqlite.connect(harness.db_path) as db:
        media_count = (await (await db.execute("SELECT COUNT(*) FROM wan3_prime_media")).fetchone())[0]
    assert len(final_files) == media_count, (outcome, dict(await row(harness, upload_id)), final_files, media_count)


@pytest.mark.asyncio
async def test_import_request_abort_awaits_shared_persistence_before_discarding_temporary_files(harness, monkeypatch):
    storage = await initialized(harness)

    async def fetch(url, *, destination, max_bytes):
        destination.write_bytes(b"test")
        return {"url": url, "content_type": "text/plain", "size": 4}

    monkeypatch.setattr(harness.module, "fetch_public_asset", fetch, raising=False)
    entered, resume, copied = threading.Event(), threading.Event(), threading.Event()
    original = harness.files.copy_atomic

    def paused(*args):
        entered.set()
        assert resume.wait(5)
        result = original(*args)
        copied.set()
        return result

    monkeypatch.setattr(harness.files, "copy_atomic", paused)
    importing = asyncio.create_task(storage.import_url(harness.actor, kind="file", url="https://reference.test/material.txt"))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        importing.cancel()
        await asyncio.sleep(.05)
        assert not importing.done()
    finally:
        resume.set()
    with pytest.raises(asyncio.CancelledError):
        await importing
    assert copied.is_set()
    async with aiosqlite.connect(harness.db_path) as db:
        sessions = await (await db.execute("SELECT upload_id, status, completed_result FROM wan3_prime_upload_sessions")).fetchall()
        media_count = (await (await db.execute("SELECT COUNT(*) FROM wan3_prime_media")).fetchone())[0]
    assert len(sessions) == 1 and sessions[0][1] == "completed" and sessions[0][2]
    assert len(list(harness.module.UPLOAD_ROOT.rglob("*.txt"))) == media_count == 1
    assert not (harness.module.CHUNK_ROOT / sessions[0][0]).exists()
    assert (await storage.cancel_upload(harness.actor, upload_id=sessions[0][0]))["status"] == "completed"
