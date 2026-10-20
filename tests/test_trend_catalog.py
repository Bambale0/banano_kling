"""Category showcase lives beside, not inside, the private trend recipes."""

import asyncio

import pytest

from bot import database, trend_catalog
from bot import db as db_backend


async def make_trend(number, *, kind="image"):
    user = await database.get_or_create_user(991001)
    prompt = await database.create_prompt(
        author_id=user.id,
        prompt_text=f"Private original scene {number}",
        title=f"Published scene {number}",
        category="video" if kind == "video" else "photo",
        model="seedance_2_5" if kind == "video" else "banana_pro",
        generation_settings={
            "kind": kind,
            "model": "seedance_2_5" if kind == "video" else "banana_pro",
            "user_fields": [
                {"key": "Возраст", "label": "Возраст", "original_value": "37"}
            ],
        },
        tags=["trend", "trend-video"] if kind == "video" else ["trend"],
        is_public=True,
    )
    return await database.approve_prompt(prompt["id"])


@pytest.mark.asyncio
async def test_categories_initially_expose_unassigned_trends_without_private_recipe():
    trend = await make_trend(1, kind="video")
    result = await trend_catalog.list_catalog(is_admin=False, per_category=6)
    assert len(result) == 1
    assert result[0]["id"] == "unassigned"
    assert result[0]["total"] == 1
    card = result[0]["items"][0]
    assert card["id"] == trend["id"]
    assert card["prompt_text"] == ""
    assert card["model"] is None
    assert "Private original" not in str(card)
    assert "original_value" not in str(card)


@pytest.mark.asyncio
async def test_create_assign_reorder_and_reuse_same_trend_without_cloning():
    a, b, c = [await make_trend(i) for i in range(3)]
    birthday = await trend_catalog.create_category("День рождения", "🎂")
    reels = await trend_catalog.create_category("Reels", "🎵")
    await trend_catalog.set_trend_categories(a["id"], [birthday["id"], reels["id"]])
    await trend_catalog.set_trend_categories(b["id"], [birthday["id"]])
    await trend_catalog.set_trend_categories(c["id"], [birthday["id"]])
    catalog = await trend_catalog.list_catalog(is_admin=False, per_category=10)
    assert [item["id"] for item in catalog] == [birthday["id"], reels["id"]]
    assert [item["id"] for item in catalog[0]["items"]] == [a["id"], b["id"], c["id"]]
    assert catalog[1]["items"][0]["id"] == a["id"]

    update = await trend_catalog.replace_category_items(
        birthday["id"], [c["id"], a["id"], b["id"]], revision=catalog[0]["revision"]
    )
    assert update["revision"] > catalog[0]["revision"]
    result = await trend_catalog.category_page(
        birthday["id"], is_admin=False, page=1, limit=2
    )
    assert [item["id"] for item in result["items"]] == [c["id"], a["id"]]
    assert result["has_more"]
    result2 = await trend_catalog.category_page(
        birthday["id"], is_admin=False, page=2, limit=2
    )
    assert [item["id"] for item in result2["items"]] == [b["id"]]
    with pytest.raises(trend_catalog.CatalogConflict):
        await trend_catalog.replace_category_items(
            birthday["id"], [a["id"]], revision=catalog[0]["revision"]
        )


@pytest.mark.asyncio
async def test_hidden_category_is_admin_only_and_restorable_without_deleting_trend():
    trend = await make_trend(3)
    cat = await trend_catalog.create_category("Липсинги", "🎵")
    await trend_catalog.set_trend_categories(trend["id"], [cat["id"]])
    revision = (await trend_catalog.list_catalog(is_admin=True))[0]["revision"]
    hidden = await trend_catalog.update_category(cat["id"], revision, is_visible=False)
    assert not await trend_catalog.list_catalog(is_admin=False)
    assert (await trend_catalog.list_catalog(is_admin=True))[0]["id"] == cat["id"]
    with pytest.raises(trend_catalog.CatalogNotFound):
        await trend_catalog.category_page(cat["id"], is_admin=False)
    assert (await trend_catalog.category_page(cat["id"], is_admin=True))["total"] == 1
    await trend_catalog.delete_category(cat["id"], hidden["revision"])
    result = await trend_catalog.list_catalog(is_admin=False)
    assert result[0]["id"] == "unassigned"
    assert result[0]["items"][0]["id"] == trend["id"]


@pytest.mark.asyncio
async def test_category_reorder_is_revision_guarded():
    first = await trend_catalog.create_category("Первый", "1️⃣")
    second = await trend_catalog.create_category("Второй", "2️⃣")
    order = [
        {"id": second["id"], "revision": second["revision"]},
        {"id": first["id"], "revision": first["revision"]},
    ]
    await trend_catalog.reorder_categories(order)
    assert [c["id"] for c in await trend_catalog.list_catalog(is_admin=True)] == [
        second["id"],
        first["id"],
    ]
    with pytest.raises(trend_catalog.CatalogConflict):
        await trend_catalog.reorder_categories(order)


