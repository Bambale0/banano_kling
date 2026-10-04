import json

import pytest

from bot import database, miniapp


@pytest.mark.asyncio
async def test_owner_can_authorize_hidden_repeat_independently_of_publication():
    author = await database.get_or_create_user(930001)
    viewer = await database.get_or_create_user(930002)
    face, outfit = "https://example.test/face.png", "https://example.test/outfit.png"
    await database.add_generation_task(author.id, author.telegram_id, "private-repeat-source", "image", "banana_pro", prompt="Image1 person Image2 outfit", request_data={"source_reference_images": [face, outfit]})
    await database.complete_video_task("private-repeat-source", "https://example.test/result.png")
    card = await database.share_to_feed("private-repeat-source", author.id, references_visible=False, repeat_reference_image_indices=[1])
    public = await database.get_feed_generation_card(card["id"], viewer_user_id=viewer.id)
    assert public["reference_images"] == []
    assert outfit not in json.dumps(public)
    payload = await database.get_generation_task_payload(card["id"])
    assert miniapp._selected_private_repeat_references(payload) == [outfit]
    await database.share_to_feed("private-repeat-source", author.id, references_visible=False, repeat_reference_image_indices=[])
    revoked = await database.get_generation_task_payload(card["id"])
    assert miniapp._selected_private_repeat_references(revoked) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["feed", "profile"])
async def test_permission_defaults_and_owner_only_revocation(scope):
    from bot.handlers import publication_scope_compat as publication
    author = await database.get_or_create_user(930011)
    stranger = await database.get_or_create_user(930012)
    ref = "https://example.test/private-outfit.png"
    await database.add_generation_task(author.id, author.telegram_id, "grant", "image", "banana_pro", request_data={"source_reference_images": [ref]})
    await database.complete_video_task("grant", "https://example.test/result.png")
    card = await database.share_to_feed("grant", author.id, publication_scope=scope, references_visible=False, reference_image_indices=[0])
    legacy = await database.get_generation_task_payload(card["id"])
    assert miniapp._selected_private_repeat_references(legacy) == []
    assert await database.share_to_feed("grant", stranger.id, repeat_reference_image_indices=[0]) is None
    await database.share_to_feed("grant", author.id, publication_scope=scope, repeat_reference_image_indices=[0])
    payload = await database.get_generation_task_payload(card["id"])
    assert miniapp._selected_private_repeat_references(payload) == [ref]
    if scope == "feed":
        await publication.remove_from_feed_scoped(card["id"], author.id)
        assert miniapp._selected_private_repeat_references(await database.get_generation_task_payload(card["id"])) == [ref]
    await publication.remove_publication(card["id"], author.id)
    revoked = await database.get_generation_task_payload(card["id"])
    assert miniapp._selected_private_repeat_references(revoked) == []
    assert database.generation_repeat_reference_selection(revoked) == []


@pytest.mark.parametrize("grant", [None, "broken", {}, {"images": "bad"}, {"images": [None]}, {"images": []}])
def test_legacy_or_malformed_permission_never_authorizes(grant):
    payload = {"type": "image", "status": "completed", "is_public_feed": True, "feed_repeat_reference_selection": grant,
        "feed_reference_selection": {"images": ["https://example.test/private.png"]},
        "request_data": {"source_reference_images": ["https://example.test/private.png"]}}
    assert miniapp._selected_private_repeat_references(payload) == []


@pytest.mark.parametrize("change", [{"source_feed_gen_id": 12}, {"action_type": "remix"}, {"status": "failed"}, {"type": "video"}, {"is_public_feed": False}])
def test_child_or_unavailable_source_cannot_authorize(change):
    ref = "https://example.test/private.png"
    payload = {"type": "image", "status": "completed", "is_public_feed": True,
        "feed_repeat_reference_selection": {"images": [ref]}, "request_data": {"source_reference_images": [ref]}, **change}
    assert miniapp._selected_private_repeat_references(payload) == []


