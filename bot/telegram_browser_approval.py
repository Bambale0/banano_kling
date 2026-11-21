"""Browser login through explicit confirmation by the Telegram bot.

A Telegram deep link is not an authentication credential for a website: the
server verifies the callback sender, and only the initiating HttpOnly-cookie
browser can claim the approved one-time request.
"""
from __future__ import annotations

import logging
import secrets
import time
from uuid import uuid4

from aiohttp import web
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import db as db_backend

logger = logging.getLogger(__name__)

_COOKIE = "nm_tg_approval_browser"
_COOKIE_PATH = "/mini-app/api/web-auth/telegram-approval"
_TTL = 300
_BROWSER_LIMIT = 5
_REQUEST_ID_LENGTH = 32


def _auth():
    from bot import web_auth

    return web_auth


def _browser_hash(request: web.Request) -> str | None:
    raw = request.cookies.get(_COOKIE, "")
    try:
        return _auth()._digest(raw)
    except ValueError:
        return None


def _valid_request_id(value: object) -> bool:
    return isinstance(value, str) and len(value) == _REQUEST_ID_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def _status_response(status: str, *, code: int = 200) -> web.Response:
    return _auth()._json({"ok": code == 200, "status": status}, code)


async def start(request: web.Request) -> web.Response:
    auth = _auth()
    if not auth._valid_browser_origin(request):
        return auth._json({"ok": False, "error": "origin_rejected"}, 403)
    if request.content_length and request.content_length > 4096:
        return auth._json({"ok": False, "error": "request_too_large"}, 413)
    if await auth._session_account(request):
        return auth._json({"ok": False, "error": "already_authenticated"}, 409)
    try:
        # Trust the Bot API's own bot username, not browser input or a hardcoded ID.
        from bot.browser_auth import _browser_bot_username

        username = await _browser_bot_username(request)
        if not username or not all(c.isalnum() or c == "_" for c in username):
            raise ValueError("Missing Telegram bot username")
    except Exception:  # noqa: BLE001 - Bot API availability must not expose errors
        logger.warning("Telegram approval bot username unavailable", exc_info=False)
        return auth._json({"ok": False, "error": "telegram_unavailable"}, 503)

    browser_token = request.cookies.get(_COOKIE, "")
    try:
        browser_hash = auth._digest(browser_token)
    except ValueError:
        browser_token = secrets.token_urlsafe(32)
        browser_hash = auth._digest(browser_token)
    challenge = secrets.token_urlsafe(32)
    request_id = uuid4().hex
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = int(time.time())

    await auth._ensure_tables()
    async with db_backend.connect() as db:
        if not db_backend.is_postgres():
            await db.execute("BEGIN IMMEDIATE")
        try:
            # Keep terminal challenges for a short audit window; then purge
            # old opaque identifiers without affecting rate-limit history.
            await db.execute(
                "DELETE FROM web_auth_telegram_approvals WHERE expires_at_epoch < ?",
                (now - 86400,),
            )
            count_row = await (await db.execute(
                """SELECT COUNT(*) FROM web_auth_telegram_approvals
                   WHERE browser_hash=? AND created_at_epoch>?""",
                (browser_hash, now - 600),
            )).fetchone()
            if int(count_row[0]) >= _BROWSER_LIMIT:
                await db.rollback()
                return auth._json({"ok": False, "error": "rate_limited"}, 429)
            await db.execute(
                """UPDATE web_auth_telegram_approvals SET status='denied'
                   WHERE browser_hash=? AND status IN ('pending','approved')""",
                (browser_hash,),
            )
            await db.execute(
                """INSERT INTO web_auth_telegram_approvals
                   (request_id,challenge_hash,browser_hash,status,confirm_code,
                    created_at_epoch,expires_at_epoch)
                   VALUES (?,?,?,'pending',?,?,?)""",
                (request_id, auth._digest(challenge), browser_hash, code, now, now + _TTL),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    response = auth._json({
        "ok": True, "id": request_id, "expires_in": _TTL,
        "confirmation_code": code,
        "url": f"https://t.me/{username}?start=auth_{challenge}",
    })
    response.set_cookie(
        _COOKIE, browser_token, max_age=_TTL, httponly=True, secure=True,
        samesite="Lax", path=_COOKIE_PATH,
    )
    logger.info("Telegram browser approval started: request_id=%s", request_id)
    return response


async def _lookup(id_or_challenge: str, *, by_challenge: bool = False):
    auth = _auth()
    # The creating request already ensured the schema; avoid DDL/advisory-lock
    # round-trips for each short-interval browser poll and bot callback.
    where = "challenge_hash" if by_challenge else "request_id"
    try:
        lookup = auth._digest(id_or_challenge) if by_challenge else id_or_challenge
    except ValueError:
        return None
    async with db_backend.connect() as db:
        return await (await db.execute(
            f"""SELECT request_id,browser_hash,status,confirm_code,
                       telegram_id,expires_at_epoch FROM web_auth_telegram_approvals
                WHERE {where}=?""",
            (lookup,),
        )).fetchone()


async def status(request: web.Request) -> web.Response:
    request_id = request.query.get("id", "")
    browser = _browser_hash(request)
    if not browser or not _valid_request_id(request_id):
        return _status_response("not_found", code=404)
    row = await _lookup(request_id)
    if not row or row[1] != browser:
        return _status_response("not_found", code=404)
    if int(row[5]) <= int(time.time()):
        return _status_response("expired")
    return _status_response(str(row[2]))


async def cancel(request: web.Request) -> web.Response:
    auth = _auth()
    if not auth._valid_browser_origin(request):
        return auth._json({"ok": False, "error": "origin_rejected"}, 403)
    if request.content_length and request.content_length > 4096:
        return auth._json({"ok": False, "error": "request_too_large"}, 413)
    browser = _browser_hash(request)
    if not browser:
        return _status_response("not_found", code=404)
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return auth._json({"ok": False, "error": "invalid_request"}, 400)
    if not isinstance(body, dict) or not _valid_request_id(body.get("id")):
        return auth._json({"ok": False, "error": "invalid_request"}, 400)
    await auth._ensure_tables()
    async with db_backend.connect() as db:
        updated = await db.execute(
            """UPDATE web_auth_telegram_approvals SET status='denied'
               WHERE request_id=? AND browser_hash=?
                 AND status IN ('pending','approved')""",
            (body["id"], browser),
        )
        await db.commit()
    if updated.rowcount != 1:
        return _status_response("unavailable", code=409)
    return _status_response("denied")


async def claim(request: web.Request) -> web.Response:
    auth = _auth()
    if not auth._valid_browser_origin(request):
        return auth._json({"ok": False, "error": "origin_rejected"}, 403)
    if request.content_length and request.content_length > 4096:
        return auth._json({"ok": False, "error": "request_too_large"}, 413)
    browser = _browser_hash(request)
    if not browser or await auth._session_account(request):
        return _status_response("unavailable", code=409)
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return auth._json({"ok": False, "error": "invalid_request"}, 400)
    if not isinstance(body, dict) or not _valid_request_id(body.get("id")):
        return auth._json({"ok": False, "error": "invalid_request"}, 400)

    await auth._ensure_tables()
    now = int(time.time())
    # Atomic compare-and-swap: competing claims cannot mint two sessions.
    async with db_backend.connect() as db:
        if not db_backend.is_postgres():
            await db.execute("BEGIN IMMEDIATE")
        try:
            row = await (await db.execute(
                """SELECT telegram_id FROM web_auth_telegram_approvals
                   WHERE request_id=? AND browser_hash=? AND status='approved'
                     AND expires_at_epoch>?""",
                (body["id"], browser, now),
            )).fetchone()
            if not row or type(row[0]) is not int or row[0] <= 0:
                await db.rollback()
                return _status_response("unavailable", code=409)
            updated = await db.execute(
                """UPDATE web_auth_telegram_approvals SET status='consumed'
                   WHERE request_id=? AND browser_hash=? AND status='approved'
                     AND expires_at_epoch>?""",
                (body["id"], browser, now),
            )
            if updated.rowcount != 1:
                await db.rollback()
                return _status_response("unavailable", code=409)
            await db.commit()
            telegram_id = int(row[0])
        except Exception:
            await db.rollback()
            raise

    result = await auth._complete_identity(request, "telegram", str(telegram_id), {
        "mode": "login", "source": None, "destination": "/login",
    })
    if auth._SESSION_COOKIE not in result.cookies:
        logger.warning("Telegram browser approval account refused: request_id=%s", body["id"])
        return _status_response("unavailable", code=409)
    response = auth._json({"ok": True, "status": "authenticated"})
    auth._set_session_cookie(response, result.cookies[auth._SESSION_COOKIE].value)
    response.del_cookie(_COOKIE, path=_COOKIE_PATH)
    logger.info("Telegram browser approval completed: request_id=%s", body["id"])
    return response


async def send_confirmation(message, challenge: str) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    row = await _lookup(challenge, by_challenge=True)
    if not row or row[2] != "pending" or int(row[5]) <= int(time.time()):
        await message.answer("Ссылка на вход недействительна или истекла. Вернитесь на сайт NEUROMIX.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"wba:yes:{challenge}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"wba:no:{challenge}"),
    ]])
    await message.answer(
        "Вы запрашивали вход на сайт NEUROMIX?\n\n"
        f"Код проверки: <b>{row[3]}</b>\n"
        "Сравните его с кодом на сайте. Если это не вы — нажмите «Отклонить».\n"
        "Запрос действует 5 минут.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def decide(callback) -> None:
    if not callback.from_user or not callback.message or callback.message.chat.type != "private":
        await callback.answer("Доступно только в личном чате", show_alert=True)
        return
    if callback.message.chat.id != callback.from_user.id:
        await callback.answer("Неверный аккаунт", show_alert=True)
        return
    parts = str(callback.data or "").split(":")
    if len(parts) != 3 or parts[0] != "wba" or parts[1] not in {"yes", "no"}:
        await callback.answer("Недействительная кнопка", show_alert=True)
        return
    auth = _auth()
    try:
        challenge_hash = auth._digest(parts[2])
    except ValueError:
        await callback.answer("Ссылка недействительна", show_alert=True)
        return
    await auth._ensure_tables()
    now = int(time.time())
    approved = parts[1] == "yes"
    async with db_backend.connect() as db:
        updated = await db.execute(
            """UPDATE web_auth_telegram_approvals
               SET status=?,telegram_id=?
               WHERE challenge_hash=? AND status='pending'
                 AND expires_at_epoch>?""",
            ("approved" if approved else "denied",
             callback.from_user.id if approved else None, challenge_hash, now),
        )
        await db.commit()
    if updated.rowcount != 1:
        await callback.answer("Этот запрос уже обработан или истёк.", show_alert=True)
        return
    logger.info("Telegram browser approval decision: telegram_id=%s approved=%s", callback.from_user.id, approved)
    try:
        await callback.message.edit_text(
            "✅ Вход подтверждён. Вернитесь на сайт NEUROMIX."
            if approved else "❌ Вход отклонён. Доступ к сайту не предоставлен."
        )
    except Exception:  # noqa: BLE001 - confirmation must survive Telegram edit failures
        logger.warning("Telegram approval message edit failed: telegram_id=%s", callback.from_user.id)
    await callback.answer("Готово")
