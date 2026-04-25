import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from aiohttp import web

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("TWOLOOP_DATA_DIR", "/root/2loop/data"))
UPLOAD_DIR = Path(os.getenv("TWOLOOP_UPLOAD_DIR", "static/uploads/2loop"))
PRODUCTS_FILE = DATA_DIR / "products.json"
ORDERS_FILE = DATA_DIR / "orders.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

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


def _ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if not PRODUCTS_FILE.exists():
        _write_json(PRODUCTS_FILE, DEFAULT_PRODUCTS)
    if not ORDERS_FILE.exists():
        _write_json(ORDERS_FILE, [])
    if not SETTINGS_FILE.exists():
        _write_json(SETTINGS_FILE, {"theme": "dark", "brand": "2loop"})


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
    return web.json_response(data, status=status, dumps=lambda v: json.dumps(v, ensure_ascii=False))


def _next_id(items: List[Dict[str, Any]]) -> int:
    return (max([int(item.get("id", 0)) for item in items] or [0]) + 1)


def _normalize_product(payload: Dict[str, Any], product_id: int | None = None) -> Dict[str, Any]:
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


async def health(_: web.Request) -> web.Response:
    return _json({"ok": True, "service": "2loop-miniapp"})


async def list_products(request: web.Request) -> web.Response:
    products = _read_json(PRODUCTS_FILE, [])
    include_inactive = request.query.get("include_inactive") == "1"
    if not include_inactive:
        products = [p for p in products if p.get("active", True)]
    return _json({"products": products})


async def get_product(request: web.Request) -> web.Response:
    product_id = int(request.match_info["product_id"])
    products = _read_json(PRODUCTS_FILE, [])
    product = next((p for p in products if int(p.get("id")) == product_id), None)
    if not product:
        return _json({"error": "product_not_found"}, 404)
    return _json({"product": product})


async def create_product(request: web.Request) -> web.Response:
    payload = await request.json()
    products = _read_json(PRODUCTS_FILE, [])
    product = _normalize_product(payload, _next_id(products))
    if not product["article"]:
        product["article"] = f"2LOOP-{product['id']:03d}"
    products.insert(0, product)
    _write_json(PRODUCTS_FILE, products)
    return _json({"product": product}, 201)


async def update_product(request: web.Request) -> web.Response:
    product_id = int(request.match_info["product_id"])
    payload = await request.json()
    products = _read_json(PRODUCTS_FILE, [])
    for idx, product in enumerate(products):
        if int(product.get("id")) == product_id:
            merged = {**product, **payload, "id": product_id}
            products[idx] = _normalize_product(merged, product_id)
            _write_json(PRODUCTS_FILE, products)
            return _json({"product": products[idx]})
    return _json({"error": "product_not_found"}, 404)


async def delete_product(request: web.Request) -> web.Response:
    product_id = int(request.match_info["product_id"])
    products = _read_json(PRODUCTS_FILE, [])
    next_products = [p for p in products if int(p.get("id")) != product_id]
    if len(next_products) == len(products):
        return _json({"error": "product_not_found"}, 404)
    _write_json(PRODUCTS_FILE, next_products)
    return _json({"ok": True})


async def upload_product_image(request: web.Request) -> web.Response:
    product_id = int(request.match_info["product_id"])
    reader = await request.multipart()
    field = await reader.next()
    if not field or field.name != "file":
        return _json({"error": "file_required"}, 400)
    filename = field.filename or f"image-{int(time.time())}.jpg"
    ext = Path(filename).suffix.lower() or ".jpg"
    safe_name = f"product-{product_id}-{int(time.time() * 1000)}{ext}"
    target = UPLOAD_DIR / safe_name
    with target.open("wb") as f:
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            f.write(chunk)
    public_url = f"/static/uploads/2loop/{safe_name}"
    products = _read_json(PRODUCTS_FILE, [])
    for idx, product in enumerate(products):
        if int(product.get("id")) == product_id:
            images = product.get("images") or []
            images.append(public_url)
            product["images"] = images
            products[idx] = _normalize_product(product, product_id)
            _write_json(PRODUCTS_FILE, products)
            return _json({"url": public_url, "product": products[idx]})
    return _json({"error": "product_not_found"}, 404)


async def get_settings(_: web.Request) -> web.Response:
    return _json({"settings": _read_json(SETTINGS_FILE, {})})


async def update_settings(request: web.Request) -> web.Response:
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
    return _json({"code": code, "discount": discount, "subtotal": subtotal, "total": total, "valid": discount > 0})


async def create_order(request: web.Request) -> web.Response:
    payload = await request.json()
    orders = _read_json(ORDERS_FILE, [])
    products = _read_json(PRODUCTS_FILE, [])
    product_by_id = {int(p["id"]): p for p in products}
    items = payload.get("items") or []
    normalized_items = []
    subtotal = 0.0
    for item in items:
        product = product_by_id.get(int(item.get("productId") or item.get("product_id") or 0))
        if not product:
            continue
        qty = max(1, int(item.get("qty") or 1))
        line_total = float(product.get("price") or 0) * qty
        subtotal += line_total
        normalized_items.append({"productId": product["id"], "name": product["name"], "qty": qty, "price": product["price"], "total": line_total})
    delivery = 0 if subtotal >= 5000 else 350
    order = {
        "id": _next_id(orders),
        "status": "new",
        "createdAt": int(time.time()),
        "telegramUser": payload.get("telegramUser"),
        "customer": payload.get("customer") or {},
        "delivery": payload.get("delivery") or {},
        "items": normalized_items,
        "subtotal": subtotal,
        "deliveryPrice": delivery,
        "total": subtotal + delivery,
        "comment": payload.get("comment") or "",
    }
    orders.insert(0, order)
    _write_json(ORDERS_FILE, orders)
    return _json({"order": order}, 201)


async def list_orders(_: web.Request) -> web.Response:
    return _json({"orders": _read_json(ORDERS_FILE, [])})


def setup_miniapp_routes(app: web.Application) -> None:
    _ensure_storage()
    app.router.add_get("/api/miniapp/health", health)
    app.router.add_get("/api/miniapp/products", list_products)
    app.router.add_get("/api/miniapp/products/{product_id:\\d+}", get_product)
    app.router.add_post("/api/miniapp/products", create_product)
    app.router.add_put("/api/miniapp/products/{product_id:\\d+}", update_product)
    app.router.add_delete("/api/miniapp/products/{product_id:\\d+}", delete_product)
    app.router.add_post("/api/miniapp/products/{product_id:\\d+}/images", upload_product_image)
    app.router.add_get("/api/miniapp/settings", get_settings)
    app.router.add_put("/api/miniapp/settings", update_settings)
    app.router.add_post("/api/miniapp/promo", apply_promo)
    app.router.add_post("/api/miniapp/orders", create_order)
    app.router.add_get("/api/miniapp/orders", list_orders)
