import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import aiosqlite
import pytest

from bot.genjutsu.contract import PipelineError, compile_plan, quote_plan
from bot.genjutsu.pipeline import Pipeline
from bot.genjutsu.provider import ProviderFailure
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


async def make_quote(repo, *, variants=1, steps=1):
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
        "variants": variants,
        "continuation": "automatic",
    }
    draft["steps"] *= steps
    project = await repo.save_project(101, "race", draft)
    settings, version = await repo.settings()
    owned = await repo.get_assets(101, {source["id"], ref["id"]})
    plan = compile_plan(draft, owned, settings)
    quote = quote_plan(plan, owned, settings)
    return await repo.create_quote(101, project["id"], project["revision"], plan, quote, version, settings)


@pytest.mark.asyncio
async def test_reference_plus_generation_seconds_require_enough_balance(tmp_path):
    repo, _ = await build_repo(tmp_path, credits=9)
    quote = await make_quote(repo)
    assert quote["total_credits"] == 10
    with pytest.raises(PipelineError, match="insufficient_balance"):
        await repo.start(101, "insufficient-two-component-charge", quote["id"])
    assert await repo.balance(101) == 9
    assert await repo.existing_run(101, "insufficient-two-component-charge", quote["id"]) is None


@pytest.mark.asyncio
async def test_accepted_legacy_run_keeps_original_single_duration_charge(tmp_path):
    """Deploying a new price formula must not break an already reserved run."""
    repo, _ = await build_repo(tmp_path)
    quote = await make_quote(repo)
    accepted = await repo.start(101, "accepted-before-new-price", quote["id"])
    # Emulate the persisted quote, debit, and step reserve created by the old
    # deployment; only the quote format, not the request/step IDs, changes.
    async with repo.transaction() as db:
        legacy_quote = {
            "total_credits": 5,
            "allocations": [{
                "variant": 0, "ordinal": 0, "operation": "motion_transfer",
                "billable_seconds": 5, "credits_per_second": 1,
                "reserved_credits": 5, "maximum_reserve": False,
            }],
        }
        await db.execute("UPDATE genjutsu_quotes SET quote=? WHERE id=?",
                         (json.dumps(legacy_quote), quote["id"]))
        await db.execute("UPDATE genjutsu_steps SET reserved_credits=5 WHERE run_id=?",
                         (accepted["id"],))
        await db.execute("UPDATE genjutsu_finance SET amount=5 WHERE id=?",
                         ("reserve:" + accepted["id"],))
        await db.execute("UPDATE users SET credits=credits+5 WHERE telegram_id=101")
    assert await repo.balance(101) == 95
    settings, _ = await repo.settings()
    step = await repo.claim_step(settings)
    await repo.begin_submission(step["id"], step["lease_token"], 5_000)
    in_flight = await repo.get_run(101, accepted["id"])
    assert in_flight["steps"][0]["actual_credits"] == 5
    output = await repo.add_asset(101, "video", "accepted-legacy-result.mp4",
                                  {"duration_ms": 5_000, "size_bytes": 123})
    await repo.finish_step(step["id"], step["lease_token"],
                           "completed", output_asset_id=output["id"])
    assert await repo.balance(101) == 95


@pytest.mark.asyncio
async def test_pre_change_quote_is_rejected_before_debit(tmp_path):
    repo, _ = await build_repo(tmp_path)
    quote = await make_quote(repo)
    before = await repo.balance(101)
    # Quotes may outlive the deployment that created them.
    legacy_quote = {key: value for key, value in quote.items()
                    if key not in {"id", "expires_ms", "pricing_version"}}
    async with repo.transaction() as db:
        await db.execute("UPDATE genjutsu_quotes SET quote=? WHERE id=?",
                         (json.dumps(legacy_quote), quote["id"]))
    with pytest.raises(PipelineError, match="quote_changed"):
        await repo.start(101, "legacy-pricing-request", quote["id"])
    assert await repo.balance(101) == before


@pytest.mark.asyncio
async def test_concurrent_duplicate_start_debits_once(tmp_path):
    repo, _ = await build_repo(tmp_path)
    quote = await make_quote(repo)
    assert quote["total_credits"] == 10  # 5 reference seconds + 5 generated seconds.
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
    in_flight = await repo.get_run(101, run["id"])
    assert in_flight["steps"][0]["actual_credits"] == 10
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


