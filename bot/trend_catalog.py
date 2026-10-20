"""Editorial folders for curated trends. Never stores or exposes executable recipes.

The taxonomy is independent from user_prompts.category (generation media kind).
Existing prompt ids, referral links, private assets and billing remain unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from bot import database
from bot import db as db_backend
from bot import trend_catalog_audit as audit
from bot.trend_visibility import sanitize_prompt_for_public


class CatalogValidationError(ValueError):
    pass


class CatalogNotFound(CatalogValidationError):
    pass


class CatalogConflict(CatalogValidationError):
    pass


# The existing main Trends screen excludes the separate Pinterest tool.
_PUBLIC_TREND_WHERE = """
    p.status = 'approved' AND p.is_public = 1
    AND LOWER(COALESCE(p.tags, '')) LIKE '%"trend"%'
    AND LOWER(COALESCE(p.tags, '')) NOT LIKE '%"pinterest"%'
    AND LOWER(COALESCE(p.tags, '')) NOT LIKE '%"pinterest-repeat"%'
    AND LOWER(COALESCE(p.tags, '')) NOT LIKE '%"repeat-pinterest"%'
    AND LOWER(COALESCE(p.title, '')) NOT LIKE '%pinterest%'
"""
_UNASSIGNED_FROM = (
    """
    FROM user_prompts p LEFT JOIN trend_category_items ti ON ti.prompt_id = p.id
    WHERE ti.prompt_id IS NULL AND
"""
    + _PUBLIC_TREND_WHERE
)
_MEMBER_FROM = (
    """
    FROM trend_category_items ti
    JOIN user_prompts p ON p.id = ti.prompt_id
    WHERE ti.category_id = ? AND
