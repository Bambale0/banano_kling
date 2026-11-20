"""Browser-native Lava commerce, with provider-confirmed immutable credits.

This module never creates or operates a legacy numeric Telegram user. Orders are
bound to a verified browser session's shared account ID and a unique request
key. Reconciliation and callbacks use the exact same ledger operation key.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from uuid import uuid4

from aiohttp import web

from bot import db as db_backend
from bot.payment_utils import total_package_credits
from bot.services.lava_service import LavaProviderUnavailable, lava_service
from bot.services.preset_manager import preset_manager
from bot.shared_accounts.schema import ensure_schema
from bot.shared_accounts.wallet import WalletService

logger = logging.getLogger(__name__)
_KEY = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_ORDER = re.compile(r"^web_[a-f0-9]{32}$")
_SUCCESS = {"completed", "paid", "success", "succeeded"}
_FAILED = {"failed", "cancelled", "canceled", "expired"}


def _enabled() -> bool:
    import os

    return os.getenv("WEB_NATIVE_PAYMENTS_ENABLED", "0").strip().lower() in (
        "1", "true", "yes",
    )
_DDL = (
    """CREATE TABLE IF NOT EXISTS web_payment_orders (
        order_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES shared_accounts(id),
        request_key TEXT NOT NULL,
        package_id TEXT NOT NULL,
        amount_minor BIGINT NOT NULL CHECK(amount_minor > 0),
        credit_amount TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('creating','pending','credited','failed')),
        invoice_id TEXT UNIQUE, contract_id TEXT UNIQUE, payment_url TEXT,
        created_at_epoch BIGINT NOT NULL, updated_at_epoch BIGINT NOT NULL,
        UNIQUE(account_id,request_key))""",
    """CREATE INDEX IF NOT EXISTS web_payment_pending ON
       web_payment_orders(status,created_at_epoch)""",
)


async def ensure_web_payment_schema():
    async with db_backend.connect() as db:
        await ensure_schema(db)
        if db_backend.is_postgres():
            await db.execute("SELECT pg_advisory_xact_lock(?)", (80420161121,))
        else:
            await db.execute("BEGIN IMMEDIATE")
        try:
            ddl = getattr(db, "execute_native_ddl", db.execute)
            for statement in _DDL:
                await ddl(statement)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


def _minor(value) -> int:
    try:
        exact = Decimal(str(value))
        cents = exact * 100
        if (not exact.is_finite() or not exact > 0 or exact > 1_000_000
                or cents != cents.to_integral_value()):
            raise ValueError("Unsupported price precision")
        return int(cents)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("Invalid price") from exc


def _package(package_id: str) -> tuple[int, str, str, str]:
    from bot.miniapp import _miniapp_package_lava_offer_config

    package = preset_manager.get_package(package_id)
    if not isinstance(package, dict):
        raise TypeError("Package not found")
    amount = _minor(package.get("price_rub"))
    credits = total_package_credits(package)
    if type(credits) is not int or credits <= 0:
        raise ValueError("Invalid credit package")
    offer, currency = _miniapp_package_lava_offer_config(package)
    if not offer or currency != "RUB":
        raise ValueError("Lava package offer not configured for RUB")
    return amount, str(credits), offer, str(package.get("name") or package_id)


def _external_invoice(invoice: dict, order) -> bool:
    """Fail closed unless provider itself attests the exact paid price."""
    amount = lava_service._find_first(invoice, ("amount",))
    currency = lava_service._find_first(invoice, ("currency",))
    try:
        return (str(currency or "").upper() == "RUB"
                and _minor(amount) == int(order[3]))
    except ValueError:
        return False


def _row_public(row) -> dict:
    return {
        "ok": True, "order_id": row[0], "package_id": row[2],
        "amount_rub": f"{int(row[3]) // 100}.{int(row[3]) % 100:02d}",
        "credits": row[4], "status": row[5],
        "payment_url": row[8] if row[5] in ("pending", "credited") else None,
    }


async def _get_order(order_id: str, account_id: str | None = None):
    if not _ORDER.fullmatch(str(order_id)):
        return None
    await ensure_web_payment_schema()
    async with db_backend.connect() as db:
        stmt = """SELECT o.order_id,o.account_id,o.package_id,o.amount_minor,
                      o.credit_amount,o.status,o.invoice_id,o.contract_id,
                      o.payment_url FROM web_payment_orders o WHERE o.order_id=?"""
        params = [order_id]
        if account_id is not None:
            # Account aliases produced by explicit, verified linking retain
            # ownership of old orders without transferring money again.
            stmt += """ AND o.account_id IN (
                WITH RECURSIVE owned(id) AS (
                    SELECT ? UNION ALL SELECT a.id FROM shared_accounts a
                    JOIN owned prev ON a.merged_into=prev.id WHERE a.status='merged'
                ) SELECT id FROM owned)"""
            params.append(account_id)
        return await (await db.execute(stmt, tuple(params))).fetchone()


async def list_packages(request: web.Request) -> web.Response:
    from bot.web_auth import _json, _session_account

    if not await _session_account(request):
        return _json({"ok": False, "error": "session_required"}, 401)
    available = bool(lava_service.enabled) and _enabled()
    rows = []
    for package in preset_manager.get_packages():
        try:
            amount, credits, offer, name = _package(str(package["id"]))
        except (KeyError, TypeError, ValueError):
            continue
        if offer:
            rows.append({
                "id": str(package["id"]), "name": name,
                "price_rub": f"{Decimal(amount) / 100:.2f}", "credits": credits,
            })
    return _json({"ok": True, "provider": "lava", "available": available, "packages": rows})


async def create_payment(request: web.Request) -> web.Response:
    from bot.web_auth import _json, _session_account, _valid_browser_origin

    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "origin_rejected"}, 403)
    if request.content_length and request.content_length > 4096:
        return _json({"ok": False, "error": "Request too large"}, 413)
    account = await _session_account(request)
    if not account:
        return _json({"ok": False, "error": "session_required"}, 401)
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise TypeError("Invalid request")
        key = str(payload.get("request_key") or "")
        package_id = str(payload.get("package_id") or "")
        email = str(payload.get("email") or "").strip().lower()
        from bot.web_auth import _EMAIL_RE

        if (not _KEY.fullmatch(key) or len(package_id) > 64
                or not _EMAIL_RE.fullmatch(email) or len(email) > 254):
            raise ValueError("Invalid checkout data")
        amount, credits, offer, _name = _package(package_id)
    except (ValueError, TypeError, KeyError):
        return _json({"ok": False, "error": "Проверьте пакет и email для чека."}, 400)
    if not _enabled() or not lava_service.enabled:
        return _json({"ok": False, "error": "Платёжный провайдер недоступен."}, 503)
    await ensure_web_payment_schema()
    candidate = "web_" + uuid4().hex
    stamp = int(time.time())
    async with db_backend.connect() as db:
        if db_backend.is_postgres():
            lock = int.from_bytes(hashlib.sha256(
                f"checkout:{account}".encode()).digest()[:8], "big", signed=True)
            await db.execute("SELECT pg_advisory_xact_lock(?)", (lock,))
        else:
            await db.execute("BEGIN IMMEDIATE")
        try:
            existing_order = await (await db.execute(
                """SELECT order_id FROM web_payment_orders
                   WHERE account_id=? AND request_key=?""",
                (account, key),
            )).fetchone()
            if not existing_order:
                from os import getenv

                try:
                    maximum = int(getenv("WEB_PAYMENT_MAX_NEW_INVOICES_PER_HOUR", "12"))
                except (TypeError, ValueError):
                    maximum = 12
                if not 1 <= maximum <= 100:
                    maximum = 12
                count = await (await db.execute(
                    """SELECT COUNT(*) FROM web_payment_orders
                       WHERE account_id=? AND created_at_epoch>?""",
                    (account, stamp - 3600),
                )).fetchone()
                if int(count[0]) >= maximum:
                    await db.rollback()
                    return _json({"ok": False, "error": "Лимит создания счетов. Повторите позже."}, 429)
            await db.execute(
                """INSERT INTO web_payment_orders
                   (order_id,account_id,request_key,package_id,amount_minor,
                    credit_amount,status,created_at_epoch,updated_at_epoch)
                   VALUES (?,?,?,?,?,?,'creating',?,?)
                   ON CONFLICT(account_id,request_key) DO NOTHING""",
                (candidate, account, key, package_id, amount, credits, stamp, stamp),
            )
            row = await (await db.execute(
                """SELECT order_id,account_id,package_id,amount_minor,
                          credit_amount,status,invoice_id,contract_id,payment_url
                   FROM web_payment_orders WHERE account_id=? AND request_key=?""",
                (account, key),
            )).fetchone()
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    if (str(row[2]), int(row[3]), str(row[4])) != (package_id, amount, credits):
        return _json({"ok": False, "error": "Повторный ключ с другим содержимым."}, 409)
    if row[0] != candidate:
        return _json(_row_public(row), 200 if row[5] in ("pending", "credited") else 202)

    try:
        invoice = await lava_service.create_invoice(
            email=email, offer_id=offer, currency="RUB",
            amount=float(Decimal(amount) / 100), buyer_language="RU",
            client_utm={"order_id": candidate, "package_id": package_id, "source": "web"},
            _allow_amount_fallback=False,
        )
    except (LavaProviderUnavailable, TimeoutError, ConnectionError):
        logger.warning("Web invoice creation outcome uncertain order_id=%s", candidate)
        return _json({"ok": False, "order_id": candidate,
                      "error": "Исход создания счёта неизвестен. Проверьте статус позже."}, 503)
    if not isinstance(invoice, dict) or not invoice.get("ok"):
        logger.warning("Web invoice creation failed order_id=%s", candidate)
        return _json({"ok": False, "order_id": candidate,
                      "error": "Платёж временно недоступен."}, 503)
    invoice_id = lava_service.extract_invoice_id(invoice)
    contract = lava_service.extract_contract_id(invoice)
    checkout_url = str(lava_service.extract_payment_url(invoice) or "")
    url = urlsplit(checkout_url)
    if (not invoice_id or not contract or url.scheme != "https" or not url.hostname
            or url.username or url.password or len(checkout_url) > 2048):
        logger.error("Invalid web invoice binding order_id=%s", candidate)
        return _json({"ok": False, "order_id": candidate,
                      "error": "Не удалось подтвердить параметры счёта."}, 503)
    # Persist the exact invoice binding BEFORE performing another provider
    # request. If validation times out, reconciliation can still find this
    # invoice without generating a second one for the same request key.
    async with db_backend.connect() as db:
        await db.execute(
            """UPDATE web_payment_orders SET invoice_id=?,contract_id=?,
               payment_url=?,updated_at_epoch=? WHERE order_id=? AND status='creating'""",
            (invoice_id, contract, checkout_url, int(time.time()), candidate),
        )
        await db.commit()
    try:
        provider_invoice = await lava_service.get_invoice(invoice_id)
        if (not isinstance(provider_invoice, dict)
                or not _external_invoice(provider_invoice, row)):
            logger.error("Web invoice amount not confirmed order_id=%s", candidate)
            return _json({"ok": False, "order_id": candidate,
                          "error": "Провайдер не подтвердил сумму счёта."}, 503)
    except LavaProviderUnavailable:
        return _json({"ok": False, "order_id": candidate,
                      "error": "Не удалось проверить сумму счёта."}, 503)
    async with db_backend.connect() as db:
        await db.execute(
            """UPDATE web_payment_orders SET status='pending',updated_at_epoch=?
               WHERE order_id=? AND status='creating'""",
            (int(time.time()), candidate),
        )
        await db.commit()
    return _json(_row_public(await _get_order(candidate, account)))


async def payment_status(request: web.Request) -> web.Response:
    from bot.web_auth import _json, _session_account

    account = await _session_account(request)
    if not account:
        return _json({"ok": False, "error": "session_required"}, 401)
    order = await _get_order(str(request.query.get("order_id") or ""), account)
    if not order:
        return _json({"ok": False, "error": "Order not found"}, 404)
    return _json(_row_public(order))


async def _settle(order) -> None:
    """Same immutable operation key means webhook/reconcile replay is harmless."""
    if order[5] == "credited":
        return
    await WalletService("live").apply(
        str(order[1]), "credit", str(order[4]), "web:topup:" + str(order[0]),
    )
    async with db_backend.connect() as db:
        await db.execute(
            """UPDATE web_payment_orders SET status='credited',updated_at_epoch=?
               WHERE order_id=? AND status IN ('creating','pending','failed','credited')""",
            (int(time.time()), order[0]),
        )
        await db.commit()


async def _real_invoice_status(order) -> tuple[str, dict | None]:
    if not order[6]:
        return "", None
    invoice = await lava_service.get_invoice(str(order[6]))
    if not isinstance(invoice, dict):
        return "", None
    extracted_id = lava_service.extract_invoice_id(invoice)
    extracted_contract = lava_service.extract_contract_id(invoice)
    if not extracted_id and not extracted_contract:
        raise ValueError("Lava did not prove the invoice identity")
    if (extracted_id and extracted_id != order[6]) or (
        extracted_contract and extracted_contract != order[7]
    ):
        raise ValueError("Lava invoice binding mismatch")
    if not _external_invoice(invoice, order):
        raise ValueError("Lava invoice price mismatch")
    return lava_service.webhook_status(invoice), invoice


async def verified_webhook(payload: dict, contract_id: str, event_type: str):
    """Called only AFTER existing Lava webhook auth/IP checks succeed."""
    await ensure_web_payment_schema()
    async with db_backend.connect() as db:
        row = await (await db.execute(
            """SELECT order_id,account_id,package_id,amount_minor,credit_amount,
                      status,invoice_id,contract_id,payment_url FROM web_payment_orders
               WHERE contract_id=?""",
            (str(contract_id),),
        )).fetchone()
    if not row:
        return None  # Legacy TG payment, handled by original path.
    if not _external_invoice(payload, row):
        return web.Response(status=409)
    hint = str(lava_service._find_first(payload, ("order_id", "orderId")) or "")
    if hint and hint != row[0]:
        return web.Response(status=409)
    try:
        status, _invoice = await _real_invoice_status(row)
    except (LavaProviderUnavailable, TimeoutError, ConnectionError):
        return web.Response(status=503)
    except ValueError:
        return web.Response(status=409)
    if event_type == "payment.failed":
        if status in _FAILED:
            async with db_backend.connect() as db:
                await db.execute(
                    """UPDATE web_payment_orders SET status='failed',updated_at_epoch=?
                       WHERE order_id=? AND status='pending'""",
                    (int(time.time()), row[0]),
                )
                await db.commit()
            return web.Response(status=200)
        return web.Response(status=503)
    if status not in _SUCCESS:
        return web.Response(status=503)
    try:
        await _settle(row)
        logger.info("web_topup_credited order=%s", row[0])
        return web.Response(status=200)
    except Exception:
        logger.exception("web_topup_credit_failed order=%s", row[0])
        return web.Response(status=503)


async def reconcile_pending(limit: int = 25) -> list[dict]:
    """Provider polling recovers lost callbacks and retries settlement idempotently."""
    if not lava_service.enabled:
        return []
    await ensure_web_payment_schema()
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            """SELECT order_id,account_id,package_id,amount_minor,credit_amount,
                      status,invoice_id,contract_id,payment_url
               FROM web_payment_orders WHERE status IN ('pending','creating','failed')
               AND invoice_id IS NOT NULL
               ORDER BY created_at_epoch ASC LIMIT ?""",
            (max(1, min(100, limit)),),
        )).fetchall()
    outcomes = []
    for row in rows:
        try:
            status, _invoice = await _real_invoice_status(row)
            if status in _SUCCESS:
                await _settle(row)
                action = "credited"
            elif status in _FAILED:
                async with db_backend.connect() as db:
                    await db.execute(
                        """UPDATE web_payment_orders SET status='failed',updated_at_epoch=?
                           WHERE order_id=? AND status='pending'""",
                        (int(time.time()), row[0]),
                    )
                    await db.commit()
                action = "failed"
            else:
                if row[5] == "creating":
                    async with db_backend.connect() as db:
                        await db.execute(
                            """UPDATE web_payment_orders SET status='pending',updated_at_epoch=?
                               WHERE order_id=? AND status='creating'""",
                            (int(time.time()), row[0]),
                        )
                        await db.commit()
                    action = "invoice_confirmed"
                else:
                    action = "pending"
            outcomes.append({"order_id": row[0], "action": action})
        except LavaProviderUnavailable:
            outcomes.append({"order_id": row[0], "action": "provider_unavailable"})
            break
        except Exception:
            logger.exception("web_payment_reconcile_error order=%s", row[0])
            outcomes.append({"order_id": row[0], "action": "error"})
    return outcomes


def register_routes(app: web.Application, prefix: str) -> None:
    app.router.add_get(prefix + "/web-payments/packages", list_packages)
    app.router.add_post(prefix + "/web-payments/create", create_payment)
    app.router.add_get(prefix + "/web-payments/status", payment_status)
