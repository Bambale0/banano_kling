import json

import pytest

from bot import database
from bot.handlers import miniapp_regression_safety as safety


class FakeMiniAppModule:
    def __init__(self, telegram_id: int = 123456789, *, init_data: str = "signed") -> None:
        self.telegram_id = telegram_id
        self.init_data = init_data

    async def _miniapp_payload(self, _request):
        return {"init_data": self.init_data}

    def _validate_init_data(self, init_data: str, _bot_token: str):
        if not init_data:
            raise ValueError("Missing init_data")
        return {"user": {"id": self.telegram_id}}


@pytest.mark.asyncio
async def test_banned_authenticated_miniapp_user_gets_403(monkeypatch):
    fake_module = FakeMiniAppModule()

    async def fake_is_banned(telegram_id: int) -> bool:
        return telegram_id == fake_module.telegram_id

    monkeypatch.setattr(safety, "_get_miniapp_module", lambda: fake_module)
    monkeypatch.setattr(safety.config, "is_admin", lambda _telegram_id: False)
    monkeypatch.setattr(database, "is_user_banned", fake_is_banned)

    response = await safety._banned_miniapp_response(object())  # type: ignore[arg-type]
    payload = json.loads(response.text)

    assert response.status == 403
    assert payload["code"] == "user_banned"


@pytest.mark.asyncio
async def test_admin_bypasses_miniapp_ban_guard(monkeypatch):
    fake_module = FakeMiniAppModule(telegram_id=42)

    async def fake_is_banned(_telegram_id: int) -> bool:
        return True

    monkeypatch.setattr(safety, "_get_miniapp_module", lambda: fake_module)
    monkeypatch.setattr(safety.config, "is_admin", lambda telegram_id: telegram_id == 42)
    monkeypatch.setattr(database, "is_user_banned", fake_is_banned)

    response = await safety._banned_miniapp_response(object())  # type: ignore[arg-type]

    assert response is None


def test_miniapp_ban_guard_only_targets_api_routes(monkeypatch):
    monkeypatch.setattr(safety.config, "MINI_APP_PATH", "/mini-app")

    assert safety._is_miniapp_api_path("/mini-app/api/bootstrap") is True
    assert safety._is_miniapp_api_path("/mini-app/api/generate-image") is True
    assert safety._is_miniapp_api_path("/api/v1/feed") is True
    assert safety._is_miniapp_api_path("/mini-app/") is False
    assert safety._is_miniapp_api_path("/mini-app/_next/static/app.js") is False
    assert safety._is_miniapp_api_path("/internal/admin/users") is False
