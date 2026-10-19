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
    from bot.services.wan3_prime_storage import Wan3PrimeStorage
    await Wan3PrimeStorage().init_schema()
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute('TRUNCATE wan3_prime_media, generation_tasks, users, saved_references, smart_repeat_drafts, smart_repeat_templates RESTART IDENTITY CASCADE')
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


@pytest.mark.asyncio
async def test_postgres_wan_and_saved_reference_namespace_collision(monkeypatch, tmp_path):
    from tests.test_smart_repeat_store import (
        test_wan_and_saved_media_ids_have_distinct_owned_namespaces,
    )
    await test_wan_and_saved_media_ids_have_distinct_owned_namespaces(monkeypatch, tmp_path)


@pytest.mark.asyncio
async def test_postgres_optional_photo_images_and_fixed_positions(monkeypatch, tmp_path):
    from tests.test_smart_repeat_extra_images import (
        test_optional_photo_budget_and_fixed_positions_survive_remove_reload,
    )
    await test_optional_photo_budget_and_fixed_positions_survive_remove_reload(monkeypatch, tmp_path)


@pytest.mark.asyncio
async def test_postgres_extra_photo_http_concurrent_launch(monkeypatch, tmp_path):
    from tests.test_smart_repeat_extra_images import (
        test_http_extras_reach_real_image_engine_after_main_and_fixed_refs_once,
    )
    await test_http_extras_reach_real_image_engine_after_main_and_fixed_refs_once(monkeypatch, tmp_path)


@pytest.mark.asyncio
async def test_postgres_native_cancelled_debit_recovers_once(monkeypatch):
    from tests.test_native_repeat_receipt import (
        test_cancel_after_atomic_debit_has_durable_receipt_and_refunds_once_on_reopen,
    )
    await test_cancel_after_atomic_debit_has_durable_receipt_and_refunds_once_on_reopen(monkeypatch)


@pytest.mark.asyncio
async def test_postgres_native_refund_fences_suspended_worker(monkeypatch):
    from tests.test_native_repeat_receipt import (
        test_refunded_receipt_fences_a_suspended_worker_before_task_and_provider,
    )
    await test_refunded_receipt_fences_a_suspended_worker_before_task_and_provider(monkeypatch)


@pytest.mark.asyncio
async def test_postgres_native_accepted_task_never_refunded_on_reopen(monkeypatch):
    from tests.test_native_repeat_receipt import (
        test_cancel_after_task_capture_never_guesses_provider_failure_or_refunds,
    )
    await test_cancel_after_task_capture_never_guesses_provider_failure_or_refunds(monkeypatch)


@pytest.mark.asyncio
async def test_postgres_native_duplicate_claim_and_miniapp_namespace(monkeypatch):
    from tests.test_native_repeat_receipt import (
        test_native_claim_is_atomic_across_independent_contexts_and_hidden_from_miniapp,
    )
    await test_native_claim_is_atomic_across_independent_contexts_and_hidden_from_miniapp(monkeypatch)


@pytest.mark.asyncio
async def test_postgres_native_template_less_withdrawal(monkeypatch):
    from tests.test_native_repeat_receipt import (
        test_template_less_withdrawn_source_rejected_before_debit,
    )
    await test_template_less_withdrawn_source_rejected_before_debit(monkeypatch)
