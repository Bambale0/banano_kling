from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, miniapp, repeat_personalization


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["remix", "generate"])
@pytest.mark.parametrize("invalid_values", [False, True])
async def test_admin_image_personalization_keeps_base_and_authorized_reference(
    monkeypatch, endpoint, invalid_values,
):
    fixed = "https://example.test/fixed-cake.png"
    source_prompt = "Cinematic scene, blue coat, stable camera and lighting"
    card = {
        "id": 42, "gen_type": "image", "is_mine": False, "model": "banana_pro",
        "publication_scope": "feed", "references_hidden": True,
    }
    source = {
        "type": "image", "status": "completed", "is_public_feed": True,
        "prompt": source_prompt,
        "feed_repeat_reference_selection": {"images": [fixed]},
        "request_data": {"source_reference_images": [fixed]},
    }
    body = {
        "init_data": "signed", "gen_id": 42, "source_feed_gen_id": 42,
        "img_service": "banana_pro", "reference_images": [],
        "prompt": "Keep the smile",
        "repeat_user_values": {} if invalid_values else {"clothes": "red dress"},
    }
    monkeypatch.setenv(repeat_personalization.FEATURE_FLAG, "1")
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value=body))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(123, {"user": SimpleNamespace(id=7, credits=100)})))
    monkeypatch.setattr(miniapp, "_get_feed_remix_source_card", AsyncMock(return_value=card))
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", AsyncMock(return_value=card))
    monkeypatch.setattr(miniapp, "get_generation_task_payload", AsyncMock(return_value=source))
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _id: True)
    monkeypatch.setattr(miniapp, "missing_local_upload_sources", lambda _refs: [])
    monkeypatch.setattr(miniapp, "touch_saved_references", AsyncMock())
    monkeypatch.setattr(miniapp, "_resolve_image_unit_cost", lambda *_args: 1)
    launch = AsyncMock(return_value={"status": "failed"})
    monkeypatch.setattr(miniapp, "_start_image_generation_task_lazy", launch)
    fields = repeat_personalization.normalize_repeat_fields(
        [{"key": "clothes", "label": "Одежда", "original_value": "blue coat"}],
        prompt=source_prompt,
    )
    await repeat_personalization.save_repeat_fields(42, fields, actor_telegram_id=123)

    request = SimpleNamespace(app={}, json=AsyncMock(return_value=body))
    response = await (miniapp.miniapp_feed_remix if endpoint == "remix" else miniapp.miniapp_generate_image)(request)

    if invalid_values:
        assert response.status == 400, response.text
        launch.assert_not_awaited()
        return
    assert response.status == 500
    provider_prompt = launch.await_args.kwargs["prompt"]
    assert "Cinematic scene" in provider_prompt
    assert "stable camera and lighting" in provider_prompt
    assert "red dress" in provider_prompt
    assert "blue coat" not in provider_prompt
    assert "Keep the smile" in provider_prompt
    assert launch.await_args.kwargs["reference_images"] == [fixed]


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["remix", "generate"])
@pytest.mark.parametrize("model", ["banana_pro", "banana_2"])
@pytest.mark.parametrize("derived_source", [False, True])
@pytest.mark.parametrize("case", ["all_fixed", "replacement", "missing_replacement", "unavailable", "revoked", "owner_selected", "owner_selected_gap"])
async def test_image_repeat_preserves_authorized_recipe_before_billing(monkeypatch, endpoint, model, derived_source, case):
    fixed = "https://example.test/fixed-cake.png"
    original = "https://example.test/original-person.png"
    own = "https://example.test/viewer-person.png"
    all_fixed = case == "all_fixed"
    source_refs = [fixed] if all_fixed else [original, fixed]
    if case == "owner_selected_gap":
        source_refs = [original, "https://example.test/second-person.png", fixed]
    submitted = [] if case in {"all_fixed", "missing_replacement"} else [own]
    grant = [] if case in {"revoked", "owner_selected", "owner_selected_gap"} else [fixed]
    card = {"id": 42, "gen_type": "image", "is_mine": case in {"owner_selected", "owner_selected_gap"}, "model": model,
            "publication_scope": "profile", "references_hidden": True, "feed_references_visible": False}
    source = {"type": "image", "status": "completed", "is_public_feed": True, "prompt": "Synthetic numbered recipe",
              "source_feed_gen_id": 99 if derived_source else None,
              "action_type": "remix" if derived_source else None,
              "feed_references_visible": False, "feed_reference_selection": {"images": [fixed], "videos": []},
              "feed_repeat_reference_selection": {"images": grant}, "request_data": {"source_reference_images": source_refs}}
    body = {"init_data": "signed", "gen_id": 42, "source_feed_gen_id": 42, "img_service": model, "reference_images": submitted}
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value=body))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(123, {"user": SimpleNamespace(id=7, credits=100)})))
    monkeypatch.setattr(miniapp, "_get_feed_remix_source_card", AsyncMock(return_value=card))
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", AsyncMock(return_value=card))
    monkeypatch.setattr(miniapp, "get_generation_task_payload", AsyncMock(return_value=source))
    monkeypatch.setattr(database, "_is_feed_result_url_available", lambda _task, url: not (case == "unavailable" and url == fixed))
    monkeypatch.setattr(miniapp, "missing_local_upload_sources", lambda _refs: [])
    monkeypatch.setattr(miniapp, "touch_saved_references", AsyncMock())
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _id: False)
    monkeypatch.setattr(miniapp, "_resolve_image_unit_cost", lambda *_args: 1)
    monkeypatch.setattr(miniapp, "check_can_afford", AsyncMock(return_value=True))
    debit, refund = AsyncMock(return_value=True), AsyncMock()
    monkeypatch.setattr(miniapp, "deduct_credits", debit)
    monkeypatch.setattr(miniapp, "add_credits", refund)
    launch = AsyncMock(return_value={"status": "failed"})
    monkeypatch.setattr(miniapp, "_start_image_generation_task_lazy", launch)
    request = SimpleNamespace(app={}, json=AsyncMock(return_value=body))
    response = await (miniapp.miniapp_feed_remix if endpoint == "remix" else miniapp.miniapp_generate_image)(request)
    assert fixed not in response.text and original not in response.text
    private_owner = derived_source and case in {"owner_selected", "owner_selected_gap"}
    if case in {"missing_replacement", "unavailable"} or (case == "owner_selected_gap" and not private_owner):
        assert response.status == 400
        debit.assert_not_awaited()
        launch.assert_not_awaited()
    else:
        assert response.status == 500  # mocked provider failure, never a real launch
        expected = [fixed] if all_fixed else [own] if case == "revoked" or private_owner else [own, fixed]
        assert launch.await_args.kwargs["reference_images"] == expected
        assert launch.await_args.kwargs["private_repeat_reference_images"] == grant
        debit.assert_awaited_once()
        refund.assert_awaited_once()
        if not card["is_mine"] and miniapp.touch_saved_references.await_args:
            assert fixed not in miniapp.touch_saved_references.await_args.args[1]


