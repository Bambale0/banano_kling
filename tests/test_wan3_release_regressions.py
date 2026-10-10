"""User-boundary regressions from the Wan release review."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import wan3_prime as tg
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
from tests.test_wan3_prime_lifecycle import Prices, Probe, Provider, body, user_actor
from tests.test_wan3_prime_telegram_fsm import FakeCallback, FakeState


@pytest.mark.asyncio
async def test_edit_source_removal_does_not_promote_video2():
    state = FakeState()
    draft = tg.Wan3PrimeDraft(scenario="edit", prompt="Change the jacket",
        reference_video_urls=["https://owned.test/source.mp4", "https://owned.test/style.mp4"])
    await state.update_data(**tg.draft_to_state(draft))
    await tg.remove_wan3_media(FakeCallback("wan3_remove:video:0"), state)
    current = tg.draft_from_state(await state.get_data())
    assert current.reference_video_urls == ["", "https://owned.test/style.mp4"]
    with pytest.raises(ValueError):
        tg.validate_wan3_draft(current)


@pytest.mark.asyncio
async def test_owner_recipe_facade_restores_raw_recipe(monkeypatch):
    state = FakeState()
    recipe = {"scenario": "edit", "prompt": "Keep the camera; change jacket", "duration": -1,
              "reference_video_urls": ["https://owned.test/source.mp4"], "seed": 0, "audio": False}
    runtime = SimpleNamespace(owner_telegram_wan3_prime_recipe=AsyncMock(return_value=recipe))
    monkeypatch.setattr(tg, "_runtime", AsyncMock(return_value=runtime))
    await tg.restore_wan3_owner_recipe(FakeCallback("wan3_recipe:wan3_test"), state)
    current = tg.draft_from_state(await state.get_data())
    assert current.scenario == "edit"
    assert current.reference_video_urls == recipe["reference_video_urls"]
    assert current.prompt == recipe["prompt"] and current.duration == -1
    assert current.seed == 0 and current.audio is False


def test_wan_dashboard_back_uses_registered_model_callback():
    markup = tg.dashboard_keyboard(tg.Wan3PrimeDraft())
    back = next(button for row in markup.inline_keyboard for button in row if "К моделям" in button.text)
    assert back.callback_data == "video_change_model"


@pytest.mark.asyncio
async def test_callback_without_secret_never_polls_provider():
    actor = await user_actor()
    provider = Provider()
    provider.get_task_status = AsyncMock(return_value={"taskId": "provider_1", "state": "waiting"})
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, body())
    await lifecycle.launch(actor, body(), quote, "callback-test")
    response, status = await lifecycle.handle_callback({"data": {"taskId": "provider_1"}})
    assert status in {400, 403}
    assert response is None
    provider.get_task_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_wan_history_status_is_pending():
    from bot import database, miniapp

    actor = await user_actor()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=Provider())
    quote = await lifecycle.quote(actor, body())
    created = await lifecycle.launch(actor, body(), quote, "history-test")
    task = await database.get_task_by_id(created["task_id"])
    assert miniapp._public_task_status({"status": task.status, "task_id": task.task_id}) == "pending"


@pytest.mark.asyncio
async def test_completed_upload_still_counts_against_user_quota(monkeypatch, tmp_path):
    from bot.services.wan3_prime_media import Wan3PrimeValidationError
    from bot.services.wan3_prime_storage import wan3_prime_storage
    from tests.test_wan3_prime_storage import png_bytes

    monkeypatch.chdir(tmp_path)
    actor = await user_actor()
    image = png_bytes()
    monkeypatch.setenv("WAN3_UPLOAD_USER_QUOTA_BYTES", str(len(image) * 2 - 1))
    session = await wan3_prime_storage.init_upload(actor, kind="image", filename="one.png", size=len(image))
    await wan3_prime_storage.save_chunk(actor, upload_id=session["upload_id"], index=0, total=1, chunk=image)
    await wan3_prime_storage.complete_upload(actor, upload_id=session["upload_id"])
    with pytest.raises(Wan3PrimeValidationError, match="quota") as caught:
        await wan3_prime_storage.init_upload(actor, kind="image", filename="two.png", size=len(image))
    assert caught.value.status == 429


@pytest.mark.asyncio
async def test_interrupted_assembly_is_resumable(monkeypatch, tmp_path):
    from bot import database
    from bot.services.wan3_prime_storage import wan3_prime_storage
    from tests.test_wan3_prime_storage import png_bytes

    monkeypatch.chdir(tmp_path)
    actor = await user_actor()
    image = png_bytes()
    session = await wan3_prime_storage.init_upload(actor, kind="image", filename="resume.png", size=len(image))
    await wan3_prime_storage.save_chunk(actor, upload_id=session["upload_id"], index=0, total=1, chunk=image)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE wan3_prime_upload_sessions SET status = 'assembling', updated_at = '2000-01-01 00:00:00' WHERE upload_id = ?", (session["upload_id"],))
        await db.commit()
    saved = await wan3_prime_storage.complete_upload(actor, upload_id=session["upload_id"])
    replay = await wan3_prime_storage.complete_upload(actor, upload_id=session["upload_id"])
    assert saved["url"] == replay["url"]


@pytest.mark.asyncio
async def test_direct_link_recipe_checks_public_page_and_redirects(monkeypatch):
    from bot.services import wan3_prime_storage as storage
    from bot.services.wan3_prime_media import Wan3PrimeValidationError

    actor = await user_actor()
    fetch = AsyncMock(side_effect=Wan3PrimeValidationError("private redirect"))
    monkeypatch.setattr(storage, "fetch_public_asset", fetch)
    lifecycle = Wan3PrimeLifecycle(preset_manager=Prices(), transport=Provider())
    await lifecycle.init_schema()
    with pytest.raises(Wan3PrimeValidationError, match="private redirect"):
        await lifecycle.quote(actor, body(scenario="link", reference_link_urls=["https://example.com/page"]))
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_telegram_and_http_wan_reject_banned_users(monkeypatch):
    from bot import database, miniapp, wan3_prime_api
    from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycleError

    actor = await user_actor()
    user = await database.get_or_create_user(actor.telegram_id)
    monkeypatch.setattr(database, "is_user_banned", AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(actor.telegram_id, {"user": user})))
    request = SimpleNamespace(headers={}, app={})
    with pytest.raises(Wan3PrimeLifecycleError) as http_error:
        await wan3_prime_api._actor_from_request(request, {"init_data": "synthetic"})
    assert http_error.value.status == 403
    with pytest.raises(Wan3PrimeLifecycleError) as telegram_error:
        await wan3_prime_api._telegram_actor(actor.telegram_id)
    assert telegram_error.value.status == 403


@pytest.mark.asyncio
async def test_wan_canonical_task_has_partner_acceptance_proof():
    import json

    from bot import database

    actor = await user_actor()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=Provider())
    quote = await lifecycle.quote(actor, body())
    accepted = await lifecycle.launch(actor, body(), quote, "partner-proof")
    task = await database.get_task_by_id(accepted["task_id"])
    metadata = json.loads(task.request_data)
    assert metadata["partner_policy_version"] == 2
    assert metadata["partner_generation_accepted"] is True
    assert metadata["partner_invite_eligible"] is True


@pytest.mark.asyncio
async def test_lost_ack_callback_recovers_only_the_matching_provider_request(monkeypatch):
    import json
    from urllib.parse import parse_qs, urlparse

    from bot import database
    from bot.services.wan3_prime_media import WAN3_PROVIDER_MODEL

    monkeypatch.setenv("WAN3_CALLBACK_BASE_URL", "https://callback.example.test")
    actor = await user_actor()
    provider = Provider()
    provider.create_result = {"success": False, "error": "network_error"}
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, body())
    accepted = await lifecycle.launch(actor, body(), quote, "lost-ack")
    assert accepted["status"] == "unknown"
    params = parse_qs(urlparse(provider.callback_url).query)
    provider.statuses["real-task"] = {
        "taskId": "real-task", "model": WAN3_PROVIDER_MODEL, "state": "waiting",
        "param": json.dumps({"model": WAN3_PROVIDER_MODEL, "callBackUrl": provider.callback_url,
                             "input": json.dumps(provider.recipe.prepared_input)}),
    }
    await lifecycle.handle_callback({"data": {"taskId": "real-task", "model": WAN3_PROVIDER_MODEL}},
        internal_task_id=accepted["task_id"], nonce=params["nonce"][0])
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE wan3_prime_intents SET lease_until = NULL WHERE internal_task_id = ?", (accepted["task_id"],))
        await db.commit()
    await lifecycle.reconcile_once()
    result = await lifecycle.status(actor, accepted["task_id"])
    assert result["provider_task_id"] == "real-task"
    assert result["status"] == "submitted"
    assert provider.creates == 1


@pytest.mark.asyncio
async def test_operator_can_resolve_unknown_reserve_once_with_audit(monkeypatch):
    from bot import database
    from bot.config import config
    from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycleError
    from tests.test_wan3_prime_lifecycle import balance

    actor = await user_actor()
    provider = Provider()
    provider.create_result = {"success": False, "error": "network_error"}
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, body())
    submitted = await lifecycle.launch(actor, body(), quote, "manual-unknown")
    assert await balance(actor.user_id) == 90
    monkeypatch.setattr(config, "is_admin", lambda value: int(value) == 999999999)
    with pytest.raises(Wan3PrimeLifecycleError):
        await lifecycle.resolve_unknown_refund(submitted["task_id"], admin_telegram_id=111, reason="provider support confirmed no task")
    await lifecycle.resolve_unknown_refund(submitted["task_id"], admin_telegram_id=999999999, reason="provider support confirmed no task")
    await lifecycle.resolve_unknown_refund(submitted["task_id"], admin_telegram_id=999999999, reason="repeat button")
    assert await balance(actor.user_id) == 100
    assert provider.creates == 1
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        count = await (await db.execute("SELECT COUNT(*) FROM wan3_prime_operator_audit WHERE internal_task_id = ?", (submitted["task_id"],))).fetchone()
    assert count[0] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [500, 502, 503, 504])
async def test_gateway_create_failure_does_not_assume_provider_rejected(code):
    from tests.test_wan3_prime_lifecycle import balance
    actor = await user_actor()
    provider = Provider()
    provider.create_result = {'success': False, 'error': 'api_error', 'code': code}
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, body())
    first = await lifecycle.launch(actor, body(), quote, 'gateway-error')
    assert first['status'] == 'unknown'
    assert await balance(actor.user_id) == 90
    second = await lifecycle.launch(actor, body(), quote, 'gateway-error')
    assert second['task_id'] == first['task_id'] and provider.creates == 1


@pytest.mark.asyncio
async def test_legacy_launcher_cannot_bypass_wan_intent_and_confirmation(monkeypatch):
    from bot import miniapp
    actor = await user_actor()
    pricing = AsyncMock(side_effect=AssertionError('unsafe pricing boundary reached'))
    monkeypatch.setattr(miniapp, 'quote_video_for_actor', pricing)
    with pytest.raises(ValueError, match='Wan'):
        await miniapp._launch_video_generation_task(telegram_id=actor.telegram_id, user=actor,
            model='wan_3_prime', prompt='video', duration=5, aspect_ratio='9:16',
            generation_type='text', image_url=None, image_references=[], video_references=[])
    pricing.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_wan_generic_admin_refund_cannot_duplicate_lifecycle_refund(monkeypatch):
    from bot import internal_admin_operations as operations
    from tests.test_internal_admin_operations import (
        FakeConnection,
        command_request,
        operation_row,
    )
    request = command_request('/internal/admin/operations/7/refund', {
        'amount': 4, 'reason': 'operator verification', 'confirmation': 'REFUND 4'})
    connection = FakeConnection()
    monkeypatch.setattr(operations.db_backend, 'connect', lambda: connection)
    monkeypatch.setattr(operations, '_reserve_command', AsyncMock(return_value=None))
    monkeypatch.setattr(operations, '_fetch_operation_in_connection', AsyncMock(return_value=
        operation_row(task_id='wan3_pending', model='wan_3_prime', status='processing')))
    with pytest.raises(operations.CommandConflictError, match='Wan'):
        await operations.refund_operation_handler.__wrapped__(request)
    assert not any('UPDATE users' in sql for sql, _args in connection.calls)
