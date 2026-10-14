"""Category showcase lives beside, not inside, the private trend recipes."""

import pytest

from bot import database, trend_catalog


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