def test_private_merge_preserves_numbered_image_slots_and_rejects_missing_replacement():
    face, outfit, background, viewer = [f"https://example.test/{name}.png" for name in ("face", "outfit", "background", "viewer")]
    payload = {"type": "image", "status": "completed", "is_public_feed": True,
        "feed_repeat_reference_selection": {"images": [face, background]}, "request_data": {"source_reference_images": [face, outfit, background]}}
    assert miniapp._merge_private_repeat_references(payload, [viewer]) == [face, viewer, background]
    with pytest.raises(ValueError, match="порядок"):
        miniapp._merge_private_repeat_references(payload, [])
    payload["request_data"]["source_reference_images"] = [face, outfit]
    with pytest.raises(ValueError, match="недоступны"):
        miniapp._merge_private_repeat_references(payload, [viewer])


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["remix", "generate"])
@pytest.mark.parametrize("published", [False, True])
async def test_hidden_grant_used_only_in_provider_payload(monkeypatch, endpoint, published, caplog):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    face, outfit, viewer = [f"https://example.test/{name}.png" for name in ("hidden-face", "secret-outfit", "viewer")]
    card = {"id": 42, "gen_type": "image", "is_mine": False, "model": "banana_pro", "reference_images": [outfit] if published else [], "feed_references_visible": published, "references_hidden": not published}
    payload = {"type": "image", "status": "completed", "prompt": "Image1 person Image2 outfit", "is_public_feed": True,
        "feed_references_visible": published, "feed_reference_selection": {"images": [outfit]},
        "feed_repeat_reference_selection": {"images": [outfit]}, "request_data": {"source_reference_images": [face, outfit]}}
    body = {"init_data": "signed", "gen_id": 42, "source_feed_gen_id": 42, "reference_images": [viewer, face, outfit]}
    launch = AsyncMock(return_value={"status": "failed"})
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value=body))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(123, {"user": SimpleNamespace(id=7, credits=100)})))
    monkeypatch.setattr(miniapp, "_get_feed_remix_source_card", AsyncMock(return_value=card))
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", AsyncMock(return_value=card))
    monkeypatch.setattr(miniapp, "get_generation_task_payload", AsyncMock(return_value=payload))
    monkeypatch.setattr(miniapp, "missing_local_upload_sources", lambda _refs: [])
    monkeypatch.setattr(miniapp, "touch_saved_references", AsyncMock())
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _id: True)
    monkeypatch.setattr(miniapp, "_start_image_generation_task_lazy", launch)
    request = SimpleNamespace(app={}, json=AsyncMock(return_value=body))
    response = await (miniapp.miniapp_feed_remix if endpoint == "remix" else miniapp.miniapp_generate_image)(request)
    assert response.status == 500
    assert launch.await_args.kwargs["reference_images"] == [viewer, outfit]
    assert launch.await_args.kwargs["private_repeat_reference_images"] == [outfit]
    assert outfit not in response.text and face not in response.text
    assert outfit not in caplog.text and face not in caplog.text
    # Foreign source refs stay server-side even when the author also chose to
    # display them publicly; only the viewer's own upload enters their library.
    assert miniapp.touch_saved_references.await_args.args[1] == [viewer]


@pytest.mark.asyncio
async def test_owner_detail_returns_only_indices_for_grant(monkeypatch):
    author = await database.get_or_create_user(930021)
    face, outfit = "https://example.test/face.png", "https://example.test/outfit.png"
    await database.add_generation_task(author.id, author.telegram_id, "owner-detail", "image", "banana_pro", request_data={"source_reference_images": [face, outfit]})
    await database.complete_video_task("owner-detail", "https://example.test/result.png")
    await database.share_to_feed("owner-detail", author.id, repeat_reference_image_indices=[1])
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    detail = await miniapp._fetch_task_detail(author.telegram_id, "owner-detail")
    assert detail["feed_repeat_reference_selection"] == {"images": [1]}


@pytest.mark.asyncio
@pytest.mark.parametrize("indices", [[True], [-1], [99], ["0"]])
async def test_invalid_permission_indices_are_rejected(indices):
    author = await database.get_or_create_user(930031)
    await database.add_generation_task(author.id, author.telegram_id, "invalid-grant", "image", "banana_pro", request_data={"source_reference_images": ["https://example.test/ref.png"]})
    await database.complete_video_task("invalid-grant", "https://example.test/result.png")
    with pytest.raises(ValueError):
        await database.share_to_feed("invalid-grant", author.id, repeat_reference_image_indices=indices)
    payload = await database.get_generation_task_payload("invalid-grant")
    assert database.generation_repeat_reference_selection(payload) == []
    assert not payload["is_public_feed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_name", ["_retry_transient_kie_image_failure", "_retry_nexus_banana_image_failure", "_retry_transient_wan_timeout_failure"])
async def test_image_auto_retry_rechecks_revoked_permission(monkeypatch, retry_name):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot import main
    from bot.handlers import generation
    validate = AsyncMock(return_value=False)
    monkeypatch.setattr(generation, "validate_private_repeat_reference_access", validate)
    task = SimpleNamespace(type="image", source_feed_gen_id=42, request_data=json.dumps({"private_repeat_reference_images": ["https://example.test/secret.png"]}))
    assert await getattr(main, retry_name)(task, "failed-task") is None
    assert validate.await_args.kwargs == {"source_feed_gen_id": 42, "private_reference_images": ["https://example.test/secret.png"]}


