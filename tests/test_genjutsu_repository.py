import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import pytest

from bot.genjutsu.contract import compile_plan, quote_plan
from bot.genjutsu.repository import SCHEMA, Repository


@asynccontextmanager
async def sqlite_connect(path):
    db = await aiosqlite.connect(path, timeout=10)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def build_repo(tmp_path, credits=100):
    path = tmp_path / "genjutsu.sqlite3"

    @asynccontextmanager
    async def connect():
        async with sqlite_connect(path) as db:
            yield db

    async with connect() as db:
        await db.execute("CREATE TABLE users (telegram_id INTEGER PRIMARY KEY, credits REAL NOT NULL)")
        await db.execute("INSERT INTO users VALUES (?, ?)", (101, credits))
        await db.commit()

    repo = Repository(connect)
    await repo.migrate()
    settings, version = await repo.settings()
    settings["public_enabled"] = True
    settings["verified_operations"] = ["motion_transfer", "object_swap", "restyle"]
    settings["prices"] = {
        "motion_transfer": {"480p": 1, "720p": 1, "1080p": 1},
        "object_swap": {"480p": 1, "720p": 1, "1080p": 1},
        "restyle": {"480p": 1, "720p": 1, "1080p": 1},
    }
    await repo.update_settings(999, version, settings)
    return repo, connect


async def make_quote(repo):
    source = await repo.add_asset(101, "video", "a" * 32 + ".mp4", {
        "duration_ms": 5_000, "size_bytes": 100, "mime": "video/mp4",
    })
    ref = await repo.add_asset(101, "image", "b" * 32 + ".png", {
        "size_bytes": 10, "mime": "image/png",
    })
    draft = {
        "source_asset_id": source["id"],
        "steps": [{
            "operation": "motion_transfer", "resolution": "720p",
            "prompt": "", "preserve": "",
            "references": [{"asset_id": ref["id"], "role": "character", "label": ""}],
            "preset_id": None,
        }],
        "variants": 1,
        "continuation": "automatic",
    }
    project = await repo.save_project(101, "race", draft)
    settings, version = await repo.settings()
    owned = await repo.get_assets(101, {source["id"], ref["id"]})
    plan = compile_plan(draft, owned, settings)
    quote = quote_plan(plan, owned, settings)
    return await repo.create_quote(101, project["id"], project["revision"], plan, quote, version, settings)


@pytest.mark.asyncio
async def test_concurrent_duplicate_start_debits_once(tmp_path):
    repo, _ = await build_repo(tmp_path)
    quote = await make_quote(repo)
    before = await repo.balance(101)
    left, right = await asyncio.gather(
        repo.start(101, "same-request-key", quote["id"]),
        repo.start(101, "same-request-key", quote["id"]),
    )
    assert left["id"] == right["id"]
    assert await repo.balance(101) == before - quote["total_credits"]


@pytest.mark.asyncio
async def test_failed_step_refunds_reserve_exactly_once(tmp_path):
    repo, _ = await build_repo(tmp_path)
    quote = await make_quote(repo)
    before = await repo.balance(101)
    run = await repo.start(101, "failure-request", quote["id"])
    settings, _ = await repo.settings()
    step = await repo.claim_step(settings)
    assert step and step["run_id"] == run["id"]
    await repo.begin_submission(step["id"], step["lease_token"], 5_000)
    await repo.finish_step(step["id"], step["lease_token"], "failed", error_code="provider_failed")
    assert await repo.balance(101) == before
    view = await repo.get_run(101, run["id"])
    assert view["steps"][0]["refunded_credits"] == quote["total_credits"]


@pytest.mark.asyncio
async def test_crashed_submission_becomes_review_and_is_not_resubmitted(tmp_path):
    clock = [1_000_000]
    path = tmp_path / "clocked.sqlite3"

    @asynccontextmanager
    async def connect():
        async with sqlite_connect(path) as db:
            yield db

    async with connect() as db:
        await db.execute("CREATE TABLE users (telegram_id INTEGER PRIMARY KEY, credits REAL NOT NULL)")
        await db.execute("INSERT INTO users VALUES (101, 100)")
        await db.commit()
    repo = Repository(connect, clock=lambda: clock[0])
    await repo.migrate()
    settings, version = await repo.settings()
    settings["public_enabled"] = True
    settings["verified_operations"] = ["motion_transfer"]
    settings["prices"] = {
        "motion_transfer": {"480p": 1, "720p": 1, "1080p": 1},
        "object_swap": {"480p": 1, "720p": 1, "1080p": 1},
        "restyle": {"480p": 1, "720p": 1, "1080p": 1},
    }
    await repo.update_settings(999, version, settings)
    quote = await make_quote(repo)
    run = await repo.start(101, "ambiguous-submit", quote["id"])
    settings, _ = await repo.settings()
    step = await repo.claim_step(settings)
    await repo.begin_submission(step["id"], step["lease_token"], 5_000)
    clock[0] += settings["lease_seconds"] * 1_000 + 1
    assert await repo.claim_step(settings) is None
    view = await repo.get_run(101, run["id"])
    assert view["state"] == "review"
    assert view["steps"][0]["status"] == "submission_unknown"
    assert view["steps"][0]["attempt_id"]


@pytest.mark.asyncio
async def test_settings_version_increments_once_per_update(tmp_path):
    repo, _ = await build_repo(tmp_path)
    settings, version = await repo.settings()
    settings["max_variants"] = 3
    returned = await repo.update_settings(999, version, settings)
    _, stored = await repo.settings()
    assert returned == version + 1
    assert stored == returned


@pytest.mark.asyncio
async def test_migrate_uses_native_postgres_ddl_seam():
    class FakePostgresConnection:
        def __init__(self):
            self.ddl = []
            self.statements = []

        async def execute_native_ddl(self, sql):
            self.ddl.append(sql)

        async def execute(self, sql, parameters=()):
            self.statements.append((sql, parameters))

        async def commit(self):
            return None

    db = FakePostgresConnection()

    @asynccontextmanager
    async def connect():
        yield db

    await Repository(connect).migrate()

    assert db.ddl == SCHEMA
    assert len(db.statements) == 2


def test_native_postgres_schema_contains_all_genjutsu_tables():
    schema = (Path(__file__).parents[1] / "schema_postgres.sql").read_text(encoding="utf-8")
    for statement in SCHEMA:
        if "CREATE TABLE" not in statement:
            continue
        table = statement.split("CREATE TABLE IF NOT EXISTS ", 1)[1].split(None, 1)[0]
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema
