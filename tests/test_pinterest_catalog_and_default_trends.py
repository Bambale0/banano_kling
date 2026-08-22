from pathlib import Path
from types import SimpleNamespace

import pytest

from bot import pinterest_trend_catalog as catalog


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_pinterest_catalog_uses_master_system_user_without_admin_ids(monkeypatch):
    monkeypatch.setattr(catalog.config, "ADMIN_IDS_STR", "")
    calls: list[str] = []

    async def fake_master_user():
        calls.append("master")
        return SimpleNamespace(id=9001)

    async def forbidden_admin_user(_telegram_id):
        raise AssertionError("admin user lookup must not run without ADMIN_IDS")

    monkeypatch.setattr(catalog, "get_master_partner_user", fake_master_user)
    monkeypatch.setattr(catalog, "get_or_create_user", forbidden_admin_user)

    author = await catalog._system_trend_author()

    assert author.id == 9001
    assert calls == ["master"]


@pytest.mark.asyncio
async def test_pinterest_catalog_prefers_configured_admin(monkeypatch):
    monkeypatch.setattr(catalog.config, "ADMIN_IDS_STR", "424242")
    calls: list[int] = []

    async def fake_admin_user(telegram_id):
        calls.append(int(telegram_id))
        return SimpleNamespace(id=17)

    async def forbidden_master_user():
        raise AssertionError("master fallback must not run when ADMIN_IDS is configured")

    monkeypatch.setattr(catalog, "get_or_create_user", fake_admin_user)
    monkeypatch.setattr(catalog, "get_master_partner_user", forbidden_master_user)

    author = await catalog._system_trend_author()

    assert author.id == 17
    assert calls == [424242]


def test_pinterest_catalog_is_a_strict_startup_and_list_requirement():
    routes = (ROOT / "bot/handlers/trend_route_compat.py").read_text(encoding="utf-8")
    catalog_source = (ROOT / "bot/pinterest_trend_catalog.py").read_text(encoding="utf-8")

    assert "ensure_pinterest_trend_catalog" in routes
    assert "app.on_startup.append(ensure_pinterest_trend_catalog)" in routes
    assert "prompts_with_required_system_trends" in routes
    assert 'source == "tag" and tag == "trend"' in routes
    assert "await ensure_pinterest_trend_catalog(request.app)" in routes
    assert "get_master_partner_user" in catalog_source
    assert "is_public = TRUE" in catalog_source
    assert "status = 'approved'" in catalog_source
    assert 'model = \'banana_pro\'' in catalog_source
    assert "generation_settings = ?" in catalog_source
    assert "lastrowid" not in catalog_source


def test_referral_launch_preserves_trends_as_default_tab():
    start_params = (ROOT / "frontend/miniapp-v0/lib/start-params.ts").read_text(
        encoding="utf-8"
    )
    app_context = (ROOT / "frontend/miniapp-v0/lib/app-context.tsx").read_text(
        encoding="utf-8"
    )

    assert "useState(5)" in app_context
    assert "if (raw.startsWith('ref_')) return null" in start_params
    assert "if (startTarget.kind === 'ref')" in app_context
    referral_branch = app_context.split("if (startTarget.kind === 'ref')", 1)[1].split(
        "if (startTarget.kind === 'profile')", 1
    )[0]
    assert "setActiveTabState(5)" in referral_branch
    assert "setActiveTabState(0)" not in referral_branch

    # Explicit navigation deep-links must remain supported.
    for prefix in (
        "profile_",
        "posts_",
        "feed_",
        "remix_",
        "prompt_",
        "task_",
    ):
        assert prefix in start_params
