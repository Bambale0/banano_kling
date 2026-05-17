import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl

from aiohttp import web

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("TWOLOOP_DATA_DIR", "/root/2loop/data"))
PUBLIC_STATIC_ROOT = Path(os.getenv("TWOLOOP_STATIC_ROOT", "/var/www/2loop/static"))
_upload_dir_raw = Path(os.getenv("TWOLOOP_UPLOAD_DIR", "uploads/2loop"))
if _upload_dir_raw.is_absolute():
    UPLOAD_DIR = _upload_dir_raw
elif _upload_dir_raw.parts and _upload_dir_raw.parts[0] == "static":
    UPLOAD_DIR = PUBLIC_STATIC_ROOT / Path(*_upload_dir_raw.parts[1:])
else:
    UPLOAD_DIR = PUBLIC_STATIC_ROOT / _upload_dir_raw
PRODUCTS_FILE = DATA_DIR / "products.json"
ORDERS_FILE = DATA_DIR / "orders.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
MINIAPP_TASKS_FILE = DATA_DIR / "miniapp_generation_tasks.json"
MINIAPP_HISTORY_FILE = DATA_DIR / "miniapp_generation_history.json"

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
VERIFY_INIT_DATA = os.getenv("TWOLOOP_VERIFY_INIT_DATA", "1") == "1"
_DB_INIT_ATTEMPTED = False

MINIAPP_ADMIN_IDS = {
    x.strip()
    for x in os.getenv("TWOLOOP_ADMIN_IDS", os.getenv("ADMIN_IDS", "")).split(",")
    if x.strip()
}

ORDER_NOTIFY_CHAT_IDS = {
    x.strip()
    for x in os.getenv(
        "TWOLOOP_ORDER_NOTIFY_CHAT_IDS", os.getenv("ADMIN_IDS", "")
    ).split(",")
    if x.strip()
}

DEFAULT_PRODUCTS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "article": "2LOOP-001",
        "name": "Crystal Hair Loop",
        "category": "Hair",
        "price": 2900,
        "stock": 12,
        "badge": "Bestseller",
        "description": "A refined crystal hair accessory for competition-ready styling.",
        "details": "Hand-finished shine, lightweight hold, suitable for competition hairstyles.",
        "images": [],
        "mainImageIndex": 0,
        "active": True,
    }
]

DEFAULT_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "product-photo",
        "title": "Product photo",
        "description": "Clean product visual for marketplace cards and social posts.",
        "type": "image",
        "cost": 1,
        "model": "local-demo",
        "aspectRatios": ["1:1", "4:5", "9:16"],
    },
    {
        "id": "dance-look",
        "title": "Dance look",
        "description": "Competition-ready styling and accessory promo concept.",
        "type": "image",
        "cost": 1,
        "model": "local-demo",
        "aspectRatios": ["4:5", "9:16"],
    },
    {
        "id": "smm-caption",
        "title": "SMM caption",
        "description": "Short social-media copy with CTA and hashtags.",
        "type": "text",
        "cost": 0,
        "model": "local-demo",
    },
]

MINIAPP_GENERATION_COSTS = {
    "content": 15,
    "image": 30,
    "video": 60,
    "tryon": 45,
    "prompt": 5,
    "smm": 0,
}


class MiniappBillingError(Exception):
    pass


def _ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    if not PRODUCTS_FILE.exists():
        _write_json(PRODUCTS_FILE, DEFAULT_PRODUCTS)

    if not ORDERS_FILE.exists():
        _write_json(ORDERS_FILE, [])

    if not SETTINGS_FILE.exists():
        _write_json(SETTINGS_FILE, {"theme": "dark", "brand": "2loop"})

    if not MINIAPP_TASKS_FILE.exists():
        _write_json(MINIAPP_TASKS_FILE, [])

    if not MINIAPP_HISTORY_FILE.exists():
        _write_json(MINIAPP_HISTORY_FILE, [])


def _read_json(path: Path, fallback: Any) -> Any:
    _ensure_storage()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read %s", path)
        return fallback


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _json(data: Any, status: int = 200) -> web.Response:
    return web.json_response(
        data,
        status=status,
        dumps=lambda value: json.dumps(value, ensure_ascii=False),
    )


def _next_id(items: List[Dict[str, Any]]) -> int:
    return max([int(item.get("id", 0)) for item in items] or [0]) + 1


def _normalize_product(
    payload: Dict[str, Any], product_id: Optional[int] = None
) -> Dict[str, Any]:
    images = payload.get("images") or []
    if not isinstance(images, list):
        images = []

    main_idx = int(payload.get("mainImageIndex", 0) or 0)

    if images:
        main_idx = max(0, min(main_idx, len(images) - 1))
    else:
        main_idx = 0

    return {
        "id": int(product_id or payload.get("id") or 0),
        "article": str(payload.get("article") or "").strip(),
        "name": str(payload.get("name") or "New Product").strip(),
        "category": str(payload.get("category") or "Other").strip(),
        "price": float(payload.get("price") or 0),
        "stock": int(payload.get("stock") or 0),
        "badge": str(payload.get("badge") or "").strip(),
        "description": str(payload.get("description") or "").strip(),
        "details": str(payload.get("details") or "").strip(),
        "images": images,
        "mainImageIndex": main_idx,
        "active": bool(payload.get("active", True)),
    }