@pytest.mark.asyncio
async def test_badges_can_expire_and_item_membership_is_idempotent():
    trend = await make_trend(5)
    category = await trend_catalog.create_category("Новые", "✨")
    await trend_catalog.set_trend_categories(trend["id"], [category["id"]])
    await trend_catalog.set_trend_categories(trend["id"], [category["id"]])
    result = (await trend_catalog.list_catalog(is_admin=True))[0]
    assert result["total"] == 1
    await trend_catalog.set_badge(
        category["id"],
        trend["id"],
        result["revision"],
        badge="new",
        badge_until="2000-01-01",
    )
    card = (await trend_catalog.list_catalog(is_admin=False))[0]["items"][0]
    assert not card.get("badge")
    current = (await trend_catalog.list_catalog(is_admin=True))[0]
    await trend_catalog.set_badge(
        category["id"], trend["id"], current["revision"], badge="new", badge_until=None
    )
    assert (await trend_catalog.list_catalog(is_admin=False))[0]["items"][0][
        "badge"
    ] == "new"


@pytest.mark.asyncio
async def test_deactivated_trend_does_not_appear_in_folder_and_old_links_unchanged():
    trend = await make_trend(8)
    category = await trend_catalog.create_category("Тематика", "📽")
    await trend_catalog.set_trend_categories(trend["id"], [category["id"]])
    await database.deactivate_prompt(trend["id"])
    assert not await trend_catalog.list_catalog(is_admin=False)
    admin = await trend_catalog.list_catalog(is_admin=True)
    assert admin[0]["total"] == 0
    assert (await database.get_prompt_by_id(trend["id"]))["id"] == trend["id"]


@pytest.mark.asyncio
async def test_reject_invalid_title_and_non_trend_membership():
    user = await database.get_or_create_user(991001)
    prompt = await database.create_prompt(
        author_id=user.id, prompt_text="ordinary", title="Ordinary", tags=["portrait"]
    )
    await database.approve_prompt(prompt["id"])
    category = await trend_catalog.create_category("Тест", "🎨")
    with pytest.raises(trend_catalog.CatalogValidationError):
        await trend_catalog.set_trend_categories(prompt["id"], [category["id"]])
    with pytest.raises(trend_catalog.CatalogValidationError):
        await trend_catalog.create_category("   ", "✗")
    with pytest.raises(trend_catalog.CatalogValidationError):
        await trend_catalog.create_category("a" * 90, "✗")


@pytest.mark.asyncio
async def test_atomic_move_preserves_trend_identity_and_rejects_stale_revisions():
    trend = await make_trend(77)
    source = await trend_catalog.create_category("Фото", "🖼️")
    target = await trend_catalog.create_category("Видео", "🎬")
    await trend_catalog.set_trend_categories(trend["id"], [source["id"]])
    categories = await trend_catalog.list_catalog(is_admin=True)
    original = next(cat for cat in categories if cat["id"] == source["id"])
    destination = next(cat for cat in categories if cat["id"] == target["id"])
    await trend_catalog.move_trend_between_categories(
        trend["id"],
        source["id"],
        target["id"],
        source_revision=original["revision"],
        target_revision=destination["revision"],
    )
    updated = await trend_catalog.list_catalog(is_admin=True)
    assert next(cat for cat in updated if cat["id"] == source["id"])["total"] == 0
    assert (
        next(cat for cat in updated if cat["id"] == target["id"])["items"][0]["id"]
        == trend["id"]
    )
    with pytest.raises(trend_catalog.CatalogConflict):
        await trend_catalog.move_trend_between_categories(
            trend["id"],
            target["id"],
            source["id"],
            source_revision=destination["revision"],
            target_revision=original["revision"],
        )


