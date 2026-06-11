import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from aiohttp.test_utils import make_mocked_request

from bot.config import config
from bot.tma_api import (
    _dashboard,
    _feature_catalog,
    handle_tma_app_bootstrap,
    handle_tma_app_generation,
    handle_tma_app_prompt_builder,
    handle_tma_admin_bootstrap,
    handle_tma_admin_payment_action,
    require_admin,
    validate_tma_init_data,
)


def _signed_init_data(bot_token: str, user: dict) -> str:
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "test-query",
        "user": json.dumps(user, separators=(",", ":")),
    }
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(payload.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    payload["hash"] = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(payload)


def test_validate_tma_init_data_accepts_signed_payload(monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    init_data = _signed_init_data(
        config.BOT_TOKEN,
        {"id": 999999, "first_name": "Admin"},
    )

    parsed = validate_tma_init_data(init_data)

    assert parsed is not None
    assert parsed["user"]["id"] == 999999


def test_validate_tma_init_data_rejects_stale_payload(monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "TMA_INIT_DATA_MAX_AGE_SECONDS", 60)
    payload = {
        "auth_date": str(int(time.time()) - 120),
        "query_id": "old-query",
        "user": json.dumps({"id": 999999}, separators=(",", ":")),
    }
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(payload.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        config.BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    payload["hash"] = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert validate_tma_init_data(urlencode(payload)) is None


def test_tma_feature_catalog_marks_reference_capable_models():
    generation = _feature_catalog()["generation"]

    assert generation["image_models"]["banana_pro"]["supports_refs"] is True
    assert generation["image_models"]["gpt_image_2"]["supports_refs"] is True
    assert generation["image_models"]["grok_t2i"]["supports_refs"] is False
    assert generation["video_models"]["v3_std"]["supports_refs"] is True
    assert generation["video_models"]["seedance2"]["requires_refs"] is True
    assert generation["video_models"]["wan_27_i2v"]["requires_refs"] is True
    assert generation["costs"]["image_models"]["banana_pro"] > 0
    assert generation["costs"]["video_models"]["v3_std"]["5"] > 0


@pytest.mark.asyncio
async def test_require_admin_rejects_non_admin(monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "999999")
    init_data = _signed_init_data(
        config.BOT_TOKEN,
        {"id": 111111, "first_name": "User"},
    )
    request = make_mocked_request(
        "GET",
        "/api/tma/admin/bootstrap",
        headers={"X-Telegram-Init-Data": init_data},
    )

    with pytest.raises(Exception) as exc:
        await require_admin(request)

    assert getattr(exc.value, "status", None) == 403


@pytest.mark.asyncio
async def test_tma_admin_bootstrap_returns_core_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "999999")

    import bot.database as database

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tma.db"))
    await database.init_db()
    await database.get_or_create_user(999999, username="admin")

    init_data = _signed_init_data(
        config.BOT_TOKEN,
        {"id": 999999, "first_name": "Admin", "username": "admin"},
    )
    request = make_mocked_request(
        "GET",
        "/api/tma/admin/bootstrap",
        headers={"X-Telegram-Init-Data": init_data},
    )

    response = await handle_tma_admin_bootstrap(request)
    body = json.loads(response.text)

    assert response.status == 200
    assert body["ok"] is True
    assert set(body["data"]) >= {
        "dashboard",
        "limits",
        "users",
        "payments",
        "subscriptions",
        "recurring",
        "generations",
        "feed",
        "packages",
        "promos",
        "partners",
        "withdrawals",
        "referrals",
        "push",
        "system",
    }


@pytest.mark.asyncio
async def test_tma_dashboard_does_not_multiply_today_revenue_by_tasks(
    tmp_path,
    monkeypatch,
):
    import aiosqlite
    import bot.database as database

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tma-dashboard.db"))
    await database.init_db()
    user = await database.get_or_create_user(111111, username="buyer")
    await database.create_transaction(
        "today-order",
        user.id,
        "payment1",
        "tbank",
        10,
        149.0,
    )
    await database.update_transaction_status("today-order", "completed")
    for index in range(3):
        await database.add_generation_task(
            user.id,
            111111,
            f"task-{index}",
            "image",
            "preset",
            cost=1,
        )
    async with aiosqlite.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE generation_tasks SET status = 'failed' WHERE task_id = 'task-2'"
        )
        await db.commit()

    dashboard = await _dashboard()

    assert dashboard["today_revenue"] == 149.0
    assert dashboard["today_payments"] == 1
    assert dashboard["active_tasks"] == 2
    assert dashboard["failed_tasks"] == 1


@pytest.mark.asyncio
async def test_tma_app_bootstrap_allows_regular_user(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "999999")

    import bot.database as database

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tma-app.db"))
    await database.init_db()
    await database.get_or_create_user(111111, username="user")

    init_data = _signed_init_data(
        config.BOT_TOKEN,
        {"id": 111111, "first_name": "User", "username": "user"},
    )
    request = make_mocked_request(
        "GET",
        "/api/tma/app/bootstrap",
        headers={"X-Telegram-Init-Data": init_data},
    )

    response = await handle_tma_app_bootstrap(request)
    body = json.loads(response.text)

    assert response.status == 200
    assert body["ok"] is True
    assert body["data"]["is_admin"] is False
    assert set(body["data"]) >= {
        "stats",
        "settings",
        "packages",
        "payments",
        "tasks",
        "feed",
        "partner",
        "withdrawals",
        "recurring",
        "gpt55_history",
        "features",
    }


@pytest.mark.asyncio
async def test_tma_prompt_builder_returns_prompt_in_app(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "999999")

    import bot.database as database
    import bot.tma_api as tma_api

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tma-prompt.db"))
    await database.init_db()
    await database.get_or_create_user(111111, username="creator")

    async def fake_json(request):
        return {"idea": "неоновый город"}

    async def fake_ask(*args, **kwargs):
        return "Футуристический неоновый город, cinematic light, high detail"

    monkeypatch.setattr(tma_api, "_read_json", fake_json)
    monkeypatch.setattr(tma_api.gpt55_service, "ask", fake_ask)
    init_data = _signed_init_data(
        config.BOT_TOKEN,
        {"id": 111111, "first_name": "Creator", "username": "creator"},
    )
    request = make_mocked_request(
        "POST",
        "/api/tma/app/prompt-builder",
        headers={"X-Telegram-Init-Data": init_data},
    )

    response = await handle_tma_app_prompt_builder(request)
    body = json.loads(response.text)

    assert response.status == 200
    assert body["ok"] is True
    assert "неоновый город" in body["prompt"]
    assert body["history"]


@pytest.mark.asyncio
async def test_tma_generation_uses_gemini_omni_service(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "999999")

    import bot.database as database
    import bot.tma_api as tma_api

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tma-omni.db"))
    await database.init_db()
    await database.get_or_create_user(111111, username="creator")

    payload = {
        "flow": "gemini_omni",
        "model": "gemini_omni",
        "prompt": "cinematic scene",
        "duration": 4,
        "aspect_ratio": "16:9",
        "references": ["https://cdn.example.com/ref.png", "https://cdn.example.com/ref.mp4"],
        "options": {"resolution": "1080p"},
    }
    calls = {}

    async def fake_json(request):
        return payload

    async def fake_can_start(*args, **kwargs):
        return True

    async def fake_charge(*args, **kwargs):
        return True, "credits", None

    async def fake_generate_video(**kwargs):
        calls.update(kwargs)
        return {"task_id": "omni-task-1"}

    async def fail_kling(*args, **kwargs):
        raise AssertionError("Kling should not handle gemini_omni")

    monkeypatch.setattr(tma_api, "_read_json", fake_json)
    monkeypatch.setattr(tma_api, "_can_start_generation", fake_can_start)
    monkeypatch.setattr(tma_api, "_charge_generation", fake_charge)
    monkeypatch.setattr(tma_api.gemini_omni_service, "generate_video", fake_generate_video)
    monkeypatch.setattr(tma_api.kling_service, "generate_video", fail_kling)
    init_data = _signed_init_data(
        config.BOT_TOKEN,
        {"id": 111111, "first_name": "Creator", "username": "creator"},
    )
    request = make_mocked_request(
        "POST",
        "/api/tma/app/generation",
        headers={"X-Telegram-Init-Data": init_data},
    )

    response = await handle_tma_app_generation(request)
    body = json.loads(response.text)

    assert response.status == 200
    assert body["ok"] is True
    assert calls["image_urls"] == ["https://cdn.example.com/ref.png"]
    assert calls["video_urls"] == ["https://cdn.example.com/ref.mp4"]
    assert calls["resolution"] == "1080p"


@pytest.mark.asyncio
async def test_tma_generation_uses_motion_control_service(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "999999")

    import bot.database as database
    import bot.tma_api as tma_api

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tma-motion.db"))
    await database.init_db()
    await database.get_or_create_user(111111, username="creator")

    payload = {
        "flow": "motion_control",
        "model": "v3_pro",
        "prompt": "make the character dance",
        "duration": 5,
        "aspect_ratio": "9:16",
        "motion_photo_url": "https://cdn.example.com/character.png",
        "motion_video_url": "https://cdn.example.com/motion.mp4",
        "references": [
            "https://cdn.example.com/character.png",
            "https://cdn.example.com/motion.mp4",
        ],
    }
    calls = {}

    async def fake_json(request):
        return payload

    async def fake_can_start(*args, **kwargs):
        return True

    async def fake_charge(*args, **kwargs):
        return True, "credits", None

    async def fake_motion(**kwargs):
        calls.update(kwargs)
        return {"task_id": "motion-task-1"}

    async def fail_video(*args, **kwargs):
        raise AssertionError("regular video generation should not handle motion_control")

    monkeypatch.setattr(tma_api, "_read_json", fake_json)
    monkeypatch.setattr(tma_api, "_can_start_generation", fake_can_start)
    monkeypatch.setattr(tma_api, "_charge_generation", fake_charge)
    monkeypatch.setattr(tma_api.kling_service, "generate_motion_control", fake_motion)
    monkeypatch.setattr(tma_api.kling_service, "generate_video", fail_video)
    init_data = _signed_init_data(
        config.BOT_TOKEN,
        {"id": 111111, "first_name": "Creator", "username": "creator"},
    )
    request = make_mocked_request(
        "POST",
        "/api/tma/app/generation",
        headers={"X-Telegram-Init-Data": init_data},
    )

    response = await handle_tma_app_generation(request)
    body = json.loads(response.text)

    assert response.status == 200
    assert body["ok"] is True
    assert calls["image_url"] == "https://cdn.example.com/character.png"
    assert calls["video_urls"] == ["https://cdn.example.com/motion.mp4"]
    assert calls["mode"] == "1080p"
    assert calls["aspect_ratio"] == "9:16"


@pytest.mark.asyncio
async def test_tma_generation_rejects_required_refs_before_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "999999")

    import bot.database as database
    import bot.tma_api as tma_api

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tma-refs.db"))
    await database.init_db()
    await database.get_or_create_user(111111, username="creator")

    async def fake_json(request):
        return {
            "flow": "image",
            "model": "seedream_edit",
            "prompt": "edit this portrait",
            "references": [],
        }

    async def fail_provider(*args, **kwargs):
        raise AssertionError("provider should not be called without required refs")

    monkeypatch.setattr(tma_api, "_read_json", fake_json)
    monkeypatch.setattr(tma_api.seedream_lite_service, "generate_image", fail_provider)
    init_data = _signed_init_data(
        config.BOT_TOKEN,
        {"id": 111111, "first_name": "Creator", "username": "creator"},
    )
    request = make_mocked_request(
        "POST",
        "/api/tma/app/generation",
        headers={"X-Telegram-Init-Data": init_data},
    )

    response = await handle_tma_app_generation(request)
    body = json.loads(response.text)

    assert response.status == 400
    assert body == {"ok": False, "error": "refs_required"}


