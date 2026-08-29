from pathlib import Path

import pytest

from bot import postgres_pool

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_postgres_adapter_uses_bounded_async_pool() -> None:
    source = _read("bot/postgres_pool.py")
    db_source = _read("bot/db.py")

    assert "AsyncConnectionPool" in source
    assert "async def _get_postgres_pool" in source
    assert ".getconn(" in source
    assert ".putconn(" in source
    assert "PG_POOL_MAX_SIZE" in source
    assert "PG_POOL_TIMEOUT_SECONDS" in source
    assert "from bot.postgres_pool import connect as postgres_connect" in db_source


def test_pool_is_prepared_before_application_can_observe_it() -> None:
    source = _read("bot/postgres_pool.py")

    assert source.index("await _prepare_pool(pool)") < source.index("_POOL = pool")


def test_postgres_pool_preserves_legacy_rollback_on_close() -> None:
    source = _read("bot/postgres_pool.py")
    close_block = source.split("async def close(self) -> None:", 1)[1].split(
        "class PostgresPoolConnect", 1
    )[0]

    assert "rollback" in close_block
    assert "putconn" in close_block


def test_pool_dependency_is_installed_with_binary_psycopg() -> None:
    requirements = _read("requirements.txt")

    assert "psycopg[binary,pool]" in requirements


def test_hot_admin_lookup_indexes_are_installed() -> None:
    source = _read("bot/postgres_pool.py")

    for index_name in (
        "idx_generation_history_user_id",
        "idx_transactions_user_status_created",
        "idx_users_referred_by",
        "idx_partner_withdrawals_user_created",
    ):
        assert index_name in source


class _FakeRawConnection:
    def __init__(self) -> None:
        self.rollback_calls = 0

    async def rollback(self) -> None:
        self.rollback_calls += 1


class _FakePool:
    def __init__(self, raw: _FakeRawConnection) -> None:
        self.raw = raw
        self.getconn_calls = 0
        self.putconn_calls = 0
        self.timeouts: list[float] = []

    async def getconn(self, timeout: float | None = None):
        self.getconn_calls += 1
        self.timeouts.append(float(timeout or 0))
        return self.raw

    async def putconn(self, raw) -> None:
        assert raw is self.raw
        self.putconn_calls += 1


@pytest.mark.asyncio
async def test_connector_returns_checked_out_connection_to_pool(monkeypatch) -> None:
    raw = _FakeRawConnection()
    pool = _FakePool(raw)

    async def fake_get_pool():
        return pool

    async def fake_prepare(_raw) -> None:
        return None

    monkeypatch.setattr(postgres_pool, "_get_postgres_pool", fake_get_pool)
    monkeypatch.setattr(
        postgres_pool.legacy,
        "_ensure_postgres_helpers",
        fake_prepare,
    )
    monkeypatch.setattr(postgres_pool, "_ensure_performance_indexes", fake_prepare)

    connector = postgres_pool.connect()
    connection = await connector
    await connection.close()

    assert pool.getconn_calls == 1
    assert pool.putconn_calls == 1
    assert raw.rollback_calls == 1
    assert pool.timeouts == [postgres_pool._pool_timeout()]


@pytest.mark.asyncio
async def test_connection_close_is_idempotent() -> None:
    raw = _FakeRawConnection()
    pool = _FakePool(raw)
    connection = postgres_pool.PooledPostgresConnection(raw, pool)

    await connection.close()
    await connection.close()

    assert raw.rollback_calls == 1
    assert pool.putconn_calls == 1
