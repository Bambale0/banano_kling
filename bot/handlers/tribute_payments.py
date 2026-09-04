from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web

from bot.database import create_transaction, get_or_create_user, get_transaction_by_order
from bot.handlers.payments import _complete_transaction
from bot.payment_utils import total_package_credits
from bot.services.preset_manager import preset_manager

logger = logging.getLogger(__name__)

TRIBUTE_WEBHOOK_PATH = "/tribute/webhook"
TRIBUTE_API_BASE = "https://tribute.tg/api/v1"
TRIBUTE_PRODUCT_CACHE_TTL_SECONDS = 10 * 60
TRIBUTE_PACKAGE_LINKS: dict[str, str] = {
    "mini": "https://web.tribute.tg/p/Dxi",
    "start": "https://web.tribute.tg/p/Dxn",
    "optimal": "https://web.tribute.tg/p/Dxm",
    "pro": "https://web.tribute.tg/p/Dxo",
    "studio": "https://web.tribute.tg/p/Dxp",
    "business": "https://web.tribute.tg/p/Dxq",
}

_PRODUCT_CACHE: dict[int, "TributeProduct"] = {}
_PRODUCT_CACHE_EXPIRES_AT = 0.0
_PRODUCT_CACHE_LOCK = asyncio.Lock()


class TributeConfigurationError(RuntimeError):
    pass


class TributeProductError(ValueError):
    pass


@dataclass(frozen=True)
class TributeProduct:
    product_id: int
    package_id: str
    web_link: str
    amount: int | None = None
    currency: str = ""


def _api_key() -> str:
    return os.getenv("TRIBUTE_API_KEY", "").strip()


def _api_base() -> str:
    return os.getenv("TRIBUTE_API_BASE", TRIBUTE_API_BASE).strip().rstrip("/") or TRIBUTE_API_BASE