"""
    + _PUBLIC_TREND_WHERE
)


def _title(value: Any) -> str:
    result = " ".join(str(value or "").split())
    if not 1 <= len(result) <= 60:
        raise CatalogValidationError("Название категории: от 1 до 60 символов")
    return result


def _emoji(value: Any) -> str:
    result = str(value or "").strip()
    if len(result) > 16:
        raise CatalogValidationError("Эмодзи категории слишком длинный")
    return result


def _unique_ids(values: Any, *, maximum: int = 1000) -> list[int]:
    if not isinstance(values, list) or len(values) > maximum:
        raise CatalogValidationError("Передайте список идентификаторов")
    result: list[int] = []
    for value in values:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            or value in result
        ):
            raise CatalogValidationError("Некорректный или повторяющийся идентификатор")
        result.append(value)
    return result


def _positive_id(value: Any) -> int:
    if isinstance(value, bool):
        raise CatalogValidationError("Неверный идентификатор")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise CatalogValidationError("Неверный идентификатор") from exc
    if normalized <= 0:
        raise CatalogValidationError("Неверный идентификатор")
    return normalized


def _revision(value: Any) -> int:
    return _positive_id(value)


def _meta(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "title": str(row["title"]),
        "emoji": str(row["emoji"] or ""),
        "sort_order": int(row["sort_order"]),
        "is_visible": bool(row["is_visible"]),
        "revision": int(row["revision"]),
    }


async def _category_row(db: Any, category_id: int) -> Any:
    cursor = await db.execute(
        "SELECT * FROM trend_categories WHERE id = ?", (category_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise CatalogNotFound("Категория не найдена")
    return row


def _card(row: Any, *, tariff: str, is_admin: bool = False) -> dict[str, Any]:
    from bot.services.trend_preview_service import cached_trend_preview_assets
    from bot.trend_api import with_trend_repeat_cost

    raw = database._prompt_to_dict(database._row_to_user_prompt(row))
    if not raw:
        raise CatalogNotFound("Тренд не найден")
    priced = with_trend_repeat_cost(raw, tariff=tariff)
    public = sanitize_prompt_for_public(priced, include_repeat_stats=is_admin)
    # Always use the same public serializer, even for an administrative list.
    media = cached_trend_preview_assets(public.get("preview_url"))
    public["preview_url"] = media["preview_url"]
    public["preview_poster_url"] = media["preview_poster_url"]
    # sqlite3.Row.__contains__ checks VALUES, not keys: use column names explicitly.
    columns = set(row.keys())
    badge = str(row["showcase_badge"] or "") if "showcase_badge" in columns else ""
    expiry = (
        str(row["showcase_badge_until"] or "")
        if "showcase_badge_until" in columns
        else ""
    )
    if badge == "new" and (
        is_admin or not expiry or expiry >= datetime.now(UTC).date().isoformat()
    ):
        public["badge"] = badge
    if is_admin:
        public["badge_until"] = expiry or None
    return public


async def _attach_successful_repeat_counts(items: list[dict[str, Any]]) -> None:
    """Enrich an admin page once using the existing completed-task metric.

    The older Trends API already counts task-linked completed generations; the
    editorial category API had bypassed that enrichment entirely. Do not use
    user_prompts.uses_count, which includes accepted but ultimately failed runs.
    Keep one bulk query for all folders, including repeated placements.
    """
    if not items:
        return
    from bot.handlers.trend_success_compat import get_trend_success_counts

    counts = await get_trend_success_counts([int(item["id"]) for item in items])
    for item in items:
        item["successful_runs_count"] = counts.get(int(item["id"]), 0)


async def _list_page(
    db: Any,
    *,
    category_id: int | None,
    limit: int,
    offset: int,
    tariff: str,
    is_admin: bool = False,
) -> tuple[int, list[dict[str, Any]]]:
    clause = _UNASSIGNED_FROM if category_id is None else _MEMBER_FROM
    args: tuple[Any, ...] = () if category_id is None else (category_id,)
    cursor = await db.execute("SELECT COUNT(*) " + clause, args)
    row = await cursor.fetchone()
    total = int(row[0] or 0)
    if not total:
        return 0, []

    sort = (
        "p.created_at DESC, p.id DESC"
        if category_id is None
        else "ti.sort_order ASC, p.id ASC"
    )
    badge_cols = (
        "'' AS showcase_badge, '' AS showcase_badge_until"
        if category_id is None
        else "ti.badge AS showcase_badge, ti.badge_until AS showcase_badge_until"
    )
    cursor = await db.execute(
        "SELECT p.*, "
        + badge_cols
        + " "
        + clause
        + " ORDER BY "
        + sort
        + " LIMIT ? OFFSET ?",
        (*args, limit, offset),
    )
    rows = await cursor.fetchall()
    return total, [_card(item, tariff=tariff, is_admin=is_admin) for item in rows]


async def list_catalog(
    *, is_admin: bool = False, per_category: int = 6, tariff: str = "standard"
) -> list[dict[str, Any]]:
    limit = min(12, max(1, int(per_category)))
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        if is_admin:
            cursor = await db.execute(
                "SELECT * FROM trend_categories ORDER BY sort_order ASC, id ASC"
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM trend_categories WHERE is_visible = 1 ORDER BY sort_order ASC, id ASC"
            )
        categories = await cursor.fetchall()
        result = []
        for row in categories:
            total, items = await _list_page(
                db,
                category_id=int(row["id"]),
                limit=limit,
                offset=0,
                tariff=tariff,
                is_admin=is_admin,
            )
            if not total and not is_admin:
                continue
            result.append({**_meta(row), "total": total, "items": items})
        total, items = await _list_page(
            db,
            category_id=None,
            limit=limit,
            offset=0,
            tariff=tariff,
            is_admin=is_admin,
        )
        if total:
            result.append(
                {
                    "id": "unassigned",
                    "title": "Без категории" if is_admin else "Другие тренды",
                    "emoji": "✨",
                    "sort_order": 2147483647,
                    "is_visible": True,
                    "revision": 0,
                    "total": total,
                    "items": items,
                }
            )
    if is_admin:
        await _attach_successful_repeat_counts([
            item for category in result for item in category["items"]
        ])
    return result


async def category_page(
    category_id: int | str,
    *,
    is_admin: bool = False,
    page: int = 1,
    limit: int = 24,
    tariff: str = "standard",
) -> dict[str, Any]:
    safe_page = min(10000, max(1, int(page)))
    safe_limit = min(100, max(1, int(limit)))
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        if category_id == "unassigned":
            meta = {
                "id": "unassigned",
                "title": "Без категории" if is_admin else "Другие тренды",
                "emoji": "✨",
                "is_visible": True,
                "revision": 0,
            }
            key: int | None = None
        else:
            row = await _category_row(db, _positive_id(category_id))
            if not is_admin and not row["is_visible"]:
                raise CatalogNotFound("Категория недоступна")
            meta = _meta(row)
            key = int(row["id"])
        total, items = await _list_page(
            db,
            category_id=key,
            limit=safe_limit,
            offset=(safe_page - 1) * safe_limit,
            tariff=tariff,
            is_admin=is_admin,
        )
    if is_admin:
        await _attach_successful_repeat_counts(items)
    return {
        "category": meta,
        "items": items,
        "total": total,
        "page": safe_page,
        "has_more": safe_page * safe_limit < total,
    }


async def create_category(
    title: str, emoji: str = "", *, actor_id: int = 0
) -> dict[str, Any]:
    name, marker = _title(title), _emoji(emoji)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM trend_categories"
        )
        position = int((await cursor.fetchone())[0]) + 1
        cursor = await db.execute(
            "INSERT INTO trend_categories (title, emoji, sort_order) VALUES (?, ?, ?) RETURNING id",
            (name, marker, position),
        )
        new_id = int((await cursor.fetchone())[0])
        await audit.append(
            db,
            actor_id=actor_id,
            action="create",
            category_id=new_id,
            before=None,
            after=await audit.category_snapshot(db, new_id),
        )
        await db.commit()
        return _meta(await _category_row(db, new_id))


async def update_category(
    category_id: int,
    revision: int,
    *,
    title: str | None = None,
    emoji: str | None = None,
    is_visible: bool | None = None,
    actor_id: int = 0,
) -> dict[str, Any]:
    key = _positive_id(category_id)
    version = _revision(revision)
    if is_visible is not None and not isinstance(is_visible, bool):
        raise CatalogValidationError("Неверный параметр видимости")
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        current = await _category_row(db, key)
        before = await audit.category_snapshot(db, key)
        title_value = _title(title) if title is not None else current["title"]
        emoji_value = _emoji(emoji) if emoji is not None else current["emoji"]
        visible_value = (
            int(is_visible) if is_visible is not None else int(current["is_visible"])
        )
        cursor = await db.execute(
            "UPDATE trend_categories SET title = ?, emoji = ?, is_visible = ?, "
            "revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND revision = ?",
            (title_value, emoji_value, visible_value, key, version),
        )
        if cursor.rowcount != 1:
            raise CatalogConflict(
                "Категория была изменена другим администратором. Обновите страницу"
            )
        await audit.append(
            db,
            actor_id=actor_id,
            action="update",
            category_id=key,
            before=before,
            after=await audit.category_snapshot(db, key),
        )
        await db.commit()
        return _meta(await _category_row(db, key))


async def delete_category(
    category_id: int, revision: int, *, actor_id: int = 0
) -> None:
    key = _positive_id(category_id)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await _category_row(db, key)
        before = await audit.category_snapshot(db, key, include_items=True)
        cursor = await db.execute(
            "DELETE FROM trend_categories WHERE id = ? AND revision = ?",
            (key, _revision(revision)),
        )
        if cursor.rowcount != 1:
            raise CatalogConflict("Категория была изменена. Обновите страницу")
        await audit.append(
            db,
            actor_id=actor_id,
            action="delete",
            category_id=key,
            before=before,
            after=None,
        )
        await db.commit()


async def reorder_categories(
    ordered: list[Mapping[str, Any]], *, actor_id: int = 0
) -> list[dict[str, Any]]:
    if not isinstance(ordered, list) or not ordered or len(ordered) > 1000:
        raise CatalogValidationError("Нужен непустой порядок категорий")
    if any(not isinstance(item, Mapping) for item in ordered):
        raise CatalogValidationError("Неверный формат порядка категорий")
    ids = _unique_ids([item.get("id") for item in ordered])
    versions = [_revision(item.get("revision")) for item in ordered]
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        if db_backend.is_postgres():
            # The incoming order differs between editors. Acquire all row
            # locks in a stable primary-key order BEFORE updating positions to
            # prevent reverse-order transactions from deadlocking.
            cursor = await db.execute(
                "SELECT id FROM trend_categories ORDER BY id ASC FOR UPDATE"
            )
        else:
            # SQLite has a single writer: lock before reading category revisions.
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT id FROM trend_categories ORDER BY id ASC")
        rows = await cursor.fetchall()
        if set(ids) != {int(row[0]) for row in rows}:
            raise CatalogConflict("Список категорий изменился. Обновите страницу")
        before = await audit.categories_snapshot(db)
        result = []
        for position, (key, version) in enumerate(zip(ids, versions)):
            cursor = await db.execute(
                "UPDATE trend_categories SET sort_order = ?, revision = revision + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND revision = ?",
                (position, key, version),
            )
            if cursor.rowcount != 1:
                raise CatalogConflict("Порядок уже изменился. Обновите страницу")
            result.append(_meta(await _category_row(db, key)))
        await audit.append(
            db,
            actor_id=actor_id,
            action="reorder",
            before=before,
            after=await audit.categories_snapshot(db),
        )
        await db.commit()
        return result


async def _verify_trends(db: Any, ids: list[int]) -> None:
    if not ids:
        return
    markers = ",".join("?" for _ in ids)
    cursor = await db.execute(
        "SELECT COUNT(*) FROM user_prompts p WHERE p.id IN ("
        + markers
        + ") AND "
        + _PUBLIC_TREND_WHERE,
        tuple(ids),
    )
    if int((await cursor.fetchone())[0]) != len(ids):
        raise CatalogValidationError(
            "Выбраны удалённые, неопубликованные или недоступные тренды"
        )


async def replace_category_items(
    category_id: int, trend_ids: list[int], *, revision: int, actor_id: int = 0
) -> dict[str, Any]:
    key = _positive_id(category_id)
    ids = _unique_ids(trend_ids)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        await _category_row(db, key)
        before = await audit.category_snapshot(db, key, include_items=True)
        cursor = await db.execute(
            "UPDATE trend_categories SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND revision = ?",
            (key, _revision(revision)),
        )
        if cursor.rowcount != 1:
            raise CatalogConflict("Состав категории уже изменился. Обновите страницу")
        await _verify_trends(db, ids)
        existing = await (
            await db.execute(
                "SELECT prompt_id, badge, badge_until FROM trend_category_items WHERE category_id = ?",
                (key,),
            )
        ).fetchall()
        badges = {
            int(item["prompt_id"]): (item["badge"], item["badge_until"])
            for item in existing
        }
        await db.execute(
            "DELETE FROM trend_category_items WHERE category_id = ?", (key,)
        )
        for order, prompt_id in enumerate(ids):
            badge, expiry = badges.get(prompt_id, ("", None))
            await db.execute(
                "INSERT INTO trend_category_items (category_id, prompt_id, sort_order, badge, badge_until) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, prompt_id, order, badge, expiry),
            )
        await audit.append(
            db,
            actor_id=actor_id,
            action="set_items",
            category_id=key,
            before=before,
            after=await audit.category_snapshot(db, key, include_items=True),
        )
        await db.commit()
        return _meta(await _category_row(db, key))


async def set_trend_categories(
    trend_id: int, category_ids: list[int], *, actor_id: int = 0
) -> None:
    """Atomically replace one existing trend's folder memberships, preserving item order."""
    key, wanted = _positive_id(trend_id), _unique_ids(category_ids)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        # Serialize full-set replacement on a stable parent row before reading
        # memberships. Locking individual category rows is insufficient: two
        # concurrent replacements may otherwise leave a union of both sets.
        if db_backend.is_postgres():
            await db.execute(
                "SELECT id FROM user_prompts WHERE id = ? FOR UPDATE", (key,)
            )
        else:
            await db.execute("BEGIN IMMEDIATE")
        await _verify_trends(db, [key])
        before = await audit.memberships_snapshot(db, key)
        if wanted:
            placeholders = ",".join("?" for _ in wanted)
            present = await (
                await db.execute(
                    "SELECT id FROM trend_categories WHERE id IN ("
                    + placeholders
                    + ")",
                    tuple(wanted),
                )
            ).fetchall()
            if len(present) != len(wanted):
                raise CatalogValidationError("Одна из категорий больше не существует")
        existing = await (
            await db.execute(
                "SELECT category_id FROM trend_category_items WHERE prompt_id = ?",
                (key,),
            )
        ).fetchall()
        current = {int(row[0]) for row in existing}
        for cat_id in sorted(current - set(wanted)):
            await db.execute(
                "DELETE FROM trend_category_items WHERE category_id = ? AND prompt_id = ?",
                (cat_id, key),
            )
            await db.execute(
                "UPDATE trend_categories SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (cat_id,),
            )
        for cat_id in sorted(set(wanted) - current):
            # Lock category row first: concurrent publishers cannot reuse its next position.
            await db.execute(
                "UPDATE trend_categories SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (cat_id,),
            )
            next_position = await (
                await db.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM trend_category_items WHERE category_id = ?",
                    (cat_id,),
                )
            ).fetchone()
            await db.execute(
                "INSERT INTO trend_category_items (category_id, prompt_id, sort_order) VALUES (?, ?, ?)",
                (cat_id, key, int(next_position[0])),
            )
        await audit.append(
            db,
            actor_id=actor_id,
            action="set_trend_categories",
            trend_id=key,
            before=before,
            after=await audit.memberships_snapshot(db, key),
        )
        await db.commit()