def _parse_init_data(init_data: str) -> Optional[Dict[str, Any]]:
    if not init_data:
        return None

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)

    if VERIFY_INIT_DATA:
        if not BOT_TOKEN or not received_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(parsed.items())
        )
        secret_key = hmac.new(
            b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256
        ).digest()
        calculated_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

    user = None

    if parsed.get("user"):
        try:
            user = json.loads(parsed["user"])
        except Exception:
            user = None

    return {"raw": parsed, "user": user}


def _telegram_user(request: web.Request) -> Optional[Dict[str, Any]]:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    parsed = _parse_init_data(init_data)
    return parsed.get("user") if parsed else None


def _is_admin(request: web.Request) -> bool:
    if not MINIAPP_ADMIN_IDS:
        return os.getenv("TWOLOOP_ALLOW_OPEN_ADMIN", "0").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    user = _telegram_user(request)
    return bool(user and str(user.get("id")) in MINIAPP_ADMIN_IDS)


def _require_admin(request: web.Request) -> Optional[web.Response]:
    if _is_admin(request):
        return None

    return _json({"error": "admin_required"}, 403)


def _miniapp_admin_only() -> bool:
    return os.getenv("TWOLOOP_MINIAPP_ADMIN_ONLY", "1").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _gate_miniapp(handler, *, public: bool = False):
    async def wrapped(request: web.Request) -> web.Response:
        if _miniapp_admin_only() and not public:
            denied = _require_admin(request)
            if denied:
                return denied
        return await handler(request)

    return wrapped


def _require_user(request: web.Request) -> Optional[Dict[str, Any]]:
    """Return authenticated Telegram user or None.

    Miniapp generation endpoints must be callable by frontend automation without an
    operator, but still require validated Telegram init data when verification is
    enabled. Tests/local automation can disable verification with
    TWOLOOP_VERIFY_INIT_DATA=0, matching the existing auth behavior.
    """
    return _telegram_user(request)