@pytest.mark.parametrize("suffix", ["", "?cache=1", "#preview"])
def test_foreign_local_alias_is_never_a_new_user_reference(suffix):
    legacy = "https://tanyapi.chillcreative.ru/uploads/synthetic-private.png"
    alias = "https://tanyapp.xn--e1aikcel5c5a.online/uploads/synthetic-private.png" + suffix
    payload = {"request_data": {"source_reference_images": [legacy]}}
    assert miniapp._filter_foreign_feed_source_references(
        {"is_mine": False}, payload, [alias], viewer_telegram_id=123,
    ) == []


def test_private_grant_accepts_only_known_local_alias_identity(monkeypatch):
    legacy = "https://tanyapi.chillcreative.ru/uploads/synthetic-fixed.png"
    canonical = "https://tanyapp.xn--e1aikcel5c5a.online/uploads/synthetic-fixed.png"
    foreign = "https://external.test/uploads/synthetic-fixed.png"
    payload = {"type": "image", "status": "completed", "is_public_feed": True,
        "feed_repeat_reference_selection": {"images": [legacy]},
        "request_data": {"source_reference_images": [canonical]}}
    monkeypatch.setattr(database, "_is_feed_result_url_available", lambda *_args: True)
    assert miniapp._merge_private_repeat_references(payload, []) == [canonical]
    payload["request_data"]["source_reference_images"] = [foreign]
    with pytest.raises(ValueError, match="недоступны"):
        miniapp._merge_private_repeat_references(payload, [])