async def move_trend_between_categories(
    trend_id: int,
    source_id: int,
    target_id: int,
    *,
    source_revision: int,
    target_revision: int,
    actor_id: int = 0,
) -> None:
    """Atomic move; revisions are locked in category-id order to avoid deadlocks."""
    key, source, target = (
        _positive_id(trend_id),
        _positive_id(source_id),
        _positive_id(target_id),
    )
    if source == target:
        raise CatalogValidationError("Выберите другую категорию")
    versions = {source: _revision(source_revision), target: _revision(target_revision)}
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await _verify_trends(db, [key])
        before = await audit.memberships_snapshot(db, key)
        for cat_id in sorted(versions):
            await _category_row(db, cat_id)
            cursor = await db.execute(
                "UPDATE trend_categories SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND revision = ?",
                (cat_id, versions[cat_id]),
            )
            if cursor.rowcount != 1:
                raise CatalogConflict("Категории были изменены. Обновите страницу")
        cursor = await db.execute(
            "SELECT 1 FROM trend_category_items WHERE category_id = ? AND prompt_id = ?",
            (source, key),
        )
        if not await cursor.fetchone():
            raise CatalogNotFound("Тренд отсутствует в исходной категории")
        cursor = await db.execute(
            "SELECT 1 FROM trend_category_items WHERE category_id = ? AND prompt_id = ?",
            (target, key),
        )
        if not await cursor.fetchone():
            cursor = await db.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM trend_category_items WHERE category_id = ?",
                (target,),
            )
            position = int((await cursor.fetchone())[0])
            await db.execute(
                "INSERT INTO trend_category_items(category_id, prompt_id, sort_order) VALUES (?, ?, ?)",
                (target, key, position),
            )
        await db.execute(
            "DELETE FROM trend_category_items WHERE category_id = ? AND prompt_id = ?",
            (source, key),
        )
        await audit.append(
            db,
            actor_id=actor_id,
            action="move_item",
            category_id=source,
            trend_id=key,
            before={"target_category_id": target, "memberships": before},
            after={
                "target_category_id": target,
                "memberships": await audit.memberships_snapshot(db, key),
            },
        )
        await db.commit()