@pytest.fixture(autouse=True)
async def isolated_trend_metrics_database(isolated_database, monkeypatch):
    """Avoid frozen legacy metrics DB paths when the whole suite is collected.

    Global handler installers run during collection of other modules; each
    catalog test receives its own SQLite database via isolated_database.
    """
    from bot.handlers import trend_success_compat

    monkeypatch.setattr(trend_success_compat, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(trend_success_compat, "_SCHEMA_READY", False)


@pytest.mark.asyncio
async def test_repeated_schema_initialization_preserves_editorial_data():
    created = await trend_catalog.create_category("Осторожная миграция", "📁")
    await database.init_db()
    assert (
        next(
            cat
            for cat in await trend_catalog.list_catalog(is_admin=True)
            if cat["id"] == created["id"]
        )["title"]
        == "Осторожная миграция"
    )


@pytest.mark.asyncio
async def test_concurrent_membership_replacement_keeps_one_complete_requested_set():
    item = await make_trend(89)
    first = await trend_catalog.create_category("Первая", "✨")
    second = await trend_catalog.create_category("Вторая", "🎬")
    for _ in range(4):
        await asyncio.gather(
            trend_catalog.set_trend_categories(item["id"], [first["id"]]),
            trend_catalog.set_trend_categories(item["id"], [second["id"]]),
        )
        async with db_backend.connect(database.DATABASE_PATH) as db:
            cursor = await db.execute(
                "SELECT category_id FROM trend_category_items WHERE prompt_id = ?",
                (item["id"],),
            )
            assigned = {int(row[0]) for row in await cursor.fetchall()}
        assert assigned in ({first["id"]}, {second["id"]}), (
            "Do not union two replacements"
        )


@pytest.mark.asyncio
async def test_successful_repeat_counts_are_identical_in_folders_pages_and_admin_search():
    from bot.handlers import trend_success_compat as metrics

    first, second = await make_trend(301), await make_trend(302)
    category_a = await trend_catalog.create_category("Топовые повторы", "⭐")
    category_b = await trend_catalog.create_category("Популярное", "🔥")
    await trend_catalog.set_trend_categories(first["id"], [category_a["id"], category_b["id"]])
    await trend_catalog.set_trend_categories(second["id"], [category_a["id"]])
    user = await database.get_or_create_user(991001)
    cases = [
        ("completed_1", first["id"], "completed"),
        ("completed_2", first["id"], "completed"),
        ("failed_1", first["id"], "failed"),
        ("pending_1", first["id"], "pending"),
        ("processing_1", first["id"], "processing"),
        ("completed_unrelated", second["id"], "completed"),
    ]
    async with db_backend.connect(database.DATABASE_PATH) as db:
        for task, trend_id, status in cases:
            await db.execute(
                "INSERT INTO generation_tasks (user_id, telegram_id, task_id, type, preset_id, status) "
                "VALUES (?, ?, ?, 'video', 'test-trend', ?)",
                (user.id, user.telegram_id, task, status),
            )
        # accepted attempts are not completed generations
        await db.execute(
            "UPDATE user_prompts SET uses_count = 99 WHERE id = ?",
            (first["id"],),
        )
        await db.commit()

    for task, trend_id, status in cases:
        assert await metrics.register_trend_generation_run(
            task_id=task, trend_id=trend_id, user_id=user.id,
        )
    assert not await metrics.register_trend_generation_run(
        task_id="completed_1", trend_id=first["id"], user_id=user.id,
    )

    catalog = await trend_catalog.list_catalog(is_admin=True)
    all_cards = [card for folder in catalog for card in folder["items"]]
    repeated = [card for card in all_cards if card["id"] == first["id"]]
    assert len(repeated) == 2
    assert {card["successful_runs_count"] for card in repeated} == {2}
    assert {card["uses_count"] for card in repeated} == {99}
    assert next(card for card in all_cards if card["id"] == second["id"])["successful_runs_count"] == 1
    assert all(card["prompt_text"] == "" and card["model"] is None for card in all_cards)
    assert all("completed_1" not in str(card) for card in all_cards)

    pages = [await trend_catalog.category_page(category_a["id"], is_admin=True, page=page, limit=1)
             for page in (1, 2)]
    per_id = {card["id"]: card["successful_runs_count"] for page in pages for card in page["items"]}
    assert per_id == {first["id"]: 2, second["id"]: 1}
    admin = await trend_catalog.search_admin_trends(str(first["id"]))
    assert len(admin["items"]) == 1
    assert admin["items"][0]["successful_runs_count"] == 2


@pytest.mark.asyncio
async def test_zero_successes_are_explicit_not_guessed_from_accepted_launches():
    trend = await make_trend(303)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE user_prompts SET uses_count = 18 WHERE id = ?", (trend["id"],))
        await db.commit()
    card = (await trend_catalog.list_catalog(is_admin=True))[0]["items"][0]
    assert card["uses_count"] == 18
    assert card["successful_runs_count"] == 0


@pytest.mark.asyncio
async def test_viewer_catalog_pages_omit_statistics_without_querying_counts(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.handlers import trend_success_compat as metrics

    assigned, unassigned = await make_trend(401), await make_trend(402)
    category = await trend_catalog.create_category("Public category")
    await trend_catalog.set_trend_categories(assigned["id"], [category["id"]])
    query = AsyncMock(side_effect=AssertionError("Viewer must not query private statistics"))
    monkeypatch.setattr(metrics, "get_trend_success_counts", query)
    catalog = await trend_catalog.list_catalog()
    cards = [card for folder in catalog for card in folder["items"]]
    assert {card["id"] for card in cards} == {assigned["id"], unassigned["id"]}
    for category_id in (category["id"], "unassigned"):
        cards.extend((await trend_catalog.category_page(category_id))["items"])
    for card in cards:
        assert "successful_runs_count" not in card
        assert "uses_count" not in card
        assert card["title"]
        assert card["prompt_text"] == ""
    query.assert_not_awaited()