@pytest.mark.asyncio
@pytest.mark.parametrize("granted", [True, False])
async def test_provider_permission_recheck_uses_local_identity_without_resurrecting_grants(monkeypatch, granted):
    from bot.handlers import generation
    legacy = "https://tanyapi.chillcreative.ru/uploads/synthetic-fixed.png"
    canonical = "https://tanyapp.xn--e1aikcel5c5a.online/uploads/synthetic-fixed.png"
    root = {"type": "image", "status": "completed", "is_public_feed": True,
        "feed_repeat_reference_selection": {"images": [legacy] if granted else []},
        "request_data": {"source_reference_images": [legacy]}}
    monkeypatch.setattr(generation, "get_generation_task_payload", AsyncMock(return_value=root))
    monkeypatch.setattr(database, "_is_feed_result_url_available", lambda *_args: True)
    assert await generation.validate_private_repeat_reference_access(
        source_feed_gen_id=42, private_reference_images=[canonical],
    ) is granted
    assert not await generation.validate_private_repeat_reference_access(
        source_feed_gen_id=42, private_reference_images=["https://external.test/uploads/synthetic-fixed.png"],
    )


def test_own_selected_fixed_alias_preserves_the_stored_source_slot():
    legacy = "https://tanyapi.chillcreative.ru/uploads/synthetic-fixed.png"
    canonical = "https://tanyapp.xn--e1aikcel5c5a.online/uploads/synthetic-fixed.png"
    own = "https://example.test/new-person.png"
    payload = {"feed_reference_selection": {"images": [legacy]},
        "request_data": {"source_reference_images": ["https://example.test/old-person.png", canonical]}}
    references, retained = miniapp._merge_remix_image_references({"is_mine": True}, payload, [own])
    assert references == [own, canonical]
    assert retained == 1


@pytest.mark.asyncio
async def test_published_image_derivative_is_current_private_reference_authority(monkeypatch):
    from bot.handlers import generation

    reference = "https://example.test/current-published-author.png"
    current = {
        "id": 84, "type": "image", "status": "completed",
        "action_type": "remix", "source_feed_gen_id": 42,
        "is_public_feed": True, "is_profile_visible": True,
        "feed_repeat_reference_selection": {"images": [reference]},
        "request_data": {"source_reference_images": [reference]},
    }
    monkeypatch.setattr(generation, "get_generation_task_payload",
                        AsyncMock(side_effect=lambda source_id: dict(current) if source_id == 84 else None))
    monkeypatch.setattr(database, "_is_feed_result_url_available", lambda *_args: True)
    assert await generation.validate_private_repeat_reference_access(
        source_feed_gen_id=84, private_reference_images=[reference])
    current["is_public_feed"] = False
    current["is_profile_visible"] = False
    assert not await generation.validate_private_repeat_reference_access(
        source_feed_gen_id=84, private_reference_images=[reference])


@pytest.mark.asyncio
async def test_new_photo_generation_rechecks_clicked_post_not_lineage_root(monkeypatch):
    from bot.handlers import generation

    retained = "https://example.test/current-published-author.png"
    verify = AsyncMock(return_value=False)
    monkeypatch.setattr(generation, "validate_private_repeat_reference_access", verify)
    # The guard runs before any provider call or task persistence; return
    # False deliberately to observe the exact source ID being verified.
    result = await generation._start_image_generation_task(
        user=SimpleNamespace(id=3), telegram_id=883, img_service="banana_pro",
        prompt="Keep the jacket", img_ratio="1:1", reference_images=[retained],
        unit_cost=1, private_repeat_reference_images=[retained],
        source_feed_gen_id=42, private_repeat_permission_source_id=84,
        parent_generation_id=84, action_type="remix")
    assert result["status"] == "failed"
    verify.assert_awaited_once_with(source_feed_gen_id=84, private_reference_images=[retained])