@pytest.mark.asyncio
async def test_accepted_task_can_be_parked_without_refund_and_reconciled(tmp_path):
    repo, _ = await build_repo(tmp_path)
    quote = await make_quote(repo)
    before = await repo.balance(101)
    run = await repo.start(101, "recovery-review", quote["id"])
    settings, _ = await repo.settings()
    ready = await repo.claim_step(settings)
    attempt = await repo.begin_submission(ready["id"], ready["lease_token"], 5_000)
    await repo.accept_submission(
        ready["id"], attempt, "req-recovery",
        status_url="https://api.higgsfield.ai/requests/req-recovery/status",
        cancel_url="https://api.higgsfield.ai/requests/req-recovery/cancel",
        correlation_id="corr-recovery",
    )
    queued = await repo.claim_step(settings)
    assert queued and queued["status"] == "queued"
    await repo.park_step(queued["id"], queued["lease_token"], "retry_deadline_exceeded:provider_http_503")
    view = await repo.get_run(101, run["id"])
    assert view["state"] == "review"
    assert view["steps"][0]["status"] == "recovery_review"
    assert view["steps"][0]["refunded_credits"] == 0
    assert await repo.balance(101) == before - quote["total_credits"]

    await repo.request_reconciliation(999, run["id"], queued["id"])
    resumed = await repo.get_run(101, run["id"])
    assert resumed["state"] == "running"
    assert resumed["steps"][0]["status"] == "queued"
    assert resumed["steps"][0]["error_code"] is None


@pytest.mark.asyncio
async def test_nonterminal_provider_http_error_never_refunds_accepted_generation(tmp_path):
    repo, _ = await build_repo(tmp_path)
    quote = await make_quote(repo)
    before = await repo.balance(101)
    run = await repo.start(101, "accepted-http-error", quote["id"])
    settings, _ = await repo.settings()
    ready = await repo.claim_step(settings)
    attempt = await repo.begin_submission(ready["id"], ready["lease_token"], 5_000)
    await repo.accept_submission(ready["id"], attempt, "req-http-error")

    class Provider:
        configured = True
        async def status(self, *args, **kwargs):
            raise ProviderFailure("provider_http_422", http_status=422)

    pipeline = Pipeline(repo, Provider(), SimpleNamespace(configured=True))
    assert await pipeline.tick() is True
    view = await repo.get_run(101, run["id"])
    assert view["state"] == "review"
    assert view["steps"][0]["status"] == "recovery_review"
    assert view["steps"][0]["refunded_credits"] == 0
    assert await repo.balance(101) == before - quote["total_credits"]


@pytest.mark.asyncio
async def test_provider_observation_keeps_terminal_status_and_safe_provider_reason(tmp_path):
    repo, _ = await build_repo(tmp_path)
    quote = await make_quote(repo)
    run = await repo.start(101, "provider-observation", quote["id"])
    settings, _ = await repo.settings()
    step = await repo.claim_step(settings)

    await repo.record_provider_observation(
        step["id"],
        step["lease_token"],
        "corr-123",
        "provider_status_observed",
        details={
            "provider_status": "nsfw",
            "provider_reason": "content_safety_restrictions",
        },
    )

    events = await repo.events(run["id"])
    event = next(item for item in events if item["event"] == "provider_status_observed")
    details = json.loads(event["details"])
    assert details == {
        "provider_correlation_id": "corr-123",
        "provider_status": "nsfw",
        "provider_reason": "content_safety_restrictions",
    }


@pytest.mark.asyncio
async def test_terminal_provider_moderation_refunds_and_records_safe_reason(tmp_path):
    repo, _ = await build_repo(tmp_path)
    quote = await make_quote(repo)
    before = await repo.balance(101)
    run = await repo.start(101, "provider-moderation-terminal", quote["id"])
    settings, _ = await repo.settings()
    ready = await repo.claim_step(settings)
    attempt = await repo.begin_submission(ready["id"], ready["lease_token"], 5_000)
    await repo.accept_submission(ready["id"], attempt, "req-moderation")

    class Provider:
        configured = True

        async def status(self, *args, **kwargs):
            return {
                "status": "nsfw",
                "correlation_id": "corr-moderation",
                "reason": "content_safety_restrictions",
            }

    pipeline = Pipeline(repo, Provider(), SimpleNamespace(configured=True))
    assert await pipeline.tick() is True

    view = await repo.get_run(101, run["id"])
    step = view["steps"][0]
    assert view["state"] == "failed"
    assert step["status"] == "failed"
    assert step["error_code"] == "provider_nsfw"
    assert step["refunded_credits"] == quote["total_credits"]
    assert await repo.balance(101) == before

    events = await repo.events(run["id"])
    observation = next(
        item for item in events
        if item["event"] == "provider_status_observed"
    )
    details = json.loads(observation["details"])
    assert details["provider_status"] == "nsfw"
    assert details["provider_reason"] == "content_safety_restrictions"
    assert details["provider_correlation_id"] == "corr-moderation"
