"""Creator prices at the real Seedance public entry points; no paid provider calls."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import creator_tariff, creator_tariff_membership, miniapp
from bot.handlers import seedance_25_public_release as public


@pytest.fixture
def launch_env(monkeypatch):
    # Synthetic rates are deliberately local to each test, never runtime data.
    prices = {
        "costs_reference": {"video_models": {
            "seedance_2_5": {"duration_min": 4, "duration_max": 30,
                             "quality_costs": {"480p": 3, "720p": 4}},
        }},
        "creator_tariff": {"enabled": True, "video_models": {
            model: {"quality_costs": {quality: 2 for quality in qualities}}
            for model, qualities in creator_tariff._required_qualities().items()
        }},
    }
    monkeypatch.setattr(public.preset_manager, "_price_config", prices)
    monkeypatch.setattr(public.config, "is_admin", lambda _id: False)
    membership = AsyncMock(return_value=True)
    monkeypatch.setattr(creator_tariff_membership, "get_creator_tariff_membership", membership)
    user = SimpleNamespace(id=1, credits=1000)
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(123, {"user": user})))
    for module in (miniapp, public.generation_module):
        monkeypatch.setattr(module, "get_or_create_user", AsyncMock(return_value=user))
        monkeypatch.setattr(module, "check_can_afford", AsyncMock(return_value=True))
        monkeypatch.setattr(module, "deduct_credits", AsyncMock(return_value=True))
        monkeypatch.setattr(module, "add_credits", AsyncMock(return_value=True))
    monkeypatch.setattr(public.fullstack, "_validate_seedance_sources", AsyncMock())
    monkeypatch.setattr(public.fullstack, "_validate_local_source", AsyncMock(return_value=12.2))
    monkeypatch.setattr(public, "_identity_local_path", lambda *_args: "owned-upload")
    monkeypatch.setattr(public, "_launch_provider", AsyncMock(return_value={"task_id": "creator-seedance"}))
    monkeypatch.setattr(public.generation_module, "add_generation_task", AsyncMock(return_value=True))
    return SimpleNamespace(prices=prices, membership=membership, request=SimpleNamespace(app={}), user=user)


def body(**changes):
    return {"v_model": "seedance_2_5", "seedance25_scenario": "text", "prompt": "Camera pans",
            "v_duration": 5, "seedance25_resolution": "720p", **changes}


def telegram_state(data):
    state = SimpleNamespace(get_data=AsyncMock(side_effect=lambda: dict(data)),
                            set_state=AsyncMock(), clear=AsyncMock())
    async def update(**changes):
        data.update(changes)
    state.update_data = AsyncMock(side_effect=update)
    return state


def message(actor_id=123):
    msg = SimpleNamespace(from_user=SimpleNamespace(id=actor_id), answer=AsyncMock())
    msg.answer.return_value = SimpleNamespace(delete=AsyncMock())
    return msg


@pytest.mark.parametrize("member,reference_count,expected", [
    (True, 0, 10), (True, 1, 20), (True, 2, 20),
    (False, 0, 20), (False, 1, 40), (False, 2, 40),
])
async def test_miniapp_prices_authenticated_actor_and_references_once(launch_env, member, reference_count, expected):
    launch_env.membership.return_value = member
    data = body(
        seedance25_scenario="multimodal" if reference_count else "text",
        v_reference_videos=[f"https://example.test/{index}.mp4" for index in range(reference_count)],
        tariff="admin", creator_tariff=True, billing_quote={"charge_cost": 0},
    )
    response = await public._public_miniapp_generate(launch_env.request, data)
    assert response.status == 200
    assert json.loads(response.body)["cost"] == expected
    miniapp.deduct_credits.assert_awaited_once_with(123, expected)
    launch_env.membership.assert_awaited_once_with(123)
    record = public.generation_module.add_generation_task.await_args.kwargs
    assert record["cost"] == record["request_data"]["charged_cost"] == expected
    snapshot = record["request_data"]["billing_quote"]
    assert snapshot["cost"] == snapshot["charge_cost"] == expected
    assert snapshot["profile"] == ("creator" if member else "standard")
    assert snapshot["reference_multiplier"] == (2 if reference_count else 1)


async def test_inactive_scenario_references_cannot_inflate_screen_or_launch(launch_env):
    data = body(v_reference_videos=["https://example.test/stale.mp4"])
    msg, state = message(), telegram_state(data)
    await public._public_show_screen(msg, state, edit=False)
    assert "<code>10.0</code>🍌" in msg.answer.await_args.args[0]
    await public._public_message_launch(msg, state, data["prompt"])
    public.generation_module.deduct_credits.assert_awaited_once_with(123, 10)
    assert public._launch_provider.await_args.args[0]["video_urls"] == []


@pytest.mark.parametrize("surface", ["miniapp", "telegram"])
async def test_rejected_debit_never_launches_paid_provider(launch_env, surface):
    debit_module = miniapp if surface == "miniapp" else public.generation_module
    debit_module.deduct_credits.return_value = False
    if surface == "miniapp":
        response = await public._public_miniapp_generate(launch_env.request, body())
        assert response.status == 400
    else:
        msg = message()
        await public._public_message_launch(msg, telegram_state(body()), "Camera pans")
        assert "Не удалось списать" in msg.answer.await_args.args[0]
    public._launch_provider.assert_not_awaited()
    public.generation_module.add_generation_task.assert_not_awaited()
    debit_module.add_credits.assert_not_awaited()


@pytest.mark.parametrize("surface", ["miniapp", "telegram"])
async def test_immediate_failure_refunds_original_charge_after_role_and_price_change(launch_env, monkeypatch, surface):
    async def rejected(_payload):
        launch_env.prices["creator_tariff"]["video_models"]["seedance_2_5"]["quality_costs"]["720p"] = 9
        launch_env.membership.return_value = False
        monkeypatch.setattr(public.config, "is_admin", lambda _id: True)
        return {"error": "synthetic provider rejection"}
    public._launch_provider.side_effect = rejected
    if surface == "miniapp":
        response = await public._public_miniapp_generate(launch_env.request, body())
        assert response.status == 502
        credits = miniapp
    else:
        await public._public_message_launch(message(), telegram_state(body()), "Camera pans")
        credits = public.generation_module
    credits.deduct_credits.assert_awaited_once_with(123, 10)
    credits.add_credits.assert_awaited_once_with(123, 10)
    launch_env.membership.assert_awaited_once_with(123)


async def test_persisted_snapshot_survives_price_change_during_provider_call(launch_env):
    async def accepted(_payload):
        launch_env.prices["creator_tariff"]["video_models"]["seedance_2_5"]["quality_costs"]["720p"] = 9
        launch_env.membership.return_value = False
        return {"task_id": "creator-seedance"}
    public._launch_provider.side_effect = accepted
    response = await public._public_miniapp_generate(launch_env.request, body())
    assert response.status == 200
    record = public.generation_module.add_generation_task.await_args.kwargs
    assert record["cost"] == record["request_data"]["billing_quote"]["charge_cost"] == 10
    assert record["request_data"]["billing_quote"]["profile"] == "creator"
    launch_env.membership.assert_awaited_once_with(123)


@pytest.mark.parametrize("surface", ["miniapp", "telegram"])
async def test_admin_remains_free_with_standard_display_quote(launch_env, monkeypatch, surface):
    monkeypatch.setattr(public.config, "is_admin", lambda _id: True)
    if surface == "miniapp":
        response = await public._public_miniapp_generate(launch_env.request, body())
        assert json.loads(response.body)["cost"] == 20
    else:
        await public._public_message_launch(message(), telegram_state(body()), "Camera pans")
    miniapp.deduct_credits.assert_not_awaited()
    public.generation_module.deduct_credits.assert_not_awaited()
    record = public.generation_module.add_generation_task.await_args.kwargs
    assert record["cost"] == 0
    assert record["request_data"]["price_quote"] == 20
    assert record["request_data"]["admin_free"] is True
    assert record["request_data"]["billing_quote"]["profile"] == "admin"
    launch_env.membership.assert_not_awaited()


async def test_creator_identity_uses_measured_duration_and_quote_acknowledgement(launch_env):
    data = body(seedance25_scenario="multimodal", seedance25_identity_transfer=True,
                reference_images=["https://example.test/person.jpg"],
                v_reference_videos=["https://example.test/source.mp4"],
                seedance25_quote_only=True)
    response = await public._public_miniapp_generate(launch_env.request, data)
    displayed = json.loads(response.body)
    assert displayed["cost"] == 52  # ceil(12.2) * synthetic creator 2 * reference 2
    assert displayed["billing_duration"] == 13
    miniapp.deduct_credits.assert_not_awaited()
    data.update(seedance25_quote_only=False, seedance25_identity_quote=displayed["seedance25_identity_quote"])
    response = await public._public_miniapp_generate(launch_env.request, data)
    assert response.status == 200
    miniapp.deduct_credits.assert_awaited_once_with(123, 52)
    record = public.generation_module.add_generation_task.await_args.kwargs
    assert record["duration"] == -1
    assert record["request_data"]["billing_quote"]["duration"] == 13


async def test_telegram_identity_screen_uses_callback_actor_and_current_tariff(launch_env):
    data = body(seedance25_scenario="multimodal", seedance25_identity_transfer=True,
                reference_images=["https://example.test/person.jpg"],
                v_reference_videos=["https://example.test/source.mp4"])
    state, msg = telegram_state(data), message(actor_id=999)
    await public._public_show_screen(msg, state, edit=False, actor_id=123)
    assert data["seedance25_identity_quote"]["cost"] == 52
    await public._public_message_launch(msg, state, "Keep the dance", actor_id=123)
    public.generation_module.deduct_credits.assert_awaited_once_with(123, 52)
    assert all(call.args == (123,) for call in launch_env.membership.await_args_list)


async def test_membership_change_between_identity_quote_and_launch_requires_new_quote(launch_env):
    data = body(seedance25_scenario="multimodal", seedance25_identity_transfer=True,
                reference_images=["https://example.test/person.jpg"],
                v_reference_videos=["https://example.test/source.mp4"], seedance25_quote_only=True)
    displayed = json.loads((await public._public_miniapp_generate(launch_env.request, data)).body)
    launch_env.membership.return_value = False
    data.update(seedance25_quote_only=False, seedance25_identity_quote=displayed["seedance25_identity_quote"])
    response = await public._public_miniapp_generate(launch_env.request, data)
    assert response.status == 400
    miniapp.deduct_credits.assert_not_awaited()
    public._launch_provider.assert_not_awaited()


async def test_auto_editing_preserves_existing_five_second_estimate(launch_env, monkeypatch):
    monkeypatch.setattr(public.config, "is_admin", lambda _id: True)
    response = await public._public_miniapp_generate(launch_env.request, body(
        seedance25_scenario="multimodal", seedance25_video_editing=True,
        v_reference_videos=["https://example.test/source.mp4"], v_duration=20,
    ))
    assert response.status == 200
    assert json.loads(response.body)["cost"] == 40  # existing Auto 5 * retail 4 * 2
    record = public.generation_module.add_generation_task.await_args.kwargs
    assert record["duration"] == -1
    assert record["request_data"]["billing_quote"]["duration"] == 5


async def test_async_failure_refunds_snapshot_once_after_membership_changes(launch_env, monkeypatch):
    from bot import database
    user = await database.get_or_create_user(123)
    before = float(user.credits)
    await database.add_generation_task(user.id, 123, "creator-failed", "video", "no_preset_video",
        model="seedance_2_5", cost=10,
        request_data={"charged_cost": 10, "refund_on_failure": True,
                      "billing_quote": creator_tariff.resolve_video_quote("seedance_2_5", 5, "720p", tariff="creator").to_dict()})
    monkeypatch.setattr(public.config, "is_admin", lambda _id: True)
    launch_env.membership.return_value = False
    assert await public._claim_async_refund("creator-failed") == (123, 10)
    assert await public._claim_async_refund("creator-failed") is None
    assert float((await database.get_or_create_user(123)).credits) == before + 10


def test_both_telegram_model_keyboard_wrappers_preserve_creator_tariff(launch_env):
    from aiogram import types

    from bot.handlers import seedance_25_new_priority as priority
    seen = []
    def keyboard(current_model, user_id=None, *, tariff="standard"):
        seen.append((current_model, user_id, tariff))
        return types.InlineKeyboardMarkup(inline_keyboard=[])
    wrapped = priority._prioritize_video_keyboard(public._public_video_model_keyboard(keyboard))
    for profile, expected in (("creator", "2🍌/с"), ("standard", "4🍌/с")):
        markup = wrapped("seedance_2_5", user_id=123, tariff=profile)
        assert expected in markup.inline_keyboard[0][0].text
        assert seen[-1] == ("seedance_2_5", 123, profile)


@pytest.mark.parametrize("failure", ["telegram_delete", "telegram_success", "miniapp_refresh"])
async def test_postacceptance_ui_failure_keeps_charge_for_single_async_refund(launch_env, monkeypatch, failure):
    from bot import database
    user = await database.get_or_create_user(123)
    await database.add_credits(123, 100)
    before = float((await database.get_or_create_user(123)).credits)
    monkeypatch.setattr(public.generation_module, "add_generation_task", database.add_generation_task)
    credits_module = miniapp if failure == "miniapp_refresh" else public.generation_module
    monkeypatch.setattr(credits_module, "deduct_credits", database.deduct_credits)
    if failure == "miniapp_refresh":
        monkeypatch.setattr(miniapp, "get_or_create_user", AsyncMock(side_effect=RuntimeError("synthetic refresh failure")))
        response = await public._public_miniapp_generate(launch_env.request, body())
        assert response.status == 500
        assert json.loads(response.body)["code"] == "video_status_pending"
    else:
        msg = message()
        processing = SimpleNamespace(delete=AsyncMock())
        if failure == "telegram_delete":
            processing.delete.side_effect = RuntimeError("synthetic message deletion failure")
            msg.answer.return_value = processing
        else:
            msg.answer.side_effect = [processing, RuntimeError("synthetic success send failure"), None]
        await public._public_message_launch(msg, telegram_state(body()), "Camera pans")
    credits_module.add_credits.assert_not_awaited()
    record = await database.get_task_by_id("creator-seedance")
    request_data = json.loads(record.request_data)
    assert request_data["billing_quote"]["charge_cost"] == request_data["charged_cost"] == float(record.cost) == 10
    assert request_data["refund_on_failure"] is True
    assert float((await database.get_or_create_user(123)).credits) == before - 10
    launch_env.membership.return_value = False
    monkeypatch.setattr(public.config, "is_admin", lambda _id: True)
    assert await public._claim_async_refund("creator-seedance") == (123, 10)
    assert await public._claim_async_refund("creator-seedance") is None
    assert float((await database.get_or_create_user(123)).credits) == before
    assert user.id == launch_env.user.id


@pytest.mark.parametrize("surface", ["miniapp", "telegram"])
@pytest.mark.parametrize("refund_result", ["raise", "false"])
async def test_unconfirmed_immediate_refund_is_never_retried_or_reported_success(launch_env, surface, refund_result):
    public._launch_provider.return_value = {"error": "synthetic provider rejection"}
    credits_module = miniapp if surface == "miniapp" else public.generation_module
    if refund_result == "raise":
        credits_module.add_credits.side_effect = RuntimeError("synthetic unknown refund commit")
    else:
        credits_module.add_credits.return_value = False
    if surface == "miniapp":
        response = await public._public_miniapp_generate(launch_env.request, body())
        result = json.loads(response.body)
        assert result["code"] == "video_refund_pending"
        text = result["error"]
    else:
        msg = message()
        await public._public_message_launch(msg, telegram_state(body()), "Camera pans")
        text = msg.answer.await_args.args[0]
    assert "возвращено" not in text
    assert "Не удалось подтвердить возврат" in text
    credits_module.add_credits.assert_awaited_once_with(123, 10)


@pytest.mark.parametrize("failure", ["telegram_user_load", "telegram_persistence", "miniapp_persistence"])
async def test_acceptance_guard_is_set_before_first_database_operation(launch_env, monkeypatch, failure):
    if failure == "telegram_user_load":
        monkeypatch.setattr(public.generation_module, "get_or_create_user", AsyncMock(side_effect=RuntimeError("synthetic user lookup failure")))
    else:
        public.generation_module.add_generation_task.side_effect = RuntimeError("synthetic persistence failure")
    if failure == "miniapp_persistence":
        response = await public._public_miniapp_generate(launch_env.request, body())
        assert json.loads(response.body)["code"] == "video_status_pending"
    else:
        msg = message()
        await public._public_message_launch(msg, telegram_state(body()), "Camera pans")
        assert "Видео принято провайдером" in msg.answer.await_args.args[0]
    public._launch_provider.assert_awaited_once()
    miniapp.add_credits.assert_not_awaited()
    public.generation_module.add_credits.assert_not_awaited()