@pytest.mark.asyncio
async def test_tma_generation_applies_prompt_assist_options(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "999999")

    import bot.database as database
    import bot.tma_api as tma_api

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tma-assist.db"))
    await database.init_db()
    await database.get_or_create_user(111111, username="creator")

    async def fake_json(request):
        return {
            "flow": "image",
            "model": "banana_pro",
            "prompt": "portrait in neon city",
            "aspect_ratio": "1:1",
            "references": ["https://cdn.example.com/face.png"],
            "options": {"improve_prompt": True, "face_preservation": "strict"},
        }

    async def fake_ask(*args, **kwargs):
        return "improved portrait prompt"

    async def fake_can_start(*args, **kwargs):
        return True

    async def fake_charge(*args, **kwargs):
        return True, "credits", None

    calls = {}

    async def fake_generate_image(prompt, **kwargs):
        calls["prompt"] = prompt
        calls.update(kwargs)
        return {"task_id": "assist-task-1"}

    monkeypatch.setattr(tma_api, "_read_json", fake_json)
    monkeypatch.setattr(tma_api.gpt55_service, "ask", fake_ask)
    monkeypatch.setattr(tma_api, "_can_start_generation", fake_can_start)
    monkeypatch.setattr(tma_api, "_charge_generation", fake_charge)
    monkeypatch.setattr(tma_api.nano_banana_pro_service, "generate_image", fake_generate_image)
    init_data = _signed_init_data(
        config.BOT_TOKEN,
        {"id": 111111, "first_name": "Creator", "username": "creator"},
    )
    request = make_mocked_request(
        "POST",
        "/api/tma/app/generation",
        headers={"X-Telegram-Init-Data": init_data},
    )

    response = await handle_tma_app_generation(request)
    body = json.loads(response.text)

    assert response.status == 200
    assert body["ok"] is True
    assert calls["prompt"].startswith("improved portrait prompt")
    assert "strict identity guidance" in calls["prompt"]
    assert calls["image_input"] == ["https://cdn.example.com/face.png"]


