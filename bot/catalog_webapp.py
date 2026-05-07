import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import openpyxl as xl
from aiohttp import web

from bot.config import config
from bot.database import (
    create_shop_order,
    get_shop_product_images,
    get_shop_product_overrides,
    track_event,
)

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "catalog.xlsx"
SHOP_INDEX_PATH = Path(__file__).resolve().parents[1] / "static" / "shop" / "index.html"
SHOP_STATIC_PATH = Path(__file__).resolve().parents[1] / "static" / "shop"
WB_BRAND_URL = "https://www.wildberries.ru/brands/312149369-2loop"
SUPPORT_USERNAME = "design_2Loop7222"


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
        lines.append(f"• {name}\n  WB: <code>{article}</code> × {qty} — {price} ₽")

    return (
        "🛒 <b>Заказ из мини-магазина</b>\n\n"
        f"№ <code>{order_id}</code>\n\n"
        f"{chr(10).join(lines)}\n\n"
        f"💎 Итого: <code>{total} ₽</code>\n"
        f"🎟 Промокод: <code>{promo_code}</code>\n\n"
        f"👤 {customer.get('name') or '-'}\n"
        f"📞 {customer.get('phone') or '-'}\n"
        f"📍 {delivery.get('city') or '-'}, {delivery.get('address') or '-'}\n"
        f"🚚 {delivery.get('method') or 'manual'}\n\n"
        "Менеджер 2Loop свяжется для подтверждения заказа."
    )


async def shop_order_api(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except json.JSONDecodeError as error:
        raise web.HTTPBadRequest(text="Invalid JSON") from error

    if payload.get("type") != "catalog_order":
        raise web.HTTPBadRequest(text="Invalid order type")

    items = payload.get("items") or []
    customer = payload.get("customer") or {}
    delivery = payload.get("delivery") or {}
    if not items:
        raise web.HTTPBadRequest(text="Cart is empty")
    if not customer.get("name") or not customer.get("phone"):
        raise web.HTTPBadRequest(text="Customer name and phone are required")
    if not delivery.get("city") or not delivery.get("address"):
        raise web.HTTPBadRequest(text="Delivery city and address are required")

    order_id = f"SHOP-{uuid.uuid4().hex[:10].upper()}"
    telegram_user = payload.get("telegramUser") or {}
    telegram_id = telegram_user.get("id")

    await create_shop_order(
        order_id=order_id,
        telegram_id=telegram_id,
        customer=customer,
        delivery=delivery,
        items=items,
        total_rub=float(payload.get("total") or 0),
        promo_code=payload.get("promoCode") or "2LOOP",
        raw_payload=payload,
    )
    await track_event(
        telegram_id,
        "catalog_webapp_order_http",
        {
            "order_id": order_id,
            "items_count": len(items),
            "total": payload.get("total"),
            "delivery": delivery.get("method"),
        },
    )

    order_text = _format_order_text(order_id, payload)
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


def setup_catalog_webapp_routes(app: web.Application) -> None:
    app.router.add_get("/shop", shop_index)
    app.router.add_get("/shop/", shop_index)
    app.router.add_get("/api/catalog", catalog_api)
    app.router.add_post("/api/shop/order", shop_order_api)
    app.router.add_static(
        "/shop/assets/", path=SHOP_STATIC_PATH, show_index=False, name="shop_assets"
    )
