import json
from types import SimpleNamespace
from urllib.parse import urlencode

from bot import miniapp_api


def _request(init_data: str = ""):
    return SimpleNamespace(headers={"X-Telegram-Init-Data": init_data})


def _init_data(user_id: int) -> str:
    return urlencode({"user": json.dumps({"id": user_id})})


def test_miniapp_admin_fails_closed_without_admin_ids(monkeypatch):
    monkeypatch.setattr(miniapp_api, "MINIAPP_ADMIN_IDS", set())
    monkeypatch.delenv("TWOLOOP_ALLOW_OPEN_ADMIN", raising=False)

    assert not miniapp_api._is_admin(_request())


def test_miniapp_admin_open_mode_requires_explicit_flag(monkeypatch):
    monkeypatch.setattr(miniapp_api, "MINIAPP_ADMIN_IDS", set())
    monkeypatch.setenv("TWOLOOP_ALLOW_OPEN_ADMIN", "1")

    assert miniapp_api._is_admin(_request())


def test_miniapp_admin_ids_require_valid_telegram_user(monkeypatch):
    monkeypatch.setattr(miniapp_api, "MINIAPP_ADMIN_IDS", {"123"})
    monkeypatch.setattr(miniapp_api, "VERIFY_INIT_DATA", False)

    assert miniapp_api._is_admin(_request(_init_data(123)))
    assert not miniapp_api._is_admin(_request(_init_data(456)))


async def _ok_handler(request):
    return miniapp_api._json({"ok": True})


def test_miniapp_admin_only_gate_blocks_non_admin(monkeypatch):
    monkeypatch.setenv("TWOLOOP_MINIAPP_ADMIN_ONLY", "1")
    monkeypatch.setattr(miniapp_api, "MINIAPP_ADMIN_IDS", {"123"})
    monkeypatch.setattr(miniapp_api, "VERIFY_INIT_DATA", False)

    wrapped = miniapp_api._gate_miniapp(_ok_handler)
    response = __import__("asyncio").run(wrapped(_request(_init_data(456))))

    assert response.status == 403


def test_miniapp_admin_only_gate_allows_admin(monkeypatch):
    monkeypatch.setenv("TWOLOOP_MINIAPP_ADMIN_ONLY", "1")
    monkeypatch.setattr(miniapp_api, "MINIAPP_ADMIN_IDS", {"123"})
    monkeypatch.setattr(miniapp_api, "VERIFY_INIT_DATA", False)

    wrapped = miniapp_api._gate_miniapp(_ok_handler)
    response = __import__("asyncio").run(wrapped(_request(_init_data(123))))

    assert response.status == 200


def test_miniapp_health_can_stay_public(monkeypatch):
    monkeypatch.setenv("TWOLOOP_MINIAPP_ADMIN_ONLY", "1")
    monkeypatch.setattr(miniapp_api, "MINIAPP_ADMIN_IDS", {"123"})

    wrapped = miniapp_api._gate_miniapp(_ok_handler, public=True)
    response = __import__("asyncio").run(wrapped(_request()))

    assert response.status == 200