async def set_badge(
    category_id: int,
    trend_id: int,
    revision: int,
    *,
    badge: str = "",
    badge_until: str | None = None,
    actor_id: int = 0,
) -> dict[str, Any]:
    key, item_id = _positive_id(category_id), _positive_id(trend_id)
    if badge not in {"", "new"}:
        raise CatalogValidationError("Поддерживается только бейдж Новинка")
    if badge_until:
        if not isinstance(badge_until, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", badge_until
        ):
            raise CatalogValidationError("Дата должна быть в формате ГГГГ-ММ-ДД")
        try:
            date.fromisoformat(badge_until)
        except ValueError as exc:
            raise CatalogValidationError("Неверная дата") from exc
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        await _category_row(db, key)
        before = await audit.category_snapshot(db, key, include_items=True)
        cursor = await db.execute(
            "UPDATE trend_categories SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND revision = ?",
            (key, _revision(revision)),
        )
        if cursor.rowcount != 1:
            raise CatalogConflict("Категория уже была изменена. Обновите страницу")
        cursor = await db.execute(
            "UPDATE trend_category_items SET badge = ?, badge_until = ? "
            "WHERE category_id = ? AND prompt_id = ?",
            (badge, badge_until if badge else None, key, item_id),
        )
        if cursor.rowcount != 1:
            raise CatalogNotFound("Тренд больше не находится в этой категории")
        await audit.append(
            db,
            actor_id=actor_id,
            action="set_badge",
            category_id=key,
            trend_id=item_id,
            before=before,
            after=await audit.category_snapshot(db, key, include_items=True),
        )
        await db.commit()
        return _meta(await _category_row(db, key))