async def _read_request_json(request: web.Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


async def _get_account_context(telegram_user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    global _DB_INIT_ATTEMPTED

    telegram_id = _safe_int((telegram_user or {}).get("id"))
    if not telegram_id:
        return {
            "balanceGoe": 0,
            "stats": {"generations": 0, "total_spent": 0, "tasks": 0},
            "source": "anonymous",
        }

    try:
        from bot.database import get_or_create_user, get_user_stats, init_db

        if not _DB_INIT_ATTEMPTED:
            await init_db()
            _DB_INIT_ATTEMPTED = True

        user = await get_or_create_user(telegram_id)
        stats = await get_user_stats(telegram_id)
        return {
            "userId": user.id,
            "balanceGoe": int(user.credits or 0),
            "stats": stats,
            "source": "sqlite",
        }
    except Exception:
        logger.warning("Using JSON fallback for GOE account context", exc_info=True)
        user_tasks = _filter_user_items(_read_json(MINIAPP_TASKS_FILE, []), telegram_id)
        total_spent = sum(_safe_int(item.get("cost")) for item in user_tasks)
        return {
            "balanceGoe": 0,
            "stats": {
                "generations": len(user_tasks),
                "tasks": len(user_tasks),
                "total_spent": total_spent,
            },
            "source": "json_fallback",
        }


def _filter_user_items(items: List[Dict[str, Any]], telegram_id: int) -> List[Dict[str, Any]]:
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if _safe_int(item.get("telegramId")) == telegram_id:
            result.append(item)
    return result


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _find_preset(preset_id: str) -> Dict[str, Any]:
    return next(
        (preset for preset in DEFAULT_PRESETS if preset["id"] == preset_id),
        DEFAULT_PRESETS[0],
    )


def _build_demo_result(
    *,
    prompt: str,
    preset: Dict[str, Any],
    kind: str,
    aspect_ratio: str,
) -> Dict[str, Any]:
    digest = hashlib.sha256(
        f"{kind}|{preset.get('id')}|{aspect_ratio}|{prompt}".encode("utf-8")
    ).hexdigest()[:16]
    if kind in {"smm", "prompt", "content"}:
        if kind == "prompt":
            caption = (
                "Улучшенный промпт 2Loop:\n"
                f"{prompt.strip()}\n\n"
                "Стиль: ледяной premium, динамика фигурного катания, чистый фон, понятный коммерческий акцент, "
                "готово для генерации фото/видео и публикации."
            )
        elif kind == "content":
            caption = (
                f"❄️ {prompt.strip()}\n\n"
                "Хук: покажите движение, эмоцию и одну сильную деталь образа.\n"
                "Текст: 2Loop автоматически собирает идею в готовый контент для фигурного катания.\n"
                "CTA: создайте следующий материал в боте за GOE."
            )
        else:
            caption = (
                f"{prompt.strip()} — стильный акцент 2loop для уверенного образа. "
                "Сохраните идею и создайте следующий материал в 2Loop за GOE."
            )
        return {
            "type": "text",
            "provider": "local-demo",
            "text": caption,
            "plan": "\n".join(
                [
                    "1. Хук: ледяная деталь и понятная польза.",
                    "2. Экспертный блок: короткий чек-лист для фигуристов.",
                    "3. CTA: создать следующий материал в 2Loop за GOE.",
                ]
            ),
            "caption": caption,
            "hashtags": ["#2loop", "#dancewear", "#style", "#handmade"],
            "variants": [
                caption,
                f"2loop idea: {prompt.strip()}. Лаконично, заметно, готово к выступлению.",
            ],
            "signature": digest,
        }
    media_type = "video" if kind == "video" else "image"
    ext = "mp4" if media_type == "video" else "png"
    return {
        "type": media_type,
        "provider": "local-demo",
        "url": f"/static/miniapp/demo/{digest}.{ext}",
        "previewUrl": f"/static/miniapp/demo/{digest}.png",
        "description": f"Demo {kind} result for: {prompt.strip()}",
        "signature": digest,
    }



async def _ensure_unified_db() -> bool:
    """Ensure Mini App uses the same SQLite DB as the Telegram bot."""
    try:
        import aiosqlite
        from bot.database import DATABASE_PATH, init_db
        await init_db()
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS miniapp_products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article TEXT UNIQUE,
                    name TEXT NOT NULL,
                    category TEXT DEFAULT 'Other',
                    price REAL DEFAULT 0,
                    stock INTEGER DEFAULT 0,
                    badge TEXT,
                    description TEXT,
                    details TEXT,
                    images TEXT DEFAULT '[]',
                    main_image_index INTEGER DEFAULT 0,
                    active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS miniapp_generation_results (
                    task_id TEXT PRIMARY KEY,
                    telegram_id INTEGER,
                    result_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS miniapp_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    status TEXT DEFAULT 'new',
                    customer TEXT,
                    delivery TEXT,
                    items TEXT NOT NULL,
                    subtotal REAL DEFAULT 0,
                    delivery_price REAL DEFAULT 0,
                    total REAL DEFAULT 0,
                    comment TEXT,
                    raw_payload TEXT,
                    created_at INTEGER NOT NULL
                )
            """)
            cursor = await db.execute("SELECT COUNT(*) FROM miniapp_products")
            count = (await cursor.fetchone())[0]
            if count == 0:
                for product in DEFAULT_PRODUCTS:
                    n = _normalize_product(product, None)
                    await db.execute(
                        """INSERT INTO miniapp_products
                           (article, name, category, price, stock, badge, description, details, images, main_image_index, active)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            n["article"], n["name"], n["category"], n["price"], n["stock"],
                            n["badge"], n["description"], n["details"], json.dumps(n["images"], ensure_ascii=False),
                            n["mainImageIndex"], 1 if n["active"] else 0,
                        ),
                    )
            await db.commit()
        return True
    except Exception:
        logger.warning("Unified SQLite miniapp DB unavailable; falling back to JSON files", exc_info=True)
        return False


def _row_to_product(row: Any) -> Dict[str, Any]:
    keys = row.keys() if hasattr(row, "keys") else []
    images_raw = row["images"] if "images" in keys else "[]"
    try:
        images = json.loads(images_raw or "[]")
    except Exception:
        images = []
    return {
        "id": int(row["id"]),
        "article": row["article"] or f"2LOOP-{int(row['id']):03d}",
        "name": row["name"],
        "category": row["category"] or "Other",
        "price": float(row["price"] or 0),
        "stock": int(row["stock"] or 0),
        "badge": row["badge"] or "",
        "description": row["description"] or "",
        "details": row["details"] or "",
        "images": images if isinstance(images, list) else [],
        "mainImageIndex": int(row["main_image_index"] or 0),
        "active": bool(row["active"]),
    }


async def _db_list_products(include_inactive: bool = False) -> Optional[List[Dict[str, Any]]]:
    if not await _ensure_unified_db():
        return None
    import aiosqlite
    from bot.database import DATABASE_PATH
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        sql = "SELECT * FROM miniapp_products"
        params = []
        if not include_inactive:
            sql += " WHERE active = 1"
        sql += " ORDER BY id DESC"
        cursor = await db.execute(sql, params)
        return [_row_to_product(row) for row in await cursor.fetchall()]