def _normalize_web_link(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def verify_tribute_signature(raw_body: bytes, signature: str, api_key: str | None = None) -> bool:
    key = (api_key if api_key is not None else _api_key()).strip()
    supplied = str(signature or "").strip()
    if supplied.lower().startswith("sha256="):
        supplied = supplied.split("=", 1)[1].strip()
    if not key or not supplied:
        return False
    expected = hmac.new(key.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.lower(), supplied.lower())


def _configured_tribute_links() -> dict[str, str]:
    return {
        _normalize_web_link(web_link): package_id
        for package_id, web_link in TRIBUTE_PACKAGE_LINKS.items()
    }


def _product_from_api_row(row: dict[str, Any], configured_links: dict[str, str]) -> TributeProduct | None:
    web_link = _normalize_web_link(row.get("webLink") or row.get("web_link"))
    package_id = configured_links.get(web_link)
    if not package_id:
        return None
    try:
        product_id = int(row.get("id"))
    except (TypeError, ValueError):
        return None
    raw_amount = row.get("amount")
    try:
        amount = int(raw_amount) if raw_amount is not None else None
    except (TypeError, ValueError):
        amount = None
    return TributeProduct(
        product_id=product_id,
        package_id=package_id,
        web_link=web_link,
        amount=amount,
        currency=str(row.get("currency") or "").strip().upper(),
    )


def build_tribute_payment_method_keyboard(
    package_id: str,
    has_crypto: bool = True,
    has_lava: bool = False,
    has_stars: bool = True,
    lava_price_usd: float | None = None,
) -> InlineKeyboardMarkup:
    """Text-bot payment methods with Tribute exposed as Reserve 2.

    Reserve 2 points straight to the matching Tribute product. Stars intentionally
    stay below Reserve 2 so the international backup method is easier to reach.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if has_crypto:
        rows.append(
            [
                InlineKeyboardButton(
                    text="₿ Криптовалюта (CryptoBot)",
                    callback_data=f"buy_crypto_{package_id}",
                )
            ]
        )
    if has_lava:
        lava_suffix = f" · ${lava_price_usd:g}" if lava_price_usd else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Оплата картой {lava_suffix}",
                    callback_data=f"buy_lava_{package_id}",
                )
            ]
        )

    tribute_url = TRIBUTE_PACKAGE_LINKS.get(package_id)
    if tribute_url:
        rows.append([InlineKeyboardButton(text="Резерв 2", url=tribute_url)])

    if has_stars:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⭐ Telegram Stars",
                    callback_data=f"buy_stars_{package_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_topup")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def install_tribute_text_payment_keyboard() -> None:
    """Install Reserve 2 into the existing Telegram payment flow."""
    from bot import keyboards as keyboards_module
    from bot.handlers import payments as payments_handler

    keyboards_module.get_payment_method_keyboard = build_tribute_payment_method_keyboard
    payments_handler.get_payment_method_keyboard = build_tribute_payment_method_keyboard


async def _load_product_map() -> dict[int, TributeProduct]:
    api_key = _api_key()
    if not api_key:
        raise TributeConfigurationError("TRIBUTE_API_KEY is not configured")

    configured_links = _configured_tribute_links()
    if len(configured_links) != 6:
        raise TributeConfigurationError("All six Tribute package links must be configured")

    timeout = aiohttp.ClientTimeout(total=15)
    products: dict[int, TributeProduct] = {}
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for page in range(1, 11):
            async with session.get(
                f"{_api_base()}/products",
                params={"page": page, "size": 100, "type": "digital"},
                headers={"Api-Key": api_key, "Accept": "application/json"},
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    raise TributeConfigurationError(
                        f"Tribute products API returned HTTP {response.status}: {body[:200]}"
                    )
                payload = await response.json(content_type=None)

            rows = payload.get("rows") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise TributeConfigurationError("Tribute products API returned invalid rows")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                product = _product_from_api_row(row, configured_links)
                if product:
                    products[product.product_id] = product
            if len(rows) < 100:
                break

    if len(products) != 6:
        missing = sorted(set(configured_links.values()) - {item.package_id for item in products.values()})
        raise TributeConfigurationError(
            "Tribute products are not fully resolved" + (f": {', '.join(missing)}" if missing else "")
        )
    return products


async def resolve_tribute_product(product_id: int) -> TributeProduct:
    global _PRODUCT_CACHE, _PRODUCT_CACHE_EXPIRES_AT
    now = time.monotonic()
    if _PRODUCT_CACHE and now < _PRODUCT_CACHE_EXPIRES_AT:
        product = _PRODUCT_CACHE.get(int(product_id))
        if product:
            return product
        raise TributeProductError("Unknown Tribute product")

    async with _PRODUCT_CACHE_LOCK:
        now = time.monotonic()
        if not _PRODUCT_CACHE or now >= _PRODUCT_CACHE_EXPIRES_AT:
            _PRODUCT_CACHE = await _load_product_map()
            _PRODUCT_CACHE_EXPIRES_AT = now + TRIBUTE_PRODUCT_CACHE_TTL_SECONDS
        product = _PRODUCT_CACHE.get(int(product_id))
        if not product:
            raise TributeProductError("Unknown Tribute product")
        return product


def _validate_payload_against_product(payload: dict[str, Any], product: TributeProduct) -> None:
    event_currency = str(payload.get("currency") or "").strip().upper()
    if product.currency and event_currency and product.currency != event_currency:
        raise TributeProductError("Tribute currency mismatch")

    if product.amount is not None and payload.get("amount") is not None:
        try:
            event_amount = int(payload.get("amount"))
        except (TypeError, ValueError) as exc:
            raise TributeProductError("Invalid Tribute amount") from exc
        if event_amount != product.amount:
            raise TributeProductError("Tribute amount mismatch")


def _event_ids(payload: dict[str, Any]) -> tuple[int, str, str]:
    try:
        telegram_user_id = int(payload.get("telegram_user_id"))
        purchase_id = str(int(payload.get("purchase_id")))
    except (TypeError, ValueError) as exc:
        raise TributeProductError("Missing Tribute purchaser or purchase id") from exc
    transaction_id_raw = payload.get("transaction_id")
    transaction_id = str(transaction_id_raw).strip() if transaction_id_raw is not None else purchase_id
    if telegram_user_id <= 0 or not purchase_id:
        raise TributeProductError("Invalid Tribute purchaser or purchase id")
    return telegram_user_id, purchase_id, transaction_id


async def _credit_tribute_purchase(request: web.Request, payload: dict[str, Any], product: TributeProduct) -> dict[str, Any]:
    _validate_payload_against_product(payload, product)
    telegram_user_id, purchase_id, transaction_id = _event_ids(payload)
    package = preset_manager.get_package(product.package_id)
    if not package:
        raise TributeProductError("Mapped package is unavailable")

    credits = int(total_package_credits(package, 0))
    amount_rub = float(package.get("price_rub") or 0)
    order_id = f"tribute:{purchase_id}"
    payment_id = f"tribute:{transaction_id}"

    user = await get_or_create_user(telegram_user_id)
    existing = await get_transaction_by_order(order_id)
    if existing is not None:
        if (
            existing.provider != "tribute"
            or int(existing.user_id) != int(user.id)
            or int(existing.credits) != credits
        ):
            raise TributeProductError("Tribute purchase conflicts with an existing transaction")
        if existing.status == "completed":
            return {"status": "ok", "duplicate": True, "order_id": order_id}
    else:
        created = await create_transaction(
            order_id=order_id,
            user_id=user.id,
            payment_id=payment_id,
            provider="tribute",
            credits=credits,
            amount_rub=amount_rub,
            status="pending",
        )
        if not created:
            existing = await get_transaction_by_order(order_id)
            if existing is not None and existing.status == "completed":
                return {"status": "ok", "duplicate": True, "order_id": order_id}
            if existing is None:
                raise RuntimeError("Could not persist Tribute transaction")

    bot = request.app.get("bot")
    result = await _complete_transaction(order_id, bot=bot)
    if not result.get("ok") and not result.get("already_completed"):
        raise RuntimeError(
            f"Could not complete Tribute transaction: {result.get('reason') or 'unknown reason'}"
        )
    return {
        "status": "ok",
        "duplicate": bool(result.get("already_completed")),
        "order_id": order_id,
        "credits": credits,
    }


async def handle_tribute_webhook(request: web.Request) -> web.Response:
    api_key = _api_key()
    if not api_key:
        logger.error("Tribute webhook rejected: TRIBUTE_API_KEY is not configured")
        return web.json_response({"error": "tribute_not_configured"}, status=503)

    raw_body = await request.read()
    signature = request.headers.get("trbt-signature", "")
    if not verify_tribute_signature(raw_body, signature, api_key):
        return web.json_response({"error": "invalid_signature"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid_payload"}, status=400)

    event_name = str(body.get("name") or "").strip()
    if event_name != "new_digital_product":
        return web.json_response({"status": "ignored", "event": event_name})

    payload = body.get("payload")
    if not isinstance(payload, dict):
        return web.json_response({"error": "invalid_payload"}, status=400)
    try:
        product_id = int(payload.get("product_id"))
        product = await resolve_tribute_product(product_id)
        result = await _credit_tribute_purchase(request, payload, product)
    except TributeProductError as exc:
        logger.warning("Tribute webhook rejected: %s", exc)
        return web.json_response({"error": str(exc)}, status=400)
    except TributeConfigurationError as exc:
        logger.error("Tribute webhook configuration error: %s", exc)
        return web.json_response({"error": "tribute_configuration_error"}, status=503)
    except Exception:
        logger.exception("Tribute webhook failed")
        return web.json_response({"error": "tribute_webhook_failed"}, status=500)

    return web.json_response(result)


def setup_tribute_routes(app: web.Application) -> None:
    install_tribute_text_payment_keyboard()
    app.router.add_post(TRIBUTE_WEBHOOK_PATH, handle_tribute_webhook)
    logger.info("Tribute webhook registered: %s", TRIBUTE_WEBHOOK_PATH)