@pytest.mark.asyncio
async def test_private_snapshot_and_grant_redacted_from_history_bootstrap(monkeypatch):
    from unittest.mock import AsyncMock

    from bot import trend_task_privacy
    secret = "https://example.test/secret-outfit.png"
    monkeypatch.setattr(trend_task_privacy, "_protected_task_ids", AsyncMock(return_value={"child"}))
    task = {"task_id": "child", "feed_repeat_reference_selection": {"images": [secret]}, "request_data": {"private_repeat_reference_images": [secret], "source_reference_images": [secret]}}
    clean = await trend_task_privacy.sanitize_task_api_payload({"task": task, "recent_tasks": [task]})
    assert secret not in json.dumps(clean)
    assert "feed_repeat_reference_selection" not in clean["task"]
    assert "private_repeat_reference_images" not in clean["task"]["request_data"]


@pytest.mark.asyncio
async def test_legacy_schema_migration_does_not_grant_private_reuse():
    from bot import db as db_backend
    author = await database.get_or_create_user(930041)
    await database.add_generation_task(author.id, author.telegram_id, "legacy-grant", "image", "banana_pro", request_data={"source_reference_images": ["https://example.test/old.png"]})
    await database.complete_video_task("legacy-grant", "https://example.test/result.png")
    await database.share_to_feed("legacy-grant", author.id, references_visible=False, reference_image_indices=[0])
    async with db_backend.connect(database.DATABASE_PATH) as connection:
        await connection.execute("ALTER TABLE generation_tasks DROP COLUMN feed_repeat_reference_selection")
        await connection.commit()
    await database.init_db()
    payload = await database.get_generation_task_payload("legacy-grant")
    assert payload["feed_repeat_reference_selection"] is None
    assert payload["feed_reference_selection"] is not None
    assert miniapp._selected_private_repeat_references(payload) == []


def test_deleted_private_source_is_not_silently_omitted(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STATIC_LOCAL_HOSTS", "example.test")
    path = tmp_path / "static/uploads/refs/image/930051/synthetic.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"synthetic")
    ref = "https://example.test/uploads/refs/image/930051/synthetic.png"
    payload = {"type": "image", "status": "completed", "is_public_feed": True,
        "feed_repeat_reference_selection": {"images": [ref]}, "request_data": {"source_reference_images": [ref]}}
    assert miniapp._selected_private_repeat_references(payload) == [ref]
    path.unlink()
    assert miniapp._selected_private_repeat_references(payload) == []
    with pytest.raises(ValueError, match="недоступны"):
        miniapp._merge_private_repeat_references(payload, ["https://example.test/user.png"])


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["profile", "feed"])
async def test_installed_publication_api_preserves_explicit_grant(monkeypatch, scope):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot.handlers import publication_scope_compat as publication
    author = await database.get_or_create_user(930061)
    ref = "https://example.test/private-api-ref.png"
    await database.add_generation_task(author.id, author.telegram_id, "api-grant", "image", "banana_pro", request_data={"source_reference_images": [ref]})
    await database.complete_video_task("api-grant", "https://example.test/result.png")
    body = {"task_id": "api-grant", "publication_scope": scope, "references_visible": False, "repeat_reference_image_indices": [0]}
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value=body))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(author.telegram_id, {"user": author})))
    monkeypatch.setattr(miniapp, "miniapp_generation_share", miniapp.miniapp_generation_share)
    publication._patch_miniapp_module(miniapp)
    request = SimpleNamespace(app={"bot": SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="testbot")))})
    response = await miniapp.miniapp_generation_share(request)
    assert response.status == 200
    assert ref not in response.text
    payload = await database.get_generation_task_payload("api-grant")
    assert miniapp._selected_private_repeat_references(payload) == [ref]
    task = await database.get_task_by_id("api-grant")
    assert task.is_profile_visible is True
    assert database.generation_repeat_reference_selection(task) == [ref]
    body["repeat_reference_image_indices"] = []
    response = await miniapp.miniapp_generation_share(request)
    assert response.status == 200
    assert miniapp._selected_private_repeat_references(await database.get_generation_task_payload("api-grant")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["remix", "generate"])
