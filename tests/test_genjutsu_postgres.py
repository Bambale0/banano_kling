"""Genjutsu schema and financial invariants through the real PostgreSQL adapter."""
import asyncio
import os

import psycopg
import pytest

from bot import db as db_backend
from bot.genjutsu.contract import compile_plan, quote_plan
from bot.genjutsu.repository import Repository
from tests.runtime72_postgres_fixture import runtime_postgres_schema

pytestmark = pytest.mark.skipif(
    os.environ.get("RUNTIME_POSTGRES_TEST") != "1",
    reason="requires the dedicated ephemeral PostgreSQL runtime job",
)


@pytest.fixture(autouse=True)
async def genjutsu_postgres_schema(isolated_database):
    assert db_backend.is_postgres()
    async with runtime_postgres_schema():
        yield


@pytest.mark.asyncio
async def test_postgres_migration_and_concurrent_refund_are_idempotent():
    owner = 93939393
    repo = Repository(db_backend.connect)
    await repo.migrate()
    await repo.migrate()

    async with await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        await connection.execute(
            "INSERT INTO users(telegram_id, credits) VALUES(%s, 100) "
            "ON CONFLICT(telegram_id) DO UPDATE SET credits=100",
            (owner,),
        )
        await connection.commit()

    settings, version = await repo.settings()
    settings["public_enabled"] = True
    settings["verified_operations"] = ["motion_transfer"]
    settings["prices"]["motion_transfer"] = {"480p": 1, "720p": 1, "1080p": 1}
    await repo.update_settings(1, version, settings)

    source = await repo.add_asset(owner, "video", "pg-source.mp4", {
        "duration_ms": 5_000, "size_bytes": 100, "mime": "video/mp4",
    })
    reference = await repo.add_asset(owner, "image", "pg-reference.png", {
        "size_bytes": 10, "mime": "image/png",
    })
    draft = {
        "source_asset_id": source["id"],
        "steps": [{
            "operation": "motion_transfer", "resolution": "720p", "prompt": "",
            "preserve": "", "references": [{
                "asset_id": reference["id"], "role": "character", "label": "",
            }], "preset_id": None,
        }],
        "variants": 1,
        "continuation": "automatic",
    }
    project = await repo.save_project(owner, "PostgreSQL", draft)
    settings, version = await repo.settings()
    assets = await repo.get_assets(owner, {source["id"], reference["id"]})
    plan = compile_plan(draft, assets, settings)
    quote = await repo.create_quote(
        owner, project["id"], project["revision"], plan,
        quote_plan(plan, assets, settings), version, settings,
    )
    left, right = await asyncio.gather(
        repo.start(owner, "postgres-idempotency", quote["id"]),
        repo.start(owner, "postgres-idempotency", quote["id"]),
    )
    assert left["id"] == right["id"]
    step = await repo.claim_step(settings)
    await repo.finish_step(step["id"], step["lease_token"], "failed", error_code="test")
    assert await repo.balance(owner) == 100
