"""Validate the PostgreSQL test harness without opening any DB connection."""
import pytest

from tests.test_creator_tariff_postgres import validated_test_dsn

LOCAL_DSN = "postgresql://creator_test:creator_test@127.0.0.1:5432/banano_creator_test"


def test_disposable_loopback_dsn_is_accepted():
    assert validated_test_dsn(LOCAL_DSN) == LOCAL_DSN


@pytest.mark.parametrize("dsn", [
    LOCAL_DSN.replace("127.0.0.1", "db.example.test"),
    LOCAL_DSN.replace("banano_creator_test", "production"),
    LOCAL_DSN.replace("creator_test:creator_test", "postgres:postgres"),
    LOCAL_DSN + "?hostaddr=192.0.2.1",
    LOCAL_DSN + "?service=production",
    LOCAL_DSN + "?options=-csearch_path%3Dpublic",
    LOCAL_DSN.replace(":5432/", ":99999/"),
    "dbname=banano_creator_test user=creator_test password=creator_test",
    "",
])
def test_nonisolated_or_implicit_connections_are_rejected(dsn):
    with pytest.raises(ValueError):
        validated_test_dsn(dsn)


@pytest.mark.asyncio
async def test_connector_explicitly_pins_loopback_even_with_libpq_environment(monkeypatch):
    from unittest.mock import AsyncMock

    import psycopg

    from tests.test_creator_tariff_postgres import connect_test_database

    connect = AsyncMock()
    monkeypatch.setenv("PGHOSTADDR", "192.0.2.1")
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    await connect_test_database(LOCAL_DSN, autocommit=True)
    connect.assert_awaited_once_with(
        LOCAL_DSN, host="127.0.0.1", hostaddr="127.0.0.1",
        connect_timeout=5, sslmode="disable", autocommit=True,
    )