async def test_miniapp_owner_child_cannot_launder_hidden_inputs(monkeypatch, endpoint):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    secret = "https://example.test/secret-child.png"
    body = {"gen_id": 42, "source_feed_gen_id": 42, "reference_images": [secret]}
    card = {"id": 42, "gen_type": "image", "is_mine": True, "references_hidden": True, "publication_scope": "profile"}
    payload = {"source_feed_gen_id": 12, "prompt": "recipe", "feed_reference_selection": {"images": [secret]}, "request_data": {"source_reference_images": [secret], "private_repeat_reference_images": [secret]}}
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value=body))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(123, {"user": SimpleNamespace(id=7)})))
    monkeypatch.setattr(miniapp, "_get_feed_remix_source_card", AsyncMock(return_value=card))
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", AsyncMock(return_value=card))
    monkeypatch.setattr(miniapp, "get_generation_task_payload", AsyncMock(return_value=payload))
    launch = AsyncMock()
    monkeypatch.setattr(miniapp, "_start_image_generation_task_lazy", launch)
    response = await (miniapp.miniapp_feed_remix if endpoint == "remix" else miniapp.miniapp_generate_image)(SimpleNamespace(app={}, json=AsyncMock(return_value=body)))
    assert response.status == 403
    assert secret not in response.text
    launch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["remix", "generate"])
async def test_image_api_unexpected_errors_never_echo_recipe_or_urls(monkeypatch, endpoint, caplog):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    private = "https://example.test/private-echo.png secret recipe"
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(side_effect=RuntimeError(private)))
    response = await (miniapp.miniapp_feed_remix if endpoint == "remix" else miniapp.miniapp_generate_image)(SimpleNamespace(app={}, json=AsyncMock(side_effect=RuntimeError(private))))
    assert response.status == 500
    assert private not in response.text and private not in caplog.text
    assert "private-echo" not in response.text and "private-echo" not in caplog.text


@pytest.mark.parametrize("error,status", [(PermissionError("https://example.test/private.png"),403), (ValueError("Invalid Telegram signature"),401), (ValueError("Invalid boundary https://example.test/private.png"),400), (TimeoutError("https://example.test/private.png"),408), (ConnectionResetError("https://example.test/private.png"),499)])
def test_private_image_errors_preserve_expected_status_without_raw_details(error, status, caplog):
    response = miniapp._private_image_error_response(error, log_message="Synthetic image failure")
    assert response.status == status
    assert "private.png" not in response.text and "private.png" not in caplog.text


def test_user_error_redacts_encoded_media_url():
    from bot.utils.user_facing_errors import make_user_friendly_generation_error
    assert "private-marker.png" not in make_user_friendly_generation_error("failed: https%3A%2F%2Fexample.test%2Fprivate-marker.png")


@pytest.mark.asyncio
async def test_legacy_retry_without_marker_requires_live_root_permission(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot import main
    from bot.handlers import generation
    ref = "https://example.test/legacy-hidden.png"
    root = {"type": "image", "status": "completed", "is_public_feed": True, "feed_references_visible": False, "request_data": {"source_reference_images": [ref]}}
    monkeypatch.setattr(generation, "get_generation_task_payload", AsyncMock(return_value=root))
    task = SimpleNamespace(type="image", user_id=7, source_feed_gen_id=42, request_data=json.dumps({"source_reference_images": [ref], "reference_images": [ref]}))
    assert not await main._image_retry_private_references_allowed(task, json.loads(task.request_data))
    root["feed_repeat_reference_selection"] = {"images": [ref]}
    assert await main._image_retry_private_references_allowed(task, json.loads(task.request_data))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get_error", "get_exception", "post_exception"])
async def test_shared_kie_adapter_never_logs_private_urls(monkeypatch, caplog, operation):
    import importlib
    module = importlib.import_module("bot.services.kling_service")
    secret = "https://example.test/secret-shared-adapter.png"
    class Response:
        status = 400
        async def __aenter__(self):
            if operation.endswith("exception"):
                raise RuntimeError("failed to fetch " + secret)
            return self
        async def __aexit__(self, *_args):
            return False
        async def text(self):
            return json.dumps({"error": "failed to fetch " + secret, "input": {"image_urls": [secret]}})
    class Session:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return False
        def get(self, *_args, **_kwargs):
            return Response()
        def post(self, *_args, **_kwargs):
            return Response()
    monkeypatch.setattr(module.aiohttp, "ClientSession", lambda **_kwargs: Session())
    service = module.KlingService(kie_key="synthetic-test-only")
    result = await service._kie_post("/synthetic", {"input": {"image_urls": [secret]}}) if operation == "post_exception" else await service._kie_get("/synthetic")
    assert secret not in caplog.text
    assert secret not in json.dumps(result)