async def _db_upsert_product(payload: Dict[str, Any], product_id: Optional[int] = None) -> Dict[str, Any]:
    import aiosqlite
    from bot.database import DATABASE_PATH
    await _ensure_unified_db()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        if product_id:
            cursor = await db.execute("SELECT * FROM miniapp_products WHERE id = ?", (product_id,))
            old = await cursor.fetchone()
            if not old:
                raise KeyError("product_not_found")
            merged = {**_row_to_product(old), **payload, "id": product_id}
            n = _normalize_product(merged, product_id)
            await db.execute(
                """UPDATE miniapp_products SET article=?, name=?, category=?, price=?, stock=?, badge=?,
                   description=?, details=?, images=?, main_image_index=?, active=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (n["article"] or f"2LOOP-{product_id:03d}", n["name"], n["category"], n["price"], n["stock"], n["badge"],
                 n["description"], n["details"], json.dumps(n["images"], ensure_ascii=False), n["mainImageIndex"],
                 1 if n["active"] else 0, product_id),
            )
        else:
            n = _normalize_product(payload, None)
            await db.execute(
                """INSERT INTO miniapp_products (article, name, category, price, stock, badge, description, details, images, main_image_index, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (n["article"] or None, n["name"], n["category"], n["price"], n["stock"], n["badge"], n["description"],
                 n["details"], json.dumps(n["images"], ensure_ascii=False), n["mainImageIndex"], 1 if n["active"] else 0),
            )
            product_id = (await (await db.execute("SELECT last_insert_rowid() AS id")).fetchone())["id"]
            if not n["article"]:
                n["article"] = f"2LOOP-{int(product_id):03d}"
                await db.execute("UPDATE miniapp_products SET article=? WHERE id=?", (n["article"], product_id))
        await db.commit()
        cursor = await db.execute("SELECT * FROM miniapp_products WHERE id = ?", (product_id,))
        return _row_to_product(await cursor.fetchone())


async def _db_delete_product(product_id: int) -> bool:
    if not await _ensure_unified_db():
        return False
    import aiosqlite
    from bot.database import DATABASE_PATH
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute("DELETE FROM miniapp_products WHERE id=?", (product_id,))
        await db.commit()
        return cur.rowcount > 0


async def _db_store_generation_item(item: Dict[str, Any]) -> bool:
    try:
        if not await _ensure_unified_db():
            return False
        from bot.database import add_generation_history, add_generation_task, complete_video_task, deduct_credits, get_or_create_user, track_event
        user = await get_or_create_user(int(item["telegramId"]))
        cost = _safe_int(item.get("cost"))
        if cost > 0:
            deducted = await deduct_credits(user.telegram_id, cost, check_balance=True)
            if not deducted:
                raise MiniappBillingError("not_enough_goe")
        await add_generation_task(
            user.id, user.telegram_id, item["taskId"], item["type"], item.get("presetId") or item["type"],
            item.get("model"), item.get("duration"), item.get("aspectRatio"), item.get("prompt"), cost,
        )
        await complete_video_task(item["taskId"], item.get("resultUrl") or item.get("result", {}).get("url") or "")
        await add_generation_history(user.id, item.get("presetId") or item["type"], item.get("prompt") or "", cost)
        import aiosqlite
        from bot.database import DATABASE_PATH
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO miniapp_generation_results (task_id, telegram_id, result_json) VALUES (?, ?, ?)",
                (item["taskId"], user.telegram_id, json.dumps(item, ensure_ascii=False, default=str)),
            )
            await db.commit()
        await track_event(user.telegram_id, "miniapp_generate", {"type": item["type"], "task_id": item["taskId"], "cost": cost})
        return True
    except MiniappBillingError:
        raise
    except Exception:
        logger.warning("Failed to store miniapp generation in unified DB", exc_info=True)
        return False