@pytest.mark.asyncio
async def test_tma_multi_photo_requires_multiple_refs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "999999")

    import bot.database as database
    import bot.tma_api as tma_api

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tma-multi.db"))
    await database.init_db()
    await database.get_or_create_user(111111, username="creator")

    async def fake_json(request):
        return {
            "flow": "multi_photo",
            "model": "banana_pro",
            "prompt": "combine these photos",
            "references": ["https://cdn.example.com/one.png"],
        }

    async def fail_provider(*args, **kwargs):
        raise AssertionError("provider should not be called with one multi-photo ref")

    monkeypatch.setattr(tma_api, "_read_json", fake_json)
    monkeypatch.setattr(tma_api.nano_banana_pro_service, "generate_image", fail_provider)
    init_data = _signed_init_data(
        config.BOT_TOKEN,
        {"id": 111111, "first_name": "Creator", "username": "creator"},
    )
    request = make_mocked_request(
        "POST",
        "/api/tma/app/generation",
        headers={"X-Telegram-Init-Data": init_data},
    )

    response = await handle_tma_app_generation(request)
    body = json.loads(response.text)

    assert response.status == 400
    assert body == {"ok": False, "error": "multi_photo_refs_required"}


@pytest.mark.asyncio
async def test_tma_multi_photo_runs_remix_models(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "999999")

    import bot.database as database
    import bot.tma_api as tma_api

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tma-remix.db"))
    await database.init_db()
    await database.get_or_create_user(111111, username="creator")

    async def fake_json(request):
        return {
            "flow": "multi_photo",
            "model": "mix_photo",
            "prompt": "combine these photos",
            "aspect_ratio": "1:1",
            "references": [
                "https://cdn.example.com/one.png",
                "https://cdn.example.com/two.png",
            ],
        }

    async def fake_can_start(*args, **kwargs):
        return True

    async def fake_charge(*args, **kwargs):
        return True, "credits", None

    calls = []

    async def fake_banana(*args, **kwargs):
        calls.append("banana_2")
        return {"task_id": "banana-task"}

    async def fake_grok(*args, **kwargs):
        calls.append("grok_i2i")
        return {"task_id": "grok-task"}

    async def fake_gpt(*args, **kwargs):
        calls.append("gpt_image_2")
        return {"task_id": "gpt-task"}

    monkeypatch.setattr(tma_api, "_read_json", fake_json)
    monkeypatch.setattr(tma_api, "_can_start_generation", fake_can_start)
    monkeypatch.setattr(tma_api, "_charge_generation", fake_charge)
    monkeypatch.setattr(tma_api.nano_banana_2_service, "generate_image", fake_banana)
    monkeypatch.setattr(tma_api.grok_service, "generate_image_to_image", fake_grok)
    monkeypatch.setattr(tma_api.gpt_image_service, "generate_image", fake_gpt)
    init_data = _signed_init_data(
        config.BOT_TOKEN,
        {"id": 111111, "first_name": "Creator", "username": "creator"},
    )
    request = make_mocked_request(
        "POST",
        "/api/tma/app/generation",
        headers={"X-Telegram-Init-Data": init_data},
    )

    response = await handle_tma_app_generation(request)
    body = json.loads(response.text)

    assert response.status == 200
    assert body["ok"] is True
    assert calls == ["banana_2", "grok_i2i", "gpt_image_2"]
    assert [task["model"] for task in body["tasks"]] == [
        "banana_2",
        "grok_i2i",
        "gpt_image_2",
    ]


