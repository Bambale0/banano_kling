"""Safe cross-platform multimedia reference ownership for motion/avatars."""
from types import SimpleNamespace

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from bot import web_auth, web_generation, web_references


@pytest.mark.asyncio
async def test_web_multimedia_references_are_typed_and_private(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_references, "is_s3_enabled", lambda: True)
    monkeypatch.setattr(web_references, "persist_upload_bytes",
                        lambda path, data, **kw: "https://neuromixbot.com/uploads/" + path)

    async def login(subject):
        response = await web_auth._complete_identity(
            SimpleNamespace(), "yandex", subject,
            {"mode": "login", "source": None, "destination": "/login"},
        )
        return response.cookies["nm_web_session"].value

    owner_cookie = await login("web-multimedia-owner")
    other_cookie = await login("web-multimedia-other")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        ids = {}
        for kind, data, mime in (
            ("image", b"\x89PNG\r\n\x1a\n1234567890123456", "image/png"),
            ("video", b"\x00\x00\x00\x18ftypisom00000000", "video/mp4"),
            ("audio", b"ID3\x04\x00\x00\x00\x00\x00\x03abcdef", "audio/mpeg"),
        ):
            form = FormData()
            form.add_field(kind, data, filename=kind, content_type=mime)
            response = await client.post("/mini-app/api/web-auth/web-generation/reference",
                                         data=form, headers={
                                             "Origin": "https://neuromixbot.com",
                                             "Cookie": "nm_web_session=" + owner_cookie,
                                         })
            assert response.status == 200, await response.text()
            ids[kind] = (await response.json())["reference_id"]

        owner = await web_auth._session_account(SimpleNamespace(cookies={
            "nm_web_session": owner_cookie,
        }))
        other = await web_auth._session_account(SimpleNamespace(cookies={
            "nm_web_session": other_cookie,
        }))
        assert len(await web_references.owned_reference_urls(owner, [ids["image"]], kind="image")) == 1
        assert len(await web_references.owned_reference_urls(owner, [ids["video"]], kind="video")) == 1
        assert len(await web_references.owned_reference_urls(owner, [ids["audio"]], kind="audio")) == 1
        with pytest.raises(PermissionError):
            await web_references.owned_reference_urls(other, [ids["image"]], kind="image")
        with pytest.raises(PermissionError):
            await web_references.owned_reference_urls(owner, [ids["video"]], kind="image")


def test_motion_avatar_validation_rejects_missing_video_and_audio_refs():
    for model, extra_key in (
        ("motion_control_v26", "video_reference_ids"),
        ("motion_control_v30", "video_reference_ids"),
        ("avatar_std", "audio_reference_ids"),
        ("avatar_pro", "audio_reference_ids"),
    ):
        with pytest.raises(ValueError):
            web_generation._normalize_request({
                "model": model,
                "prompt": "Animate the person speaking",
                "reference_ids": ["wr_" + "a" * 32],
                "request_key": "motion-required-key-2026",
            })
        valid = web_generation._normalize_request({
            "model": model,
            "prompt": "Animate the person speaking",
            "reference_ids": ["wr_" + "a" * 32],
            extra_key: ["wr_" + "b" * 32],
            "request_key": "motion-required-key-2026",
            "quality": "720p" if model.startswith("motion") else None,
        })
        assert valid[extra_key] == ["wr_" + "b" * 32]


@pytest.mark.asyncio
@pytest.mark.parametrize("model,kind,extra_key", (
    ("motion_control_v26", "video", "video_reference_ids"),
    ("avatar_std", "audio", "audio_reference_ids"),
))
async def test_typed_multimedia_task_reserves_and_delivers_to_own_browser_history(
    monkeypatch, model, kind, extra_key,
):
    from unittest.mock import AsyncMock

    from aiohttp import FormData

    from bot import db as db_backend
    from bot import web_media_delivery
    from bot.shared_accounts.wallet import WalletService

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_references, "is_s3_enabled", lambda: True)
    monkeypatch.setattr(web_references, "persist_upload_bytes",
                        lambda path, data, **kw: "https://neuromixbot.com/uploads/" + path)
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    monkeypatch.setattr(web_generation, "_price", lambda *args: "5.0000")
    submit = AsyncMock(return_value=("real-provider-id", False))
    poll = AsyncMock(return_value=("success", "https://cdn.kie.ai/result.mp4"))
    archive = AsyncMock(return_value="https://neuromixbot.com/uploads/web_results/ready.mp4")
    monkeypatch.setattr(web_generation, "_submit_to_provider", submit)
    monkeypatch.setattr(web_generation, "_provider_check", poll)
    monkeypatch.setattr(web_media_delivery, "archive_web_result", archive)

    signed = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", model + "-web-owned",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = signed.cookies["nm_web_session"].value
    owner = await web_auth._session_account(SimpleNamespace(
        cookies={"nm_web_session": cookie},
    ))
    await WalletService("live").apply(owner, "credit", "8", "multimedia-seed:" + model)
    headers = {
        "Origin": "https://neuromixbot.com", "Cookie": "nm_web_session=" + cookie,
    }
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        ids = {}
        for ref_kind, raw, mime in (
            ("image", b"\x89PNG\r\n\x1a\n" + b"A" * 22, "image/png"),
            (kind, b"\x00\x00\x00\x18ftyp" + b"B" * 20 if kind == "video"
             else b"ID3\x04\x00\x00" + b"B" * 20,
             "video/mp4" if kind == "video" else "audio/mpeg"),
        ):
            form = FormData()
            form.add_field(ref_kind, raw, filename=ref_kind, content_type=mime)
            response = await client.post(
                "/mini-app/api/web-auth/web-generation/reference",
                data=form, headers=headers,
            )
            assert response.status == 200, await response.text()
            ids[ref_kind] = (await response.json())["reference_id"]
        request = {
            "model": model, "prompt": "Person moves and speaks to the camera",
            "request_key": "multimedia-key-" + model.replace("_", "-"),
            "reference_ids": [ids["image"]],
            extra_key: [ids[kind]],
            "quality": "720p" if kind == "video" else None,
            "expected_price": "5.0000",
        }
        quote = await client.post(
            "/mini-app/api/web-auth/web-generation/quote",
            json={key: value for key, value in request.items()
                  if key not in ("request_key", "expected_price")},
            headers=headers,
        )
        assert quote.status == 200, await quote.text()
        assert (await quote.json())["price"] == "5.0000"
        created = await client.post(
            "/mini-app/api/web-auth/web-generation/create", json=request,
            headers=headers,
        )
        assert created.status == 202, await created.text()
        task_id = (await created.json())["task_id"]
        assert (await WalletService("live").snapshot(owner))["balance"]["reserved"] == "5.0000"
        assert await web_generation.run_worker_tick() == [task_id]
        async with db_backend.connect() as db:
            await db.execute("UPDATE web_generation_tasks SET lease_until_epoch=0 WHERE task_id=?",
                             (task_id,))
            await db.commit()
        assert await web_generation.run_worker_tick() == [task_id]
        submit.assert_awaited_once()
        arguments = submit.await_args.args[1]
        assert arguments["reference_urls"][0].startswith("https://neuromixbot.com/uploads/web_refs/")
        assert arguments["reference_" + kind + "_urls"][0].startswith("https://neuromixbot.com/uploads/web_refs/")
        task = await client.get("/mini-app/api/web-auth/task/" + task_id, headers=headers)
        assert (await task.json())["task"]["status"] == "completed"
        assert (await WalletService("live").snapshot(owner))["balance"] == {
            "available": "3.0000", "reserved": "0.0000", "revision": 3,
        }
