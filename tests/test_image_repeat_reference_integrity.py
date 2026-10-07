from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, miniapp


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["remix", "generate"])
@pytest.mark.parametrize("model", ["banana_pro", "banana_2"])
@pytest.mark.parametrize("case", ["all_fixed", "replacement", "missing_replacement", "unavailable", "revoked", "owner_selected", "owner_selected_gap"])
async def test_image_repeat_preserves_authorized_recipe_before_billing(monkeypatch, endpoint, model, case):
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
    if case in {"missing_replacement", "unavailable", "owner_selected_gap"}:
        assert response.status == 400
        debit.assert_not_awaited()
        launch.assert_not_awaited()
    else:
        assert response.status == 500  # mocked provider failure, never a real launch
        expected = [fixed] if all_fixed else [own] if case == "revoked" else [own, fixed]
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