async def _db_list_generation_items(telegram_id: int, limit: int) -> Optional[List[Dict[str, Any]]]:
    if not await _ensure_unified_db():
        return None
    import aiosqlite
    from bot.database import DATABASE_PATH
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT gt.*, gh.id AS history_id, mgr.result_json
               FROM generation_tasks gt
               LEFT JOIN generation_history gh ON gh.user_id = gt.user_id AND gh.preset_id = gt.preset_id AND gh.prompt = gt.prompt
               LEFT JOIN miniapp_generation_results mgr ON mgr.task_id = gt.task_id
               WHERE gt.telegram_id = ?
               ORDER BY gt.created_at DESC
               LIMIT ?""",
            (telegram_id, limit),
        )
        items = []
        for row in await cursor.fetchall():
            stored = {}
            try:
                stored = json.loads(row["result_json"] or "{}")
            except Exception:
                stored = {}
            result = stored.get("result") or {"type": row["type"], "url": row["result_url"], "text": row["result_url"] if row["type"] in {"smm", "prompt", "content"} else ""}
            items.append({
                "id": row["task_id"], "taskId": row["task_id"], "telegramId": row["telegram_id"],
                "type": row["type"], "kind": row["type"], "presetId": row["preset_id"], "title": row["prompt"],
                "prompt": row["prompt"], "model": row["model"], "duration": row["duration"], "aspectRatio": row["aspect_ratio"],
                "cost": row["cost"] or 0, "status": row["status"], "resultUrl": row["result_url"], "result": result,
                "text": result.get("text") or result.get("caption") or result.get("description"),
                "createdAt": row["created_at"], "completedAt": row["completed_at"] if "completed_at" in row.keys() else None,
            })
        return items


async def _db_store_order(order: Dict[str, Any]) -> bool:
    try:
        import aiosqlite
        from bot.database import DATABASE_PATH
        await _ensure_unified_db()
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """INSERT INTO miniapp_orders (telegram_id, status, customer, delivery, items, subtotal, delivery_price, total, comment, raw_payload, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_safe_int((order.get("telegramUser") or {}).get("id")), order.get("status", "new"),
                 json.dumps(order.get("customer") or {}, ensure_ascii=False), json.dumps(order.get("delivery") or {}, ensure_ascii=False),
                 json.dumps(order.get("items") or [], ensure_ascii=False), order.get("subtotal") or 0, order.get("deliveryPrice") or 0,
                 order.get("total") or 0, order.get("comment") or "", json.dumps(order, ensure_ascii=False, default=str), order.get("createdAt") or int(time.time())),
            )
            row = await (await db.execute("SELECT last_insert_rowid() AS id")).fetchone()
            order["id"] = row[0]
            await db.commit()
        return True
    except Exception:
        logger.warning("Failed to store miniapp order in unified DB", exc_info=True)
        return False


async def _db_list_orders() -> Optional[List[Dict[str, Any]]]:
    if not await _ensure_unified_db():
        return None
    import aiosqlite
    from bot.database import DATABASE_PATH
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM miniapp_orders ORDER BY id DESC LIMIT 500")
        orders = []
        for row in await cursor.fetchall():
            def loads(v, fallback):
                try: return json.loads(v or "")
                except Exception: return fallback
            orders.append({
                "id": row["id"], "status": row["status"], "createdAt": row["created_at"],
                "telegramUser": {"id": row["telegram_id"]} if row["telegram_id"] else None,
                "customer": loads(row["customer"], {}), "delivery": loads(row["delivery"], {}),
                "items": loads(row["items"], []), "subtotal": row["subtotal"], "deliveryPrice": row["delivery_price"],
                "total": row["total"], "comment": row["comment"] or "",
            })
        return orders

def _store_generation_item(item: Dict[str, Any]) -> None:
    tasks = _read_json(MINIAPP_TASKS_FILE, [])
    history = _read_json(MINIAPP_HISTORY_FILE, [])
    tasks.insert(0, item)
    history.insert(0, item)
    _write_json(MINIAPP_TASKS_FILE, tasks[:500])
    _write_json(MINIAPP_HISTORY_FILE, history[:500])


async def _notify_order(order: Dict[str, Any]) -> None:
    if not BOT_TOKEN or not ORDER_NOTIFY_CHAT_IDS:
        return

    try:
        import aiohttp

        items = "\n".join(
            f"• {item['name']} × {item['qty']} = {item['total']:.0f} ₽"
            for item in order.get("items", [])
        )

        user = order.get("telegramUser") or {}
        customer = order.get("customer") or {}

        text = (
            f"🛒 Новый заказ 2loop #{order['id']}\n\n"
            f"{items}\n\n"
            f"Итого: {order['total']:.0f} ₽\n"
            f"Telegram: {user.get('first_name', '')} {user.get('last_name', '')} "
            f"@{user.get('username', '')}\n"
            f"Контакты: {customer.get('name', '')} {customer.get('phone', '')}"
        )

        async with aiohttp.ClientSession() as session:
            for chat_id in ORDER_NOTIFY_CHAT_IDS:
                await session.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": text},
                    timeout=10,
                )

    except Exception:
        logger.exception("Failed to notify admins about 2loop order")


async def health(_: web.Request) -> web.Response:
    return _json({"ok": True, "service": "2loop-miniapp"})


async def me(request: web.Request) -> web.Response:
    user = _telegram_user(request)
    account = await _get_account_context(user)
    return _json(
        {
            "user": user,
            "isAdmin": _is_admin(request),
            "balanceGoe": account.get("balanceGoe", 0),
            "stats": account.get("stats", {}),
        }
    )


async def get_goe(request: web.Request) -> web.Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "auth_required"}, 401)
    account = await _get_account_context(user)
    return _json(
        {
            "balanceGoe": account.get("balanceGoe", 0),
            "balance": account.get("balanceGoe", 0),
            "goe": account.get("balanceGoe", 0),
            "spent": account.get("stats", {}).get("spentGoe", 0),
            "stats": account.get("stats", {}),
            "currency": "GOE",
        }
    )


async def list_presets(_: web.Request) -> web.Response:
    return _json({"presets": DEFAULT_PRESETS})


