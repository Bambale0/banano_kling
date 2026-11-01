"""Owner-scoped, explicitly saved personal reference folders."""

import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from bot import database
from bot import db as db_backend


def _name(value, *, maximum=80):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"Укажите название от 1 до {maximum} символов")
    return value.strip()


def _category_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Неверная категория")
    return value


@asynccontextmanager
async def _transaction(telegram_id):
    user = await database.get_or_create_user(telegram_id)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        await db.execute("BEGIN" if db_backend.is_postgres() else "BEGIN IMMEDIATE")
        if db_backend.is_postgres():
            await db.execute("SELECT id FROM users WHERE id = ? FOR UPDATE", (user.id,))
        yield db, user.id
        await db.commit()


async def require_category(db, user_id, category_id):
    category_id = _category_id(category_id)
    row = await (await db.execute(
        "SELECT id, name FROM reference_categories WHERE id = ? AND user_id = ?", (category_id, user_id),
    )).fetchone()
    if not row:
        raise PermissionError("Категория недоступна")
    return row


async def create_category(telegram_id, name):
    name = _name(name)
    async with _transaction(telegram_id) as (db, user_id):
        await db.execute(
            "INSERT INTO reference_categories(id, user_id, name, name_key) VALUES (?, ?, ?, ?) ON CONFLICT(user_id, name_key) DO NOTHING",
            (uuid.uuid4().hex, user_id, name, name.casefold()),
        )
        row = await (await db.execute(
            "SELECT id, name FROM reference_categories WHERE user_id = ? AND name_key = ?", (user_id, name.casefold()),
        )).fetchone()
    return {"id": row['id'], "name": row['name']}


async def list_categories(telegram_id):
    user = await database.get_or_create_user(telegram_id)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        rows = await (await db.execute(
            """SELECT c.id, c.name, COUNT(i.reference_id) AS item_count
               FROM reference_categories c LEFT JOIN reference_category_items i
               ON i.category_id = c.id AND i.user_id = c.user_id
               WHERE c.user_id = ? GROUP BY c.id, c.name ORDER BY c.name, c.id""", (user.id,),
        )).fetchall()
    return [{"id": row['id'], "name": row['name'], "count": row['item_count']} for row in rows]


async def rename_category(telegram_id, category_id, name):
    name = _name(name)
    async with _transaction(telegram_id) as (db, user_id):
        await require_category(db, user_id, category_id)
        duplicate = await (await db.execute(
            "SELECT id FROM reference_categories WHERE user_id = ? AND name_key = ? AND id <> ?",
            (user_id, name.casefold(), category_id),
        )).fetchone()
        if duplicate:
            raise ValueError("Категория с таким названием уже есть")
        await db.execute("UPDATE reference_categories SET name = ?, name_key = ? WHERE id = ? AND user_id = ?",
                         (name, name.casefold(), category_id, user_id))


async def delete_category(telegram_id, category_id):
    category_id = _category_id(category_id)
    async with _transaction(telegram_id) as (db, user_id):
        await db.execute("DELETE FROM reference_category_items WHERE category_id = ? AND user_id = ?", (category_id, user_id))
        await db.execute("DELETE FROM reference_categories WHERE id = ? AND user_id = ?", (category_id, user_id))


async def save_item_in_transaction(db, user_id, category_id, reference_id, title=None):
    await require_category(db, user_id, category_id)
    if title is not None:
        title = _name(title)
    row = await (await db.execute(
        "SELECT id FROM saved_references WHERE id = ? AND user_id = ?" + (" FOR UPDATE" if db_backend.is_postgres() else ""),
        (int(reference_id), user_id),
    )).fetchone()
    if not row:
        raise PermissionError("Референс недоступен. Загрузите его заново")
    await db.execute(
        """INSERT INTO reference_category_items(category_id, reference_id, user_id, title) VALUES (?, ?, ?, ?)
           ON CONFLICT(category_id, reference_id) DO UPDATE SET title = COALESCE(excluded.title, reference_category_items.title)""",
        (category_id, int(reference_id), user_id, title),
    )


async def save_item(telegram_id, category_id, reference_id, title=None):
    async with _transaction(telegram_id) as (db, user_id):
        await save_item_in_transaction(db, user_id, category_id, reference_id, title)


async def remove_item(telegram_id, category_id, reference_id):
    async with _transaction(telegram_id) as (db, user_id):
        await require_category(db, user_id, category_id)
        await db.execute("DELETE FROM reference_category_items WHERE category_id = ? AND reference_id = ? AND user_id = ?",
                         (category_id, int(reference_id), user_id))


def reference_payload(reference, title=None):
    return {"id": str(reference.id), "kind": reference.kind, "url": reference.file_url,
            "filename": reference.original_filename or Path(reference.file_url).name,
            "title": title or reference.original_filename or Path(reference.file_url).name,
            "available": database._saved_reference_is_available(reference)}


async def _category_rows(telegram_id, category_id, *, kind=None, offset=0, limit=40):
    user = await database.get_or_create_user(telegram_id)
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        await require_category(db, user.id, category_id)
        query = """SELECT sr.*, i.title FROM reference_category_items i JOIN saved_references sr
                   ON sr.id = i.reference_id AND sr.user_id = i.user_id
                   WHERE i.category_id = ? AND i.user_id = ?"""
        args = [category_id, user.id]
        if kind in {'image', 'video', 'audio'}:
            query += ' AND sr.kind = ?'
            args.append(kind)
        query += ' ORDER BY i.created_at DESC, sr.id DESC LIMIT ? OFFSET ?'
        rows = await (await db.execute(query, (*args, limit, offset))).fetchall()
    return rows


async def list_items(telegram_id, category_id, **options):
    rows = await _category_rows(telegram_id, category_id, **options)
    return [reference_payload(database._saved_reference_from_row(row), row['title']) for row in rows]


async def list_category_references(telegram_id, category_id, *, kind='image', limit=100, offset=0):
    rows = await _category_rows(telegram_id, category_id, kind=kind, limit=limit, offset=offset)
    references = [database._saved_reference_from_row(row) for row in rows]
    return [reference for reference in references if database._saved_reference_is_available(reference)]
