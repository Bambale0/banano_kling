"""Immutable, signed-actor audit history for every editorial catalog mutation."""

from __future__ import annotations

import json
import sqlite3

import pytest

from bot import database, trend_catalog, trend_catalog_audit
from bot import db as db_backend

ADMIN = 999999999


@pytest.fixture(autouse=True)
async def isolated_metrics(isolated_database, monkeypatch):
    from bot.handlers import trend_success_compat

    monkeypatch.setattr(trend_success_compat, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(trend_success_compat, "_SCHEMA_READY", False)


async def _make_private_trend() -> dict:
    user = await database.get_or_create_user(ADMIN)
    prompt = await database.create_prompt(
        author_id=user.id,
        title="Публичный день рождения",
        description="Создайте поздравление",
        prompt_text="SECRET recipe @Image1 input private scene 1992",
        category="video",
        model="seedance_2_5",
        tags=["trend", "trend-video"],
        is_public=True,
        generation_settings={
            "kind": "video",
            "user_fields": [{"key": "Возраст", "original_value": "1992"}],
        },
    )
    return await database.approve_prompt(prompt["id"])


@pytest.mark.asyncio
async def test_all_eight_mutations_leave_signed_atomic_snapshots_without_private_recipe():
    trend = await _make_private_trend()
    first = await trend_catalog.create_category("День рождения", "🎂", actor_id=ADMIN)
    second = await trend_catalog.create_category("Видео", "🎬", actor_id=ADMIN)
    await trend_catalog.reorder_categories(
        [
            {"id": second["id"], "revision": second["revision"]},
            {"id": first["id"], "revision": first["revision"]},
        ],
        actor_id=ADMIN,
    )
    await trend_catalog.set_trend_categories(
        trend["id"],
        [first["id"]],
        actor_id=ADMIN,
    )
    catalog = await trend_catalog.list_catalog(is_admin=True)
    first_current = next(item for item in catalog if item["id"] == first["id"])
    await trend_catalog.replace_category_items(
        first["id"],
        [trend["id"]],
        revision=first_current["revision"],
        actor_id=ADMIN,
    )
    catalog = await trend_catalog.list_catalog(is_admin=True)
    first_current = next(item for item in catalog if item["id"] == first["id"])
    await trend_catalog.set_badge(
        first["id"],
        trend["id"],
        first_current["revision"],
        badge="new",
        badge_until="2028-04-01",
        actor_id=ADMIN,
    )
    catalog = await trend_catalog.list_catalog(is_admin=True)
    first_current = next(item for item in catalog if item["id"] == first["id"])
    second_current = next(item for item in catalog if item["id"] == second["id"])
    await trend_catalog.move_trend_between_categories(
        trend["id"],
        first["id"],
        second["id"],
        source_revision=first_current["revision"],
        target_revision=second_current["revision"],
        actor_id=ADMIN,
    )
    catalog = await trend_catalog.list_catalog(is_admin=True)
    second_current = next(item for item in catalog if item["id"] == second["id"])
    renamed = await trend_catalog.update_category(
        second["id"],
        second_current["revision"],
        title="Reels",
        actor_id=ADMIN,
    )
    await trend_catalog.delete_category(
        second["id"], renamed["revision"], actor_id=ADMIN
    )

    history = await trend_catalog_audit.list_history(limit=50)
    operations = [item["action"] for item in history]
    assert set(operations) == {
        "create",
        "reorder",
        "set_trend_categories",
        "set_items",
        "set_badge",
        "move_item",
        "update",
        "delete",
    }
    assert len(history) == 9  # two category creations
    assert all(item["actor_telegram_id"] == ADMIN for item in history)
    assert len({item["id"] for item in history}) == len(history)
    assert all(item["created_at"] for item in history)
    serialized = json.dumps(history, ensure_ascii=False)
    assert "SECRET recipe" not in serialized
    assert "@Image1" not in serialized
    assert "original_value" not in serialized
    delete = next(item for item in history if item["action"] == "delete")
    assert delete["before"]["items"][0]["prompt_id"] == trend["id"]
    assert delete["after"] is None
    move = next(item for item in history if item["action"] == "move_item")
    assert move["before"]["memberships"]["placements"][0]["category_id"] == first["id"]
    assert move["after"]["memberships"]["placements"][0]["category_id"] == second["id"]


@pytest.mark.asyncio
async def test_failed_audit_insert_rolls_back_category_mutation(monkeypatch):
    async def broken_audit(*_args, **_kwargs):
        raise RuntimeError("simulated audit DB insert failure")

    original = trend_catalog_audit.append
    monkeypatch.setattr(trend_catalog_audit, "append", broken_audit)
    with pytest.raises(RuntimeError, match="audit DB"):
        await trend_catalog.create_category("Cannot appear", "❌", actor_id=ADMIN)

    assert await trend_catalog.list_catalog(is_admin=True) == []
    monkeypatch.setattr(trend_catalog_audit, "append", original)
    created = await trend_catalog.create_category("Safe", "📁", actor_id=ADMIN)
    old_version = created["revision"]
    monkeypatch.setattr(trend_catalog_audit, "append", broken_audit)
    with pytest.raises(RuntimeError, match="audit DB"):
        await trend_catalog.update_category(
            created["id"],
            old_version,
            title="Cannot persist",
            actor_id=ADMIN,
        )
    async with db_backend.connect(database.DATABASE_PATH) as db:
        row = await (
            await db.execute(
                "SELECT title, revision FROM trend_categories WHERE id = ?",
                (created["id"],),
            )
        ).fetchone()
    assert row[0] == "Safe"
    assert row[1] == old_version


@pytest.mark.asyncio
async def test_audit_rows_are_append_only_and_survive_repeat_migration():
    await trend_catalog.create_category("Do not erase history", "📁", actor_id=ADMIN)
    before = await trend_catalog_audit.list_history(limit=10)
    assert len(before) == 1
    audit_id = before[0]["id"]
    async with db_backend.connect(database.DATABASE_PATH) as db:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            await db.execute(
                "DELETE FROM trend_catalog_audit WHERE id = ?", (audit_id,)
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            await db.execute(
                "UPDATE trend_catalog_audit SET action = 'tampered' WHERE id = ?",
                (audit_id,),
            )
    await database.init_db()
    after = await trend_catalog_audit.list_history(limit=10)
    assert after == before


@pytest.mark.asyncio
async def test_audit_rejects_unknown_actor_without_applying_changes():
    with pytest.raises(ValueError, match="audit actor"):
        await trend_catalog.create_category("Not traceable", actor_id=-7)
    assert await trend_catalog.list_catalog(is_admin=True) == []