async def list_generation_tasks(request: web.Request) -> web.Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "auth_required"}, 401)
    telegram_id = _safe_int(user.get("id"))
    limit = max(1, min(_safe_int(request.query.get("limit"), 20), 100))
    db_items = await _db_list_generation_items(telegram_id, limit)
    if db_items is not None:
        return _json({"tasks": db_items[:limit]})
    tasks = _filter_user_items(_read_json(MINIAPP_TASKS_FILE, []), telegram_id)
    return _json({"tasks": tasks[:limit]})


async def list_generation_history(request: web.Request) -> web.Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "auth_required"}, 401)
    telegram_id = _safe_int(user.get("id"))
    limit = max(1, min(_safe_int(request.query.get("limit"), 20), 100))
    db_items = await _db_list_generation_items(telegram_id, limit)
    if db_items is not None:
        return _json({"history": db_items[:limit], "items": db_items[:limit]})
    history = _filter_user_items(_read_json(MINIAPP_HISTORY_FILE, []), telegram_id)
    return _json({"history": history[:limit], "items": history[:limit]})


async def create_generation(request: web.Request) -> web.Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "auth_required"}, 401)

    payload = await _read_request_json(request)
    prompt = str(
        payload.get("prompt")
        or payload.get("topic")
        or payload.get("text")
        or payload.get("goal")
        or ""
    ).strip()
    if not prompt:
        return _json({"error": "prompt_required"}, 400)
    if len(prompt) > 4000:
        return _json({"error": "prompt_too_long", "max": 4000}, 400)

    generation_type = str(payload.get("type") or payload.get("kind") or payload.get("generationType") or "content").strip().lower()
    if generation_type not in {"content", "image", "video", "tryon", "prompt"}:
        generation_type = "content"
    default_preset = {"content": "smm-caption", "image": "product-photo", "video": "dance-look", "tryon": "dance-look", "prompt": "smm-caption"}[generation_type]
    preset_id = str(payload.get("presetId") or payload.get("preset_id") or default_preset)
    preset = _find_preset(preset_id)
    aspect_ratio = str(payload.get("aspectRatio") or payload.get("aspect_ratio") or payload.get("ratio") or "1:1")
    duration = _safe_int(payload.get("duration"), 5)
    model = str(payload.get("model") or preset.get("model") or "local-demo")
    cost = MINIAPP_GENERATION_COSTS[generation_type]
    created_at = int(time.time())
    telegram_id = _safe_int(user.get("id"))
    result = _build_demo_result(
        prompt=prompt,
        preset=preset,
        kind=("image" if generation_type == "tryon" else generation_type),
        aspect_ratio=aspect_ratio,
    )
    task_id = f"{generation_type}_" + hashlib.sha256(
        f"{telegram_id}|{created_at}|{generation_type}|{preset['id']}|{prompt}".encode("utf-8")
    ).hexdigest()[:18]
    task = {
        "id": task_id,
        "taskId": task_id,
        "telegramId": telegram_id,
        "type": generation_type,
        "presetId": preset["id"],
        "prompt": prompt,
        "model": model,
        "aspectRatio": aspect_ratio,
        "duration": duration,
        "cost": cost,
        "status": "completed",
        "provider": "local-demo",
        "result": result,
        "resultUrl": result.get("url"),
        "createdAt": created_at,
        "completedAt": created_at,
    }
    try:
        stored = await _db_store_generation_item(task)
    except MiniappBillingError:
        return _json({"error": "not_enough_goe", "cost": cost}, 402)
    if not stored:
        if cost > 0:
            return _json({"error": "generation_storage_unavailable"}, 503)
        _store_generation_item(task)
    result_text = result.get("text") or result.get("description") or result.get("caption")
    return _json({"task": task, "result": result, "text": result_text}, 201)


async def create_smm_generation(request: web.Request) -> web.Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "auth_required"}, 401)

    payload = await _read_request_json(request)
    prompt = str(
        payload.get("prompt") or payload.get("topic") or payload.get("text") or ""
    ).strip()
    if not prompt:
        return _json({"error": "prompt_required"}, 400)
    if len(prompt) > 4000:
        return _json({"error": "prompt_too_long", "max": 4000}, 400)

    preset = _find_preset(str(payload.get("presetId") or "smm-caption"))
    created_at = int(time.time())
    telegram_id = _safe_int(user.get("id"))
    result = _build_demo_result(
        prompt=prompt,
        preset=preset,
        kind="smm",
        aspect_ratio="text",
    )
    task_id = "smm_" + hashlib.sha256(
        f"{telegram_id}|{created_at}|{preset['id']}|{prompt}".encode("utf-8")
    ).hexdigest()[:18]
    task = {
        "id": task_id,
        "taskId": task_id,
        "telegramId": telegram_id,
        "type": "smm",
        "presetId": preset["id"],
        "prompt": prompt,
        "model": str(payload.get("model") or preset.get("model") or "local-demo"),
        "cost": MINIAPP_GENERATION_COSTS["smm"],
        "status": "completed",
        "provider": "local-demo",
        "result": result,
        "createdAt": created_at,
        "completedAt": created_at,
    }
    try:
        stored = await _db_store_generation_item(task)
    except MiniappBillingError:
        return _json({"error": "not_enough_goe", "cost": task["cost"]}, 402)
    if not stored:
        _store_generation_item(task)
    return _json(
        {
            "task": task,
            "result": result,
            "text": result.get("text") or result.get("caption"),
            "plan": result.get("plan") or result.get("text") or result.get("caption"),
        },
        201,
    )


