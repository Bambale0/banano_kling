from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_postgres_adapter_uses_bounded_async_pool() -> None:
    source = _read("bot/postgres_aiosqlite.py")

    assert "AsyncConnectionPool" in source
    assert "async def _get_postgres_pool" in source
    assert ".getconn(" in source
    assert ".putconn(" in source
    assert "PG_POOL_MAX_SIZE" in source
    assert "PG_POOL_TIMEOUT_SECONDS" in source


def test_postgres_pool_preserves_legacy_rollback_on_close() -> None:
    source = _read("bot/postgres_aiosqlite.py")
    close_block = source.split("async def close(self) -> None:", 1)[1].split(
        "async def __aenter__", 1
    )[0]

    assert "rollback" in close_block
    assert "_release" in close_block


def test_pool_dependency_is_installed_with_binary_psycopg() -> None:
    requirements = _read("requirements.txt")

    assert "psycopg[binary,pool]" in requirements


def test_partner_lookup_supporting_index_is_declared() -> None:
    schema = _read("schema_postgres.sql")
    runtime = _read("bot/postgres_aiosqlite.py")

    expected = "idx_users_referred_by"
    assert expected in schema
    assert expected in runtime
