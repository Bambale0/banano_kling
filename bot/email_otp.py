"""One-time email code verification for independent browser identities.

No email delivery is performed during DB transactions. The raw code is never
persisted or logged. All rate limits and attempts are database-backed so that
multiple workers observe the same state.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage

import aiohttp
from aiohttp import web

from bot import db as db_backend

logger = logging.getLogger(__name__)
_CODE_PATTERN = re.compile(r"^[0-9]{6}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_CODE_TTL = 600
_RESEND_COOLDOWN = 60
_RATE_WINDOW = 900
_MAX_EMAIL_SENDS = 3
_MAX_IP_SENDS = 15
_MAX_GUESSES = 5
_RESEND_API = "https://api.resend.com/emails"


class EmailDeliveryError(Exception):
    """Do not leak provider payloads or secret-bearing HTTP headers."""

    def __init__(self, *, uncertain: bool = False):
        super().__init__("Email provider could not confirm delivery")
        self.uncertain = uncertain


_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS web_auth_email_codes (
        challenge_hash TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        code_hash TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('login', 'link')),
        source_account_id TEXT,
        destination TEXT NOT NULL,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        created_at_epoch BIGINT NOT NULL,
        expires_at_epoch BIGINT NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS web_auth_email_codes_expiry
        ON web_auth_email_codes(expires_at_epoch)""",
    """CREATE TABLE IF NOT EXISTS web_auth_email_rate (
        id TEXT PRIMARY KEY,
        email_key TEXT NOT NULL,
        ip_key TEXT NOT NULL,
        created_at_epoch BIGINT NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS web_auth_email_rate_email
        ON web_auth_email_rate(email_key, created_at_epoch)""",
    """CREATE INDEX IF NOT EXISTS web_auth_email_rate_ip
        ON web_auth_email_rate(ip_key, created_at_epoch)""",
)


def email_provider() -> str:
    value = os.getenv("WEB_AUTH_EMAIL_PROVIDER", "").strip().lower()
    if value:
        return value if value in ("resend", "smtp") else ""
    return "resend" if os.getenv("WEB_AUTH_RESEND_API_KEY", "").strip() else "smtp"


def email_enabled() -> bool:
    from bot.web_auth import _public_origin

    if not _public_origin():
        return False
    if email_provider() == "resend":
        return bool(os.getenv("WEB_AUTH_RESEND_API_KEY", "").strip()
                    and os.getenv("WEB_AUTH_RESEND_FROM", "").strip())
    if email_provider() == "smtp":
        return bool(os.getenv("WEB_AUTH_SMTP_HOST", "").strip()
                    and os.getenv("WEB_AUTH_SMTP_FROM", "").strip())
    return False


def _server_secret() -> bytes:
    from bot.config import config

    secret = os.getenv("WEB_AUTH_EMAIL_CODE_SECRET", "").strip() or config.BOT_TOKEN
    if not secret or len(secret) < 12:
        raise RuntimeError("Missing email OTP HMAC secret")
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _code_hash(challenge: str, code: str) -> str:
    # A six-digit SHA-256 can be brute-forced from a stolen DB. Use HMAC with a
    # secret held outside the database, even when the challenge ID is known.
    return hmac.new(_server_secret(), (challenge + ":" + code).encode(),
                    hashlib.sha256).hexdigest()


def _rate_key(kind: str, value: str) -> str:
    return hmac.new(_server_secret(), (kind + ":" + value).encode(),
                    hashlib.sha256).hexdigest()


def _client_ip(request: web.Request) -> str:
    # Nginx sets X-Real-IP from the actual connection peer. Do not trust
    # user-provided forwarded headers from an arbitrary external connection.
    peer = request.remote or ""
    if peer in ("127.0.0.1", "::1"):
        return request.headers.get("X-Real-IP", "") or peer
    return peer


def _email_message(code: str) -> str:
    return (f"Код входа в NEUROMIX: {code}\n\n"
            "Введите этот код на странице входа. Он действует 10 минут.\n"
            "Никому не сообщайте код. Если вы не запрашивали вход, игнорируйте письмо.")


async def _deliver_code(email: str, code: str, request_id: str) -> str:
    """Provider acceptance != inbox delivery; return a provider request ID."""
    if email_provider() == "resend":
        token = os.getenv("WEB_AUTH_RESEND_API_KEY", "").strip()
        sender = os.getenv("WEB_AUTH_RESEND_FROM", "").strip()
        if not token or not sender:
            raise EmailDeliveryError()
        timeout = aiohttp.ClientTimeout(total=10, connect=4)
        headers = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Idempotency-Key": "neuromix-email-otp-" + request_id,
        }
        body = {
            "from": sender,
            "to": [email],
            "subject": "NEUROMIX — код подтверждения",
            "text": _email_message(code),
        }
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(_RESEND_API, headers=headers, json=body) as response:
                    # Never log provider response bodies (may contain PII).
                    if response.status not in (200, 201):
                        raise EmailDeliveryError(uncertain=response.status >= 500)
                    data = await response.json(content_type=None)
                    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
                        raise EmailDeliveryError(uncertain=True)
                    return data["id"]
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise EmailDeliveryError(uncertain=True) from exc
    if email_provider() != "smtp":
        raise EmailDeliveryError()
    await asyncio.wait_for(asyncio.to_thread(_send_smtp, email, code), timeout=12)
    return "smtp-accepted"