async def list_products(request: web.Request) -> web.Response:
    include_inactive = request.query.get("include_inactive") == "1"

    if include_inactive and not _is_admin(request):
        return _json({"error": "admin_required"}, 403)

    db_products = await _db_list_products(include_inactive)
    if db_products is not None:
        return _json({"products": db_products})

    products = _read_json(PRODUCTS_FILE, [])
    if not include_inactive:
        products = [product for product in products if product.get("active", True)]
    return _json({"products": products})


async def get_product(request: web.Request) -> web.Response:
    product_id = int(request.match_info["product_id"])
    db_products = await _db_list_products(True)
    if db_products is not None:
        product = next((item for item in db_products if int(item.get("id")) == product_id), None)
    else:
        products = _read_json(PRODUCTS_FILE, [])
        product = next((item for item in products if int(item.get("id")) == product_id), None)
    if not product:
        return _json({"error": "product_not_found"}, 404)
    return _json({"product": product})


async def create_product(request: web.Request) -> web.Response:
    denied = _require_admin(request)
    if denied:
        return denied

    payload = await request.json()
    try:
        product = await _db_upsert_product(payload)
        return _json({"product": product}, 201)
    except Exception:
        logger.warning("DB product create failed; using JSON fallback", exc_info=True)
    products = _read_json(PRODUCTS_FILE, [])
    product = _normalize_product(payload, _next_id(products))
    if not product["article"]:
        product["article"] = f"2LOOP-{product['id']:03d}"
    products.insert(0, product)
    _write_json(PRODUCTS_FILE, products)
    return _json({"product": product}, 201)


async def update_product(request: web.Request) -> web.Response:
    denied = _require_admin(request)
    if denied:
        return denied

    product_id = int(request.match_info["product_id"])
    payload = await request.json()
    try:
        product = await _db_upsert_product(payload, product_id)
        return _json({"product": product})
    except KeyError:
        return _json({"error": "product_not_found"}, 404)
    except Exception:
        logger.warning("DB product update failed; using JSON fallback", exc_info=True)
    products = _read_json(PRODUCTS_FILE, [])
    for idx, product in enumerate(products):
        if int(product.get("id")) == product_id:
            merged = {**product, **payload, "id": product_id}
            products[idx] = _normalize_product(merged, product_id)
            _write_json(PRODUCTS_FILE, products)
            return _json({"product": products[idx]})
    return _json({"error": "product_not_found"}, 404)


async def delete_product(request: web.Request) -> web.Response:
    denied = _require_admin(request)
    if denied:
        return denied

    product_id = int(request.match_info["product_id"])
    deleted = await _db_delete_product(product_id)
    if deleted:
        return _json({"ok": True})
    products = _read_json(PRODUCTS_FILE, [])
    next_products = [product for product in products if int(product.get("id")) != product_id]
    if len(next_products) == len(products):
        return _json({"error": "product_not_found"}, 404)
    _write_json(PRODUCTS_FILE, next_products)
    return _json({"ok": True})


async def upload_product_image(request: web.Request) -> web.Response:
    denied = _require_admin(request)
    if denied:
        return denied

    product_id = int(request.match_info["product_id"])
    db_products = await _db_list_products(True)
    use_db = db_products is not None
    products = db_products if use_db else _read_json(PRODUCTS_FILE, [])
    product_index = next((idx for idx, product in enumerate(products) if int(product.get("id")) == product_id), None)
    if product_index is None:
        return _json({"error": "product_not_found"}, 404)

    reader = await request.multipart()
    field = await reader.next()

    if not field or field.name != "file":
        return _json({"error": "file_required"}, 400)

    filename = field.filename or f"image-{int(time.time())}.jpg"
    ext = Path(filename).suffix.lower() or ".jpg"

    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        return _json({"error": "unsupported_file_type"}, 400)

    safe_name = f"product-{product_id}-{int(time.time() * 1000)}{ext}"
    target = UPLOAD_DIR / safe_name
    target.parent.mkdir(parents=True, exist_ok=True)

    with target.open("wb") as file:
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            file.write(chunk)

    public_url = f"/static/uploads/2loop/{safe_name}"

    product = products[product_index]
    images = product.get("images") or []
    images.append(public_url)
    product["images"] = images
    if use_db:
        updated = await _db_upsert_product(product, product_id)
    else:
        products[product_index] = _normalize_product(product, product_id)
        _write_json(PRODUCTS_FILE, products)
        updated = products[product_index]
    return _json({"url": public_url, "product": updated})


