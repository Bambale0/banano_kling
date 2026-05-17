import asyncio
import html
import hmac
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import openpyxl as xl
from aiohttp import web

from bot.config import config
from bot.database import (
    create_shop_order,
    get_recent_shop_orders,
    get_shop_product_images,
    get_shop_product_overrides,
    track_event,
    upsert_shop_product_override,
)

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "catalog.xlsx"
SHOP_INDEX_PATH = Path(__file__).resolve().parents[1] / "static" / "shop" / "index.html"
SHOP_STATIC_PATH = Path(__file__).resolve().parents[1] / "static" / "shop"
WB_BRAND_URL = "https://www.wildberries.ru/brands/312149369-2loop"
SUPPORT_USERNAME = "design_2Loop7222"
SHOP_ADMIN_KEY = os.getenv("SHOP_ADMIN_KEY", "")
MAX_ORDER_ITEM_QTY = 99


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_number(value: Any, default: float = 0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    return int(_as_number(value, default))


def _html(value: Any) -> str:
    return html.escape(_as_text(value), quote=True)


def _format_name(category: str, seller_article: str, wb_article: str) -> str:
    if seller_article and not seller_article.lower().startswith("wb"):
        return seller_article[:1].upper() + seller_article[1:]
    if category:
        return f"{category} 2Loop"
    return f"Товар 2Loop {wb_article}"


def _product_from_row(row: tuple[Any, ...]) -> dict[str, Any] | None:
    if len(row) < 13:
        return None

    brand = _as_text(row[0])
    category = _as_text(row[1]) or "Аксессуары"
    wb_article = _as_text(row[2])
    seller_article = _as_text(row[3])
    if not wb_article or wb_article.lower() == "none":
        return None

    stock_wb = _as_int(row[5])
    stock_seller = _as_int(row[6])
    current_price = _as_int(row[8])
    discount = _as_int(row[10])
    final_price = _as_int(row[12], current_price)
    total_stock = stock_wb + stock_seller

    return {
        "id": wb_article,
        "brand": brand or "2Loop",
        "category": category,
        "name": _format_name(category, seller_article, wb_article),
        "wbArticle": wb_article,
        "sellerArticle": seller_article,
        "barcode": _as_text(row[4]),
        "stockWb": stock_wb,
        "stockSeller": stock_seller,
        "stockTotal": total_stock,
        "available": total_stock > 0,
        "imageUrl": "",
        "images": [],
        "currentPrice": current_price,
        "price": final_price,
        "discountPercent": discount,
        "promoCode": "2LOOP",
        "promoHint": "Промокод проверяется в боте",
        "wbUrl": f"https://www.wildberries.ru/catalog/{wb_article}/detail.aspx",
        "sizes": ["XS", "S", "M", "L"] if "гетр" in category.lower() or "перчат" in category.lower() else ["one size"],
        "color": "перламутровый" if "чех" in category.lower() else ("чёрный" if "black" in seller_article.lower() or "midnight" in seller_article.lower() else "ледяной"),
        "badge": "2в1" if "гетр" in category.lower() else ("NEW" if total_stock > 0 else ""),
        "description": "Авторский аксессуар 2LOOP для фигурного катания: премиальная посадка, красота и уверенность на льду.",
    }


def load_catalog_products() -> list[dict[str, Any]]:
    workbook = xl.load_workbook(CATALOG_PATH, data_only=True)
    sheet = workbook.active

    products: list[dict[str, Any]] = []
    for row in sheet.iter_rows(min_row=3, values_only=True):
        product = _product_from_row(row)
        if product:
            products.append(product)

    products.sort(
        key=lambda item: (not item["available"], item["category"], item["name"])
    )
    return products


def apply_product_overrides(
    products: list[dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
    images_by_article: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    images_by_article = images_by_article or {}
    result = []
    for product in products:
        override = overrides.get(product["wbArticle"])
        if override:
            if override.get("is_hidden"):
                continue
            if override.get("name"):
                product["name"] = override["name"]
            if override.get("image_url"):
                product["imageUrl"] = override["image_url"]
            if override.get("stock_override") is not None:
                product["stockTotal"] = int(override["stock_override"])
                product["stockSeller"] = int(override["stock_override"])
                product["available"] = int(override["stock_override"]) > 0
            if override.get("price_override") is not None:
                product["price"] = int(float(override["price_override"]))
        gallery = [
            {
                "id": image["id"],
                "url": image["image_url"],
                "isPrimary": bool(image["is_primary"]),
            }
            for image in images_by_article.get(product["wbArticle"], [])
        ]
        if not gallery and product.get("imageUrl"):
            gallery = [{"id": None, "url": product["imageUrl"], "isPrimary": True}]
        if gallery:
            primary = next(
                (image for image in gallery if image["isPrimary"]), gallery[0]
            )
            product["imageUrl"] = primary["url"]
            product["images"] = gallery
        result.append(product)
    return result


async def shop_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(SHOP_INDEX_PATH)


async def catalog_api(request: web.Request) -> web.Response:
    try:
        products = apply_product_overrides(
            load_catalog_products(),
            await get_shop_product_overrides(),
            await get_shop_product_images(),
        )
    except Exception as error:
        raise web.HTTPInternalServerError(
            text=f"Failed to load catalog: {error}"
        ) from error

    categories = sorted({product["category"] for product in products})
    host = config.WEBHOOK_HOST.rstrip("/")
    shop_url = f"{host}/shop" if host else "/shop"

    return web.json_response(
        {
            "brand": "2Loop",
            "title": "2Loop Shop",
            "supportUsername": SUPPORT_USERNAME,
            "wildberriesBrandUrl": WB_BRAND_URL,
            "shopUrl": shop_url,
            "currency": "RUB",
            "promoCode": "2LOOP",
            "categories": categories,
            "products": products,
        }
    )


def _format_order_text(order_id: str, payload: dict[str, Any]) -> str:
    items = payload.get("items") or []
    total = payload.get("total", 0)
    promo_code = payload.get("promoCode") or "2LOOP"
    customer = payload.get("customer") or {}
    delivery = payload.get("delivery") or {}
    lines = []
    for item in items:
        name = item.get("name", "Товар")
        article = item.get("wbArticle", "")
        qty = item.get("qty", 1)
        price = item.get("price", 0)
        line_total = item.get("total") or float(price or 0) * int(qty or 1)
        lines.append(
            f"• {_html(name)}\n"
            f"  WB: <code>{_html(article)}</code> × {_html(qty)} — {_html(line_total)} ₽"
        )

    return (
        "🛒 <b>Заказ из мини-магазина</b>\n\n"
        f"№ <code>{_html(order_id)}</code>\n\n"
        f"{chr(10).join(lines)}\n\n"
        f"💎 Итого: <code>{_html(total)} ₽</code>\n"
        f"🎟 Промокод: <code>{_html(promo_code)}</code>\n\n"
        f"👤 {_html(customer.get('name') or '-')}\n"
        f"📞 {_html(customer.get('phone') or '-')}\n"
        f"📍 {_html(delivery.get('city') or '-')}, {_html(delivery.get('address') or '-')}\n"
        f"🚚 {_html(delivery.get('method') or 'manual')}\n\n"
        "Менеджер 2Loop свяжется для подтверждения заказа."
    )


def _catalog_product_map(products: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    product_map: dict[str, dict[str, Any]] = {}
    for product in products:
        for key in (product.get("wbArticle"), product.get("id")):
            article = _as_text(key)
            if article:
                product_map[article] = product
    return product_map


def _server_delivery_price(subtotal: float, delivery: dict[str, Any]) -> float:
    method = _as_text(delivery.get("method")).lower()
    if method in {"pickup", "self", "самовывоз"}:
        return 0.0
    return 0.0 if subtotal >= 5000 else 350.0


def _build_trusted_order(
    payload: dict[str, Any],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    product_map = _catalog_product_map(products)
    trusted_items: list[dict[str, Any]] = []

    for raw_item in payload.get("items") or []:
        if not isinstance(raw_item, dict):
            raise web.HTTPBadRequest(text="Invalid order item")

        article = _as_text(
            raw_item.get("wbArticle") or raw_item.get("article") or raw_item.get("id")
        )
        product = product_map.get(article)
        if not product:
            raise web.HTTPBadRequest(text=f"Unknown product: {article or '-'}")

        qty = _as_int(raw_item.get("qty") or raw_item.get("quantity"), 1)
        if qty < 1 or qty > MAX_ORDER_ITEM_QTY:
            raise web.HTTPBadRequest(text="Invalid item quantity")

        stock = _as_int(product.get("stockTotal"), 0)
        if not product.get("available", True) or stock <= 0:
            raise web.HTTPConflict(text=f"Product unavailable: {article}")
        if qty > stock:
            raise web.HTTPConflict(text=f"Not enough stock: {article}")

        price = round(float(product.get("price") or product.get("currentPrice") or 0), 2)
        if price <= 0:
            raise web.HTTPConflict(text=f"Product has no price: {article}")

        trusted_items.append(
            {
                "id": product.get("id") or article,
                "wbArticle": product.get("wbArticle") or article,
                "sellerArticle": product.get("sellerArticle") or "",
                "name": product.get("name") or f"Товар 2Loop {article}",
                "category": product.get("category") or "",
                "price": price,
                "qty": qty,
                "total": round(price * qty, 2),
                "imageUrl": product.get("imageUrl") or "",
                "wbUrl": product.get("wbUrl") or "",
            }
        )

    if not trusted_items:
        raise web.HTTPBadRequest(text="Cart is empty")

    delivery = payload.get("delivery") or {}
    subtotal = round(sum(float(item["total"]) for item in trusted_items), 2)
    delivery_price = _server_delivery_price(subtotal, delivery)
    trusted_delivery = {
        "method": _as_text(delivery.get("method")) or "manual",
        "city": _as_text(delivery.get("city")),
        "address": _as_text(delivery.get("address")),
        "price": delivery_price,
    }
    total = round(subtotal + delivery_price, 2)

    return {
        "items": trusted_items,
        "subtotal": subtotal,
        "delivery": trusted_delivery,
        "total": total,
    }


async def shop_order_api(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except json.JSONDecodeError as error:
        raise web.HTTPBadRequest(text="Invalid JSON") from error

    if payload.get("type") != "catalog_order":
        raise web.HTTPBadRequest(text="Invalid order type")

    customer = payload.get("customer") or {}
    delivery = payload.get("delivery") or {}
    if not customer.get("name") or not customer.get("phone"):
        raise web.HTTPBadRequest(text="Customer name and phone are required")
    if not delivery.get("city") or not delivery.get("address"):
        raise web.HTTPBadRequest(text="Delivery city and address are required")

    products = apply_product_overrides(
        load_catalog_products(),
        await get_shop_product_overrides(),
        await get_shop_product_images(),
    )
    trusted_order = _build_trusted_order(payload, products)
    trusted_payload = {
        **payload,
        "items": trusted_order["items"],
        "subtotal": trusted_order["subtotal"],
        "delivery": trusted_order["delivery"],
        "total": trusted_order["total"],
        "clientTotal": payload.get("total"),
    }

    order_id = f"SHOP-{uuid.uuid4().hex[:10].upper()}"
    telegram_user = payload.get("telegramUser") or {}
    telegram_id = _as_int(telegram_user.get("id"), 0) or None

    await create_shop_order(
        order_id=order_id,
        telegram_id=telegram_id,
        customer=customer,
        delivery=trusted_order["delivery"],
        items=trusted_order["items"],
        total_rub=trusted_order["total"],
        promo_code=payload.get("promoCode") or "2LOOP",
        raw_payload=trusted_payload,
    )
    await track_event(
        telegram_id,
        "catalog_webapp_order_http",
        {
            "order_id": order_id,
            "items_count": len(trusted_order["items"]),
            "total": trusted_order["total"],
            "client_total": payload.get("total"),
            "delivery": trusted_order["delivery"].get("method"),
        },
    )

    order_text = _format_order_text(order_id, trusted_payload)
    bot = request.app.get("bot")
    if bot:

        async def notify_order():
            recipients = []
            if telegram_id:
                recipients.append(int(telegram_id))
            recipients.extend(config.admin_ids)
            for recipient in dict.fromkeys(recipients):
                try:
                    await bot.send_message(recipient, order_text, parse_mode="HTML")
                except Exception:
                    pass

        asyncio.create_task(notify_order())

    return web.json_response(
        {
            "ok": True,
            "orderId": order_id,
            "message": "Заказ сохранён. Менеджер 2Loop свяжется для подтверждения.",
        }
    )


def _admin_allowed(request: web.Request) -> bool:
    provided = request.headers.get("X-Shop-Admin-Key") or request.query.get("admin_key")
    if SHOP_ADMIN_KEY and hmac.compare_digest(provided or "", SHOP_ADMIN_KEY):
        return True

    try:
        from bot.miniapp_api import _parse_init_data

        parsed = _parse_init_data(request.headers.get("X-Telegram-Init-Data", ""))
        user = (parsed or {}).get("user") or {}
        telegram_id = int(user.get("id"))
    except Exception:
        return False

    return config.is_admin(telegram_id)


async def shop_admin_orders_api(request: web.Request) -> web.Response:
    if not _admin_allowed(request):
        raise web.HTTPForbidden(text="admin_required")
    limit = min(int(request.query.get("limit", "100")), 500)
    return web.json_response({"ok": True, "orders": await get_recent_shop_orders(limit)})


async def shop_admin_product_api(request: web.Request) -> web.Response:
    if not _admin_allowed(request):
        raise web.HTTPForbidden(text="admin_required")
    wb_article = request.match_info.get("wb_article", "").strip()
    try:
        payload = await request.json()
    except json.JSONDecodeError as error:
        raise web.HTTPBadRequest(text="Invalid JSON") from error
    await upsert_shop_product_override(
        wb_article,
        name=payload.get("name") or None,
        image_url=payload.get("imageUrl") or payload.get("image_url") or None,
        stock_override=int(payload["stock"]) if payload.get("stock") not in (None, "") else None,
        price_override=float(payload["price"]) if payload.get("price") not in (None, "") else None,
        is_hidden=bool(payload.get("isHidden")),
        updated_by=int(request.headers.get("X-Telegram-Id", "0") or 0) or None,
    )
    return web.json_response({"ok": True, "message": "Товар сохранён"})


async def shop_lead_api(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except json.JSONDecodeError as error:
        raise web.HTTPBadRequest(text="Invalid JSON") from error
    name = _as_text(payload.get("name")) or "Гость сайта"
    contact = _as_text(payload.get("contact") or payload.get("phone") or payload.get("email"))
    message = _as_text(payload.get("message"))
    if not contact:
        raise web.HTTPBadRequest(text="Contact is required")
    await track_event(
        None,
        "shop_lead",
        {"name": name, "contact": contact, "message": message, "source": payload.get("source", "site")},
    )
    bot = request.app.get("bot")
    if bot and config.admin_ids:
        text = (
            "💌 <b>Заявка с сайта 2LOOP</b>\n\n"
            f"👤 {name}\n"
            f"📞 {contact}\n"
            f"💬 {message or '-'}"
        )
        async def notify_lead():
            for recipient in dict.fromkeys(config.admin_ids):
                try:
                    await bot.send_message(recipient, text, parse_mode="HTML")
                except Exception:
                    pass
        asyncio.create_task(notify_lead())
    return web.json_response({"ok": True, "message": "Заявка отправлена"})


async def shop_analytics_api(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except json.JSONDecodeError as error:
        raise web.HTTPBadRequest(text="Invalid JSON") from error
    event = _as_text(payload.get("event")) or "shop_event"
    await track_event(None, event[:80], {"path": payload.get("path"), "payload": payload.get("payload") or {}})
    return web.json_response({"ok": True})


async def shop_admin_order_status_api(request: web.Request) -> web.Response:
    if not _admin_allowed(request):
        raise web.HTTPForbidden(text="admin_required")
    order_id = request.match_info.get("order_id", "").strip()
    try:
        payload = await request.json()
    except json.JSONDecodeError as error:
        raise web.HTTPBadRequest(text="Invalid JSON") from error
    status = _as_text(payload.get("status")) or "new"
    allowed = {"new", "pending", "confirmed", "paid", "shipped", "done", "cancelled"}
    if status not in allowed:
        raise web.HTTPBadRequest(text="Invalid status")
    import aiosqlite
    from bot.database import DATABASE_PATH
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE shop_orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE order_id = ?", (status, order_id))
        await db.commit()
    return web.json_response({"ok": True, "orderId": order_id, "status": status})


SITE_GENERATION_COSTS = {"content": 15, "image": 30, "video": 60, "tryon": 45, "prompt": 5, "voice": 20, "product": 25, "calendar": 35}
SITE_GENERATION_TITLES = {
    "content": "Пост / сценарий / SMM",
    "image": "AI-образ / фото / карточка товара",
    "video": "Видео / Reels / клип",
    "tryon": "Примерка / look / образ",
    "prompt": "Улучшение промпта",
    "voice": "Озвучка / voice-over",
    "product": "Описание товара / карточка",
    "calendar": "Контент-план",
}


async def _ensure_site_cabinet_tables() -> None:
    import aiosqlite
    from bot.database import DATABASE_PATH
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS site_users (
                session_id TEXT PRIMARY KEY,
                name TEXT,
                contact TEXT,
                telegram_id INTEGER,
                balance_goe INTEGER NOT NULL DEFAULT 300,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS site_generations (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                type TEXT NOT NULL,
                title TEXT,
                prompt TEXT NOT NULL,
                result_json TEXT NOT NULL,
                cost INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'completed',
                created_at INTEGER NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS site_goe_transactions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        await db.commit()


def _site_session_from_request(request: web.Request, payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    raw = request.headers.get("X-2Loop-Session") or request.query.get("sessionId") or payload.get("sessionId") or ""
    raw = str(raw).strip()
    if raw and len(raw) <= 80:
        return raw
    return "site_" + uuid.uuid4().hex


def _site_generation_result(kind: str, prompt: str, ratio: str = "1:1") -> dict[str, Any]:
    title = SITE_GENERATION_TITLES.get(kind, SITE_GENERATION_TITLES["content"])
    common = {
        "kind": kind,
        "title": title,
        "ratio": ratio,
        "brand": "2LOOP",
        "currency": "GOE",
        "prompt": prompt,
    }
    if kind == "image":
        common.update({"description": f"Премиальный fashion-визуал 2LOOP: {prompt}. Светлый лёд, aurora gradient, перламутровые блики, чистый каталоговый кадр.", "assetType": "image_prompt"})
    elif kind == "video":
        common.update({"script": ["0–2 сек: крупный ледяной блик и логотип 2LOOP", "2–6 сек: фигуристка в движении, акцент на аксессуар", "6–10 сек: товар + CTA создать образ за GOE"], "assetType": "video_script"})
    elif kind == "tryon":
        common.update({"description": f"Виртуальный look для фигуристки: {prompt}. Подбор аксессуаров, цвета, посадки и премиальной подачи на льду.", "assetType": "tryon_brief"})
    elif kind == "prompt":
        common.update({"text": f"Премиальный промпт для 2LOOP: {prompt}. Стиль: фигурное катание, aurora light, luxury sport, clean product focus, elegant ice motion, high detail.", "assetType": "prompt"})
    elif kind == "voice":
        common.update({"text": f"Voice-over 2LOOP: {prompt}. Тон: вдохновляющий, лёгкий, премиальный, с ощущением движения на льду.", "assetType": "voice_script"})
    elif kind == "product":
        common.update({"text": f"Карточка товара 2LOOP: {prompt}. Преимущества: авторские лекала, комфорт на тренировке, премиальная посадка, эстетика на льду.", "assetType": "product_copy"})
    elif kind == "calendar":
        common.update({"plan": ["Пн: польза аксессуара", "Ср: backstage/примерка", "Пт: Reels на льду", "Вс: подборка товаров + CTA"], "assetType": "content_calendar"})
    else:
        common.update({"text": f"Пост 2LOOP: {prompt}\n\nСоздаём красоту на льду ✦ Авторские аксессуары, тренировки и стиль в одном движении. Выберите образ и создайте следующий материал за GOE.", "assetType": "content"})
    return common


async def _site_profile(session_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    await _ensure_site_cabinet_tables()
    import aiosqlite
    from bot.database import DATABASE_PATH
    now = int(time.time())
    payload = payload or {}
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute("SELECT * FROM site_users WHERE session_id=?", (session_id,))).fetchone()
        if not row:
            await db.execute("INSERT INTO site_users(session_id,name,contact,balance_goe,created_at,updated_at) VALUES(?,?,?,?,?,?)", (session_id, str(payload.get("name") or "Гость 2LOOP"), str(payload.get("contact") or ""), 300, now, now))
            await db.execute("INSERT INTO site_goe_transactions(id,session_id,amount,reason,created_at) VALUES(?,?,?,?,?)", ("tx_"+uuid.uuid4().hex, session_id, 300, "welcome_bonus", now))
            await db.commit()
            row = await (await db.execute("SELECT * FROM site_users WHERE session_id=?", (session_id,))).fetchone()
        elif payload.get("name") or payload.get("contact"):
            await db.execute("UPDATE site_users SET name=COALESCE(NULLIF(?, ''), name), contact=COALESCE(NULLIF(?, ''), contact), updated_at=? WHERE session_id=?", (str(payload.get("name") or ""), str(payload.get("contact") or ""), now, session_id))
            await db.commit()
            row = await (await db.execute("SELECT * FROM site_users WHERE session_id=?", (session_id,))).fetchone()
        gens = await (await db.execute("SELECT COUNT(*), COALESCE(SUM(cost),0) FROM site_generations WHERE session_id=?", (session_id,))).fetchone()
        return {"sessionId": row["session_id"], "name": row["name"], "contact": row["contact"], "telegramId": row["telegram_id"], "balanceGoe": 0, "demoBalanceGoe": row["balance_goe"], "walletType": "site_demo", "stats": {"generations": int(gens[0] or 0), "spentGoe": int(gens[1] or 0)}, "createdAt": row["created_at"]}


async def site_session_api(request: web.Request) -> web.Response:
    payload = await request.json() if request.can_read_body else {}
    session_id = _site_session_from_request(request, payload)
    profile = await _site_profile(session_id, payload)
    return web.json_response({"ok": True, "profile": profile})


async def site_cabinet_api(request: web.Request) -> web.Response:
    session_id = _site_session_from_request(request)
    profile = await _site_profile(session_id)
    return web.json_response({"ok": True, "profile": profile, "features": [{"code": k, "title": SITE_GENERATION_TITLES[k], "cost": SITE_GENERATION_COSTS[k]} for k in SITE_GENERATION_TITLES]})


async def site_generate_api(request: web.Request) -> web.Response:
    payload = await request.json()
    session_id = _site_session_from_request(request, payload)
    profile = await _site_profile(session_id, payload)
    kind = str(payload.get("type") or payload.get("kind") or "content").strip().lower()
    if kind not in SITE_GENERATION_COSTS:
        kind = "content"
    prompt = str(payload.get("prompt") or payload.get("text") or "").strip()
    if not prompt:
        return web.json_response({"error": "prompt_required"}, status=400)
    cost = int(SITE_GENERATION_COSTS[kind])
    if int(profile["demoBalanceGoe"]) < cost:
        return web.json_response({"error": "not_enough_demo_goe", "demoBalanceGoe": profile["demoBalanceGoe"], "cost": cost}, status=402)
    result = _site_generation_result(kind, prompt, str(payload.get("aspectRatio") or "1:1"))
    task_id = "sitegen_" + uuid.uuid4().hex[:18]
    now = int(time.time())
    await _ensure_site_cabinet_tables()
    import aiosqlite
    from bot.database import DATABASE_PATH
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE site_users SET balance_goe=balance_goe-?, updated_at=? WHERE session_id=?", (cost, now, session_id))
        await db.execute("INSERT INTO site_generations(id,session_id,type,title,prompt,result_json,cost,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (task_id, session_id, kind, SITE_GENERATION_TITLES[kind], prompt, json.dumps(result, ensure_ascii=False), cost, "completed", now))
        await db.execute("INSERT INTO site_goe_transactions(id,session_id,amount,reason,created_at) VALUES(?,?,?,?,?)", ("tx_"+uuid.uuid4().hex, session_id, -cost, f"generation:{kind}", now))
        await db.commit()
    profile = await _site_profile(session_id)
    await track_event(0, "site_generate", {"type": kind, "cost": cost})
    return web.json_response({"ok": True, "task": {"id": task_id, "type": kind, "title": SITE_GENERATION_TITLES[kind], "prompt": prompt, "result": result, "cost": cost, "status": "completed", "createdAt": now}, "profile": profile})


async def site_history_api(request: web.Request) -> web.Response:
    session_id = _site_session_from_request(request)
    await _site_profile(session_id)
    import aiosqlite
    from bot.database import DATABASE_PATH
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute("SELECT * FROM site_generations WHERE session_id=? ORDER BY created_at DESC LIMIT 100", (session_id,))).fetchall()
        txs = await (await db.execute("SELECT * FROM site_goe_transactions WHERE session_id=? ORDER BY created_at DESC LIMIT 100", (session_id,))).fetchall()
    tasks=[]
    for r in rows:
        try: result=json.loads(r["result_json"] or "{}")
        except Exception: result={}
        tasks.append({"id": r["id"], "type": r["type"], "title": r["title"], "prompt": r["prompt"], "result": result, "cost": r["cost"], "status": r["status"], "createdAt": r["created_at"]})
    return web.json_response({"ok": True, "history": tasks, "transactions": [dict(t) for t in txs]})


async def shop_bot_capabilities_api(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "currency": "GOE",
            "userModules": [
                {"code": "content", "title": "Пост / сценарий / SMM", "cost": 15, "endpoint": "/api/miniapp/generate"},
                {"code": "image", "title": "AI-образ / фото / карточка товара", "cost": 30, "endpoint": "/api/miniapp/generate"},
                {"code": "video", "title": "Видео / Reels / клип", "cost": 60, "endpoint": "/api/miniapp/generate"},
                {"code": "tryon", "title": "Примерка / look / образ", "cost": 45, "endpoint": "/api/miniapp/generate"},
                {"code": "prompt", "title": "Улучшение промпта", "cost": 5, "endpoint": "/api/miniapp/generate"},
                {"code": "shop", "title": "Каталог, корзина и заказы", "cost": 0, "endpoint": "/api/shop/order"},
                {"code": "wallet", "title": "Баланс GOE и история", "cost": 0, "endpoint": "/api/miniapp/goe"},
            ],
            "adminModules": [
                {"code": "orders", "title": "Заказы и статусы", "endpoint": "/api/shop/admin/orders"},
                {"code": "products", "title": "Товары, цены, остатки, фото", "endpoint": "/api/shop/admin/products/{article}"},
                {"code": "miniapp_products", "title": "Mini App товары и изображения", "endpoint": "/api/miniapp/products"},
                {"code": "users", "title": "Пользователи, GOE, активность", "endpoint": "/api/shop/admin/overview"},
                {"code": "generations", "title": "Генерации, история, задачи", "endpoint": "/api/shop/admin/overview"},
                {"code": "broadcast", "title": "Рассылки и поддержка", "endpoint": "Telegram admin flow"},
            ],
            "flows": [
                "Открыть сайт → выбрать сценарий AI → авторизоваться в Telegram Mini App → потратить GOE → получить результат",
                "Открыть каталог → добавить товар → checkout → заказ сохранён → админ видит статус",
                "Админ → товары/заказы/пользователи/генерации → управление без оператора в клиентском сценарии",
            ],
        }
    )


async def shop_admin_overview_api(request: web.Request) -> web.Response:
    if not _admin_allowed(request):
        raise web.HTTPForbidden(text="admin_required")
    import aiosqlite
    from bot.database import DATABASE_PATH
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async def one(sql: str) -> int:
            try:
                row = await (await db.execute(sql)).fetchone()
                return int(row[0] or 0)
            except Exception:
                return 0
        stats = {
            "users": await one("SELECT COUNT(*) FROM users"),
            "generationTasks": await one("SELECT COUNT(*) FROM generation_tasks"),
            "generationHistory": await one("SELECT COUNT(*) FROM generation_history"),
            "shopOrders": await one("SELECT COUNT(*) FROM shop_orders"),
            "miniappOrders": await one("SELECT COUNT(*) FROM miniapp_orders"),
            "events": await one("SELECT COUNT(*) FROM analytics_events"),
            "transactions": await one("SELECT COUNT(*) FROM transactions"),
            "siteUsers": await one("SELECT COUNT(*) FROM site_users"),
            "siteGenerations": await one("SELECT COUNT(*) FROM site_generations"),
        }
        recent_tasks = []
        try:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT task_id, telegram_id, type, preset_id, status, cost, created_at FROM generation_tasks ORDER BY created_at DESC LIMIT 20")
            recent_tasks = [dict(row) for row in await cur.fetchall()]
        except Exception:
            recent_tasks = []
    return web.json_response({"ok": True, "stats": stats, "recentTasks": recent_tasks})


async def shop_payment_stub_api(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "provider": "manual",
            "message": "Структура оплаты подготовлена: ЮKassa / CloudPayments / Robokassa подключаются к этому шагу checkout.",
        }
    )


async def shop_delivery_methods_api(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "methods": [
                {"code": "cdek", "title": "СДЭК", "status": "ready_for_credentials"},
                {"code": "boxberry", "title": "Boxberry", "status": "ready_for_credentials"},
                {"code": "post", "title": "Почта России", "status": "ready_for_credentials"},
                {"code": "pickup", "title": "Самовывоз", "status": "manual"},
                {"code": "manual", "title": "Согласовать с менеджером", "status": "active"},
            ],
        }
    )


def setup_catalog_webapp_routes(app: web.Application) -> None:
    app.router.add_get("/shop", shop_index)
    app.router.add_get("/shop/", shop_index)
    app.router.add_get("/catalog", shop_index)
    app.router.add_get("/catalog/", shop_index)
    app.router.add_get("/product/{wb_article}", shop_index)
    app.router.add_get("/cart", shop_index)
    app.router.add_get("/checkout", shop_index)
    app.router.add_get("/thanks", shop_index)
    app.router.add_get("/bot", shop_index)
    app.router.add_get("/platform", shop_index)
    app.router.add_get("/creator", shop_index)
    app.router.add_get("/wallet", shop_index)
    app.router.add_get("/history", shop_index)
    app.router.add_get("/cabinet", shop_index)
    app.router.add_get("/dashboard", shop_index)
    app.router.add_get("/admin", shop_index)
    app.router.add_get("/api/catalog", catalog_api)
    app.router.add_post("/api/shop/order", shop_order_api)
    app.router.add_get("/api/shop/admin/orders", shop_admin_orders_api)
    app.router.add_put("/api/shop/admin/orders/{order_id}/status", shop_admin_order_status_api)
    app.router.add_put("/api/shop/admin/products/{wb_article}", shop_admin_product_api)
    app.router.add_post("/api/shop/lead", shop_lead_api)
    app.router.add_post("/api/shop/analytics", shop_analytics_api)
    app.router.add_get("/api/shop/bot-capabilities", shop_bot_capabilities_api)
    app.router.add_get("/api/shop/admin/overview", shop_admin_overview_api)
    app.router.add_post("/api/site/session", site_session_api)
    app.router.add_get("/api/site/cabinet", site_cabinet_api)
    app.router.add_post("/api/site/generate", site_generate_api)
    app.router.add_get("/api/site/history", site_history_api)
    app.router.add_post("/api/shop/payment/session", shop_payment_stub_api)
    app.router.add_get("/api/shop/delivery/methods", shop_delivery_methods_api)
    app.router.add_static(
        "/shop/assets/", path=SHOP_STATIC_PATH, show_index=False, name="shop_assets"
    )