def _send_smtp(email: str, code: str) -> None:
    host = os.getenv("WEB_AUTH_SMTP_HOST", "").strip()
    port = int(os.getenv("WEB_AUTH_SMTP_PORT", "587"))
    sender = os.getenv("WEB_AUTH_SMTP_FROM", "").strip()
    username = os.getenv("WEB_AUTH_SMTP_USERNAME", "").strip()
    password = os.getenv("WEB_AUTH_SMTP_PASSWORD", "")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = email
    message["Subject"] = "NEUROMIX — код подтверждения"
    message.set_content(_email_message(code))
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=10, context=context) as smtp:
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)


async def _ensure_schema() -> None:
    from bot.web_auth import _ensure_tables

    await _ensure_tables()
    async with db_backend.connect() as db:
        if db_backend.is_postgres():
            await db.execute("SELECT pg_advisory_xact_lock(?)", (80420161120,))
        else:
            await db.execute("BEGIN IMMEDIATE")
        try:
            ddl = getattr(db, "execute_native_ddl", db.execute)
            for statement in _SCHEMA:
                await ddl(statement)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def _issue(email: str, ip: str, mode: str, source: str | None,
                 destination: str) -> tuple[str, str]:
    """Create persistent OTP challenge with atomic rate limiting."""
    await _ensure_schema()
    now = int(time.time())
    ticket = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    email_key, ip_key = _rate_key("email", email), _rate_key("ip", ip)
    async with db_backend.connect() as db:
        if db_backend.is_postgres():
            # Two concurrent emails from different recipients must still count
            # against the same IP bucket. Lock all affected rate buckets in a
            # deterministic order, avoiding cross-request deadlocks.
            keys = sorted({int(value[:15], 16) for value in (email_key, ip_key)})
            for lock_key in keys:
                await db.execute("SELECT pg_advisory_xact_lock(?)", (lock_key,))
        else:
            await db.execute("BEGIN IMMEDIATE")
        try:
            # Keep history beyond code expiry for request throttling.
            await db.execute(
                "DELETE FROM web_auth_email_rate WHERE created_at_epoch < ?",
                (now - _RATE_WINDOW,),
            )
            await db.execute(
                "DELETE FROM web_auth_email_codes WHERE expires_at_epoch <= ?", (now,),
            )
            email_count = await (await db.execute(
                "SELECT COUNT(*), MAX(created_at_epoch) FROM web_auth_email_rate "
                "WHERE email_key = ? AND created_at_epoch > ?",
                (email_key, now - _RATE_WINDOW),
            )).fetchone()
            ip_count = await (await db.execute(
                "SELECT COUNT(*) FROM web_auth_email_rate WHERE ip_key = ? "
                "AND created_at_epoch > ?", (ip_key, now - _RATE_WINDOW),
            )).fetchone()
            if (int(email_count[0]) >= _MAX_EMAIL_SENDS
                    or int(ip_count[0]) >= _MAX_IP_SENDS
                    or (email_count[1] is not None
                        and now - int(email_count[1]) < _RESEND_COOLDOWN)):
                raise ValueError("Email code cooldown or rate limit")
            await db.execute(
                "DELETE FROM web_auth_email_codes WHERE email = ?", (email,),
            )
            await db.execute(
                """INSERT INTO web_auth_email_codes
                   (challenge_hash, email, code_hash, mode, source_account_id,
                    destination, created_at_epoch, expires_at_epoch)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (hashlib.sha256(ticket.encode()).hexdigest(), email,
                 _code_hash(ticket, code), mode, source, destination,
                 now, now + _CODE_TTL),
            )
            await db.execute(
                """INSERT INTO web_auth_email_rate
                   (id, email_key, ip_key, created_at_epoch) VALUES (?, ?, ?, ?)""",
                (secrets.token_hex(16), email_key, ip_key, now),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return ticket, code


async def _verify(ticket: str, code: str) -> dict | None:
    """One transaction for attempt increment or one-time successful claim."""
    await _ensure_schema()
    if not isinstance(ticket, str) or not _ID_PATTERN.fullmatch(ticket):
        return None
    # Never allow arbitrary Unicode digits or non-exact length.
    if not isinstance(code, str) or not _CODE_PATTERN.fullmatch(code):
        return None
    digest = hashlib.sha256(ticket.encode()).hexdigest()
    expected = _code_hash(ticket, code)
    now = int(time.time())
    async with db_backend.connect() as db:
        if not db_backend.is_postgres():
            await db.execute("BEGIN IMMEDIATE")
        suffix = " FOR UPDATE" if db_backend.is_postgres() else ""
        try:
            row = await (await db.execute(
                """SELECT email, code_hash, mode, source_account_id, destination,
                          failed_attempts, expires_at_epoch
                   FROM web_auth_email_codes WHERE challenge_hash = ?""" + suffix,
                (digest,),
            )).fetchone()
            if not row or int(row[6]) <= now or int(row[5]) >= _MAX_GUESSES:
                await db.rollback()
                return None
            match = hmac.compare_digest(expected, str(row[1]))
            if match:
                deleted = await db.execute(
                    "DELETE FROM web_auth_email_codes WHERE challenge_hash = ?", (digest,),
                )
                await db.commit()
                return ({"mode": row[2], "source": row[3], "subject": row[0],
                         "destination": row[4]} if deleted.rowcount == 1 else None)
            await db.execute(
                """UPDATE web_auth_email_codes
                   SET failed_attempts = failed_attempts + 1
                   WHERE challenge_hash = ?""", (digest,),
            )
            await db.commit()
            return None
        except Exception:
            await db.rollback()
            raise


async def email_start(request: web.Request) -> web.Response:
    from bot import web_auth as auth

    if not email_enabled():
        return auth._json({"ok": False, "error": "Email delivery is not configured"}, 503)
    if not auth._valid_browser_origin(request):
        return auth._json({"ok": False, "error": "Invalid origin"}, 403)
    if request.content_length and request.content_length > 4096:
        return auth._json({"ok": False, "error": "Invalid request"}, 413)
    try:
        body = await request.json()
        email = str(body.get("email", "")).strip().lower()
        if not auth._EMAIL_RE.fullmatch(email) or len(email) > 254:
            return auth._json({"ok": False, "error": "Invalid email"}, 400)
        mode = "link" if body.get("intent") == "link" else "login"
        account = await auth._session_account(request)
        if mode == "link" and not account:
            return auth._json({"ok": False, "error": "Session required"}, 401)
        ticket, code = await _issue(
            email, _client_ip(request), mode, account if mode == "link" else None,
            auth._safe_next(body.get("next")),
        )
    except (ValueError, TypeError, AttributeError):
        # No account existence disclosure; no code or ticket logged.
        return auth._json({"ok": False, "error": "Try again later"}, 429)

    try:
        provider_id = await _deliver_code(email, code, ticket)
        logger.info("web_email_code_accepted provider=%s request_id_hash=%s",
                    email_provider(), hashlib.sha256(ticket.encode()).hexdigest()[:12])
        del provider_id  # Never persist provider credential or recipient address.
    except (EmailDeliveryError, OSError, smtplib.SMTPException, TimeoutError) as exc:
        # Provider 4xx is a definite rejection. An HTTP timeout / 5xx is
        # uncertain: the code may still arrive. Return a challenge for that
        # case so the recipient can redeem it without a duplicate send.
        uncertain = not isinstance(exc, EmailDeliveryError) or exc.uncertain
        logger.warning("web_email_code_delivery_failed provider=%s uncertain=%s",
                       email_provider(), uncertain)
        if uncertain:
            return auth._json({
                "ok": True, "challenge_id": ticket, "expires_in": _CODE_TTL,
                "resend_after": _RESEND_COOLDOWN,
                "message": "Отправка пока не подтверждена. Если код придёт, введите его здесь.",
            }, 202)
        return auth._json({"ok": False, "error": "Email delivery unavailable"}, 503)

    return auth._json({
        "ok": True, "challenge_id": ticket, "expires_in": _CODE_TTL,
        "resend_after": _RESEND_COOLDOWN,
        "message": "На почту отправлен 6-значный код. Введите его здесь.",
    })


async def email_verify(request: web.Request) -> web.Response:
    from bot import web_auth as auth

    if not auth._valid_browser_origin(request):
        return auth._json({"ok": False, "error": "Invalid origin"}, 403)
    if request.content_length and request.content_length > 1024:
        return auth._json({"ok": False, "error": "Invalid request"}, 413)
    try:
        body = await request.json()
        ticket, code = body.get("challenge_id"), body.get("code")
    except (ValueError, TypeError, AttributeError):
        return auth._json({"ok": False, "error": "Invalid verification request"}, 400)
    flow = await _verify(ticket, code)
    if not flow:
        return auth._json({"ok": False, "error": "Invalid or expired code"}, 401)
    result = await auth._complete_identity(request, "email", flow["subject"], flow)
    if auth._SESSION_COOKIE not in result.cookies:
        return auth._json({"ok": False, "error": "Account linking failed"}, 409)
    response = auth._json({"ok": True, "redirect": result.location})
    auth._set_session_cookie(response, result.cookies[auth._SESSION_COOKIE].value)
    return response