async def get_settings(_: web.Request) -> web.Response:
    return _json({"settings": _read_json(SETTINGS_FILE, {})})


async def update_settings(request: web.Request) -> web.Response:
    denied = _require_admin(request)
    if denied:
        return denied

    payload = await request.json()
    settings = _read_json(SETTINGS_FILE, {})
    settings.update(payload)

    if settings.get("theme") not in {"dark", "light"}:
        settings["theme"] = "dark"

    _write_json(SETTINGS_FILE, settings)

    return _json({"settings": settings})


async def apply_promo(request: web.Request) -> web.Response:
    payload = await request.json()
    code = str(payload.get("code") or "").strip().upper()
    subtotal = float(payload.get("subtotal") or 0)

    discount = 0.2 if code == "2LOOP" else 0
    total = round(subtotal * (1 - discount), 2)

    return _json(
        {
            "code": code,
            "discount": discount,
            "subtotal": subtotal,
            "total": total,
            "valid": discount > 0,
        }
    )


async def create_order(request: web.Request) -> web.Response:
    payload = await request.json()
    telegram_user = _telegram_user(request) or payload.get("telegramUser")

    orders = _read_json(ORDERS_FILE, [])
    products = await _db_list_products(True)
    if products is None:
        products = _read_json(PRODUCTS_FILE, [])
    product_by_id = {int(product["id"]): product for product in products}

    items = payload.get("items") or []
    normalized_items = []
    subtotal = 0.0

    for item in items:
        product = product_by_id.get(
            int(item.get("productId") or item.get("product_id") or 0)
        )

        if not product or not product.get("active", True):
            continue

        qty = max(1, int(item.get("qty") or 1))
        line_total = float(product.get("price") or 0) * qty
        subtotal += line_total

        normalized_items.append(
            {
                "productId": product["id"],
                "name": product["name"],
                "qty": qty,
                "price": product["price"],
                "total": line_total,
            }
        )

    if not normalized_items:
        return _json({"error": "empty_order"}, 400)

    delivery = 0 if subtotal >= 5000 else 350

    order = {
        "id": _next_id(orders),
        "status": "new",
        "createdAt": int(time.time()),
        "telegramUser": telegram_user,
        "customer": payload.get("customer") or {},
        "delivery": payload.get("delivery") or {},
        "items": normalized_items,
        "subtotal": subtotal,
        "deliveryPrice": delivery,
        "total": subtotal + delivery,
        "comment": payload.get("comment") or "",
    }

    if not await _db_store_order(order):
        orders.insert(0, order)
        _write_json(ORDERS_FILE, orders)
    asyncio.create_task(_notify_order(order))

    return _json({"order": order}, 201)


async def list_orders(request: web.Request) -> web.Response:
    denied = _require_admin(request)
    if denied:
        return denied

    db_orders = await _db_list_orders()
    if db_orders is not None:
        return _json({"orders": db_orders})
    return _json({"orders": _read_json(ORDERS_FILE, [])})


def setup_miniapp_routes(app: web.Application) -> None:
    _ensure_storage()

    app.router.add_get("/api/miniapp/health", _gate_miniapp(health, public=True))
    app.router.add_get("/api/miniapp/me", _gate_miniapp(me))
    app.router.add_get("/api/miniapp/goe", _gate_miniapp(get_goe))
    app.router.add_get("/api/miniapp/history", _gate_miniapp(list_generation_history))
    app.router.add_get("/api/miniapp/tasks", _gate_miniapp(list_generation_tasks))
    app.router.add_get("/api/miniapp/presets", _gate_miniapp(list_presets))
    app.router.add_post("/api/miniapp/generate", _gate_miniapp(create_generation))
    app.router.add_post("/api/miniapp/generate/smm", _gate_miniapp(create_smm_generation))

    app.router.add_get("/api/miniapp/products", _gate_miniapp(list_products))
    app.router.add_get("/api/miniapp/products/{product_id:\\d+}", _gate_miniapp(get_product))
    app.router.add_post("/api/miniapp/products", _gate_miniapp(create_product))
    app.router.add_put("/api/miniapp/products/{product_id:\\d+}", _gate_miniapp(update_product))
    app.router.add_delete("/api/miniapp/products/{product_id:\\d+}", _gate_miniapp(delete_product))
    app.router.add_post(
        "/api/miniapp/products/{product_id:\\d+}/images", _gate_miniapp(upload_product_image)
    )

    app.router.add_get("/api/miniapp/settings", _gate_miniapp(get_settings))
    app.router.add_put("/api/miniapp/settings", _gate_miniapp(update_settings))

    app.router.add_post("/api/miniapp/promo", _gate_miniapp(apply_promo))

    app.router.add_post("/api/miniapp/orders", _gate_miniapp(create_order))
    app.router.add_get("/api/miniapp/orders", _gate_miniapp(list_orders))