async def search_admin_trends(
    query: str = "", *, page: int = 1, limit: int = 24, tariff: str = "standard"
) -> dict[str, Any]:
    page = min(10000, max(1, int(page)))
    limit = min(60, max(1, int(limit)))
    query = str(query or "").strip()[:100]
    where = _PUBLIC_TREND_WHERE
    params: list[Any] = []
    if query:
        # Escape SQL wildcards so a search is literal, not an accidental full-table scan.
        escaped = (
            query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        where += " AND (LOWER(p.title) LIKE ? ESCAPE '\\' OR p.id = ?)"
        params.extend(
            [
                "%" + escaped + "%",
                int(query) if query.isdecimal() and len(query) < 19 else -1,
            ]
        )
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        result = await (
            await db.execute(
                "SELECT COUNT(*) FROM user_prompts p WHERE " + where, tuple(params)
            )
        ).fetchone()
        total = int(result[0] or 0)
        rows = await (
            await db.execute(
                "SELECT p.*, '' AS showcase_badge, '' AS showcase_badge_until FROM user_prompts p WHERE "
                + where
                + " ORDER BY p.created_at DESC, p.id DESC LIMIT ? OFFSET ?",
                (*params, limit, (page - 1) * limit),
            )
        ).fetchall()
    items = [_card(row, tariff=tariff, is_admin=True) for row in rows]
    await _attach_successful_repeat_counts(items)
    return {
        "items": items,
        "total": total,
        "page": page,
        "has_more": page * limit < total,
    }
