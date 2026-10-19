"""Run the public draft/finance seam on a guarded disposable PostgreSQL DB."""
import os
from urllib.parse import urlsplit

import pytest

pytestmark = pytest.mark.skipif(os.getenv('SMART_REPEAT_POSTGRES_TEST') != '1',
    reason='requires disposable smart-repeat PostgreSQL acceptance job')


@pytest.fixture(autouse=True)
async def disposable_schema():
    if os.getenv('SMART_REPEAT_POSTGRES_TEST') != '1':
        yield
        return
    import psycopg

    from bot import db as db_backend
    from bot.smart_repeat_store import ensure_schema
    dsn = os.environ['DATABASE_URL']
    parsed = urlsplit(dsn)
    assert parsed.hostname in {'localhost', '127.0.0.1'} and parsed.path == '/banano_partner_test'
    assert db_backend.is_postgres()
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute('TRUNCATE generation_tasks, users, saved_references, smart_repeat_drafts, smart_repeat_templates RESTART IDENTITY CASCADE')
    async with db_backend.connect() as db:
        await ensure_schema(db)
        await ensure_schema(db)
        await db.commit()
    yield


@pytest.mark.asyncio
async def test_postgres_concurrent_claim_one_debit_refund(monkeypatch, tmp_path):
    from tests.test_smart_repeat_store import (
        test_concurrent_launch_one_debit_and_refund_only_once,
    )
    await test_concurrent_launch_one_debit_and_refund_only_once(monkeypatch, tmp_path)


@pytest.mark.asyncio
async def test_postgres_upload_lease_recovery_and_missing_asset(monkeypatch, tmp_path):
    from tests.test_smart_repeat_store import (
        test_upload_fencing_reload_delete_and_no_early_quote,
    )
    await test_upload_fencing_reload_delete_and_no_early_quote(monkeypatch, tmp_path)


@pytest.mark.asyncio
async def test_postgres_saved_reference_identity_and_filename(monkeypatch, tmp_path):
    from tests.test_smart_repeat_store import (
        test_saved_reference_id_binds_owned_asset_to_slot_and_restores_metadata,
    )
    await test_saved_reference_id_binds_owned_asset_to_slot_and_restores_metadata(monkeypatch, tmp_path)
