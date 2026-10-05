import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from bot.genjutsu.provider import Higgsfield, ProviderFailure


@pytest.mark.asyncio
async def test_provider_uses_exact_paths_auth_and_payload():
    seen = {}

    async def submit(request):
        seen["auth"] = request.headers.get("Authorization")
        seen["idempotency"] = request.headers.get("Idempotency-Key")
        seen["path"] = request.path
        seen["query"] = dict(request.query)
        seen["json"] = await request.json()
        return web.json_response(
            {
                "request_id": "req_123",
                "status_url": str(request.url.with_path("/requests/req_123/status")),
                "cancel_url": str(request.url.with_path("/requests/req_123/cancel")),
            },
            headers={"X-Correlation-ID": "corr-123"},
        )

    async def status(request):
        return web.json_response({"status": "completed", "video": {"url": "https://cdn.example/result.mp4"}})

    async def cancel(request):
        return web.json_response({"ok": True})

    async def presets(request):
        return web.json_response({
            "model": "higgsfield/genjutsu/restyle/v1.0",
            "items": [{
                "id": "1a7ae07f-5e1f-4517-a03e-d92f03a41fb2",
                "name": "Anime",
                "preview_url": "https://cdn.example/preset.jpg",
            }],
        })

    app = web.Application()
    app.router.add_post("/higgsfield/genjutsu/motion-transfer/v1.0", submit)
    app.router.add_get("/requests/{rid}/status", status)
    app.router.add_post("/requests/{rid}/cancel", cancel)
    app.router.add_get("/models/higgsfield/genjutsu/restyle/v1.0/presets", presets)
    server = TestServer(app)
    await server.start_server()
    try:
        provider = Higgsfield("secret", str(server.make_url("")).rstrip("/"), allow_insecure_for_tests=True)
        handle = await provider.submit(
            "higgsfield/genjutsu/motion-transfer/v1.0",
            {
                "video_url": "https://media.example/source.mp4",
                "image_urls": ["https://media.example/ref.png"],
                "prompt": "move",
                "resolution": "1080p",
            },
            timeout=5,
            webhook="https://app.example/callback",
            idempotency_key="intent-12345678",
        )
        assert handle["request_id"] == "req_123"
        assert handle["correlation_id"] == "corr-123"
        assert handle["status_url"].endswith("/requests/req_123/status")
        assert seen["auth"] == "Key secret"
        assert seen["idempotency"] == "intent-12345678"
        assert seen["path"] == "/higgsfield/genjutsu/motion-transfer/v1.0"
        assert seen["query"] == {"hf_webhook": "https://app.example/callback"}
        assert set(seen["json"]) == {"video_url", "image_urls", "prompt", "resolution"}
        assert (await provider.status(handle["request_id"], timeout=5, status_url=handle["status_url"]))["result_url"] == "https://cdn.example/result.mp4"
        await provider.cancel(handle["request_id"], timeout=5, cancel_url=handle["cancel_url"])
        assert (await provider.presets(timeout=5))[0]["name"] == "Anime"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_submission_5xx_is_uncertain_and_must_not_be_blindly_retried():
    async def failure(_request):
        return web.Response(status=503)

    app = web.Application()
    app.router.add_post("/higgsfield/genjutsu/object-swap/v1.0", failure)
    server = TestServer(app)
    await server.start_server()
    try:
        provider = Higgsfield("secret", str(server.make_url("")).rstrip("/"), allow_insecure_for_tests=True)
        with pytest.raises(ProviderFailure) as captured:
            await provider.submit(
                "higgsfield/genjutsu/object-swap/v1.0",
                {"video_url": "https://media.example/x.mp4", "image_urls": ["https://media.example/a.png"], "prompt": "", "resolution": "720p"},
                timeout=5,
                idempotency_key="intent-87654321",
            )
        assert captured.value.uncertain is True
        assert captured.value.code == "provider_http_503"
    finally:
        await server.close()


def test_production_provider_accepts_higgsfield_platform_status_host_only():
    provider = Higgsfield("secret", "https://api.higgsfield.ai")

    status_url = "https://platform.higgsfield.ai/requests/request-123/status"
    cancel_url = "https://platform.higgsfield.ai/requests/request-123/cancel"

    assert provider._provider_url(status_url) == status_url
    assert provider._provider_url(cancel_url) == cancel_url
    assert provider._request_handle_url("request-123", "status") == status_url
    assert provider._request_handle_url("request-123", "cancel") == cancel_url

    with pytest.raises(ProviderFailure, match="provider_invalid_url"):
        provider._provider_url("https://evil.example/requests/request-123/status")