@pytest.mark.asyncio
async def test_tma_image_to_video_uses_grok_imagine_service(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "999999")

    import bot.database as database
    import bot.tma_api as tma_api

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tma-grok-i2v.db"))
    await database.init_db()
    await database.get_or_create_user(111111, username="creator")

    async def fake_json(request):
        return {
            "flow": "image_to_video",
            "model": "grok_imagine",
            "prompt": "make this portrait blink and smile",
            "duration": 6,
            "aspect_ratio": "9:16",
            "references": [
                "https://cdn.example.com/portrait.png",
                "https://cdn.example.com/style.png",
            ],
            "options": {
                "mode": "fun",
                "resolution": "1080p",
                "nsfw_checker": True,
                "face_preservation": "strict",
            },
        }

    async def fake_can_start(*args, **kwargs):
        return True

    async def fake_charge(*args, **kwargs):
        return True, "credits", None

    calls = {}

    async def fake_grok(**kwargs):
        calls.update(kwargs)
        return {"task_id": "grok-i2v-task"}

    async def fail_kling(*args, **kwargs):
        raise AssertionError("Kling should not handle grok_imagine")

    monkeypatch.setattr(tma_api, "_read_json", fake_json)
    monkeypatch.setattr(tma_api, "_can_start_generation", fake_can_start)
    monkeypatch.setattr(tma_api, "_charge_generation", fake_charge)
    monkeypatch.setattr(tma_api.grok_service, "generate_image_to_video", fake_grok)
    monkeypatch.setattr(tma_api.kling_service, "generate_video", fail_kling)
    init_data = _signed_init_data(
        config.BOT_TOKEN,
        {"id": 111111, "first_name": "Creator", "username": "creator"},
    )
    request = make_mocked_request(
        "POST",
        "/api/tma/app/generation",
        headers={"X-Telegram-Init-Data": init_data},
    )

    response = await handle_tma_app_generation(request)
    body = json.loads(response.text)

    assert response.status == 200
    assert body["ok"] is True
    assert body["task"]["model"] == "grok_imagine"
    assert calls == {
        "image_urls": [
            "https://cdn.example.com/portrait.png",
            "https://cdn.example.com/style.png",
        ],
        "prompt": "make this portrait blink and smile\n\nUse the reference photo(s) as strict identity guidance. Preserve the exact person: facial structure, age, eye color, face shape, proportions, hairline and distinctive features must remain unchanged. Change only the requested style, background, outfit or scene.",
        "mode": "fun",
        "duration": 6,
        "resolution": "1080p",
        "aspect_ratio": "9:16",
        "nsfw_checker": True,
        "callBackUrl": config.kie_notification_url,
    }


@pytest.mark.asyncio
async def test_tma_payment_action_completes_transaction_and_credits_user(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "999999")

    import bot.database as database
    import bot.tma_api as tma_api

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tma-payment.db"))
    await database.init_db()
    user = await database.get_or_create_user(111111, username="buyer")
    before = await database.get_user_stats(111111)
    await database.create_transaction(
        "order1",
        user.id,
        "payment1",
        "tbank",
        10,
        100.0,
    )

    async def fake_json(request):
        return {"action": "mark_completed"}

    monkeypatch.setattr(tma_api, "_read_json", fake_json)
    init_data = _signed_init_data(
        config.BOT_TOKEN,
        {"id": 999999, "first_name": "Admin", "username": "admin"},
    )
    request = make_mocked_request(
        "POST",
        "/api/tma/admin/payments/order1/action",
        headers={"X-Telegram-Init-Data": init_data},
        match_info={"order_id": "order1"},
    )

    response = await handle_tma_admin_payment_action(request)
    body = json.loads(response.text)
    stats = await database.get_user_stats(111111)

    assert response.status == 200
    assert body["ok"] is True
    assert stats["credits"] == before["credits"] + 10
