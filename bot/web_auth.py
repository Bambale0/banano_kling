"""Independent browser sign-in, verified providers and opt-in account linking.

This is an identity surface, NOT a synthetic Telegram identity. Never expose
provider access tokens or use an email match to merge wallets.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import aiohttp
from aiohttp import web

from bot import db as db_backend
from bot.shared_accounts.schema import ensure_schema as ensure_shared_schema
from bot.shared_accounts.errors import PreviewConflict

_API = "/mini-app/api/web-auth"
_SESSION_COOKIE = "nm_web_session"
_STATE_COOKIE = "nm_web_oauth_state"
_SESSION_SECONDS = 7 * 86400
_FLOW_SECONDS = 600
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}$")
_PROVIDERS = ("google", "yandex", "telegram", "email")

_DDL = (
    """CREATE TABLE IF NOT EXISTS web_auth_sessions (
        token_hash TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES shared_accounts(id),
        created_at_epoch BIGINT NOT NULL,
        expires_at_epoch BIGINT NOT NULL,
        revoked_at_epoch BIGINT)""",
    """CREATE INDEX IF NOT EXISTS web_auth_sessions_expiry
       ON web_auth_sessions(expires_at_epoch)""",
    """CREATE TABLE IF NOT EXISTS web_auth_flows (
        token_hash TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('login', 'link')),
        source_account_id TEXT,
        subject TEXT,
        destination TEXT NOT NULL,
        verifier TEXT,
        created_at_epoch BIGINT NOT NULL,
        expires_at_epoch BIGINT NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS web_auth_flows_limits
       ON web_auth_flows(provider, subject, created_at_epoch)""",
)


class AuthConflict(Exception):
    """A verified identity belongs to another account: never auto-merge funds."""


def _digest(token: str) -> str:
    if not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
        raise ValueError("Invalid token")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _public_origin() -> str:
    value = os.getenv("WEB_AUTH_PUBLIC_ORIGIN", "").strip().rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.netloc or parsed.path
            or parsed.query or parsed.fragment or "@" in parsed.netloc):
        return ""
    return value


def _credentials(provider: str) -> tuple[str, str]:
    prefix = {"google": "WEB_AUTH_GOOGLE", "yandex": "WEB_AUTH_YANDEX"}.get(provider, "")
    if not prefix or not _public_origin():
        return "", ""
    return os.getenv(prefix + "_CLIENT_ID", "").strip(), os.getenv(prefix + "_CLIENT_SECRET", "").strip()


def _email_enabled() -> bool:
    return bool(_public_origin() and os.getenv("WEB_AUTH_SMTP_HOST")
                and os.getenv("WEB_AUTH_SMTP_FROM"))


def _valid_browser_origin(request: web.Request) -> bool:
    # With explicit configured origin use it; otherwise trust only same-host
    # browser POSTs on the public TLS vhost (not untrusted Origin alone).
    expected = _public_origin() or "https://" + request.host
    return request.headers.get("Origin", "") == expected


def _safe_next(raw: str | None) -> str:
    """Only same-origin app/login routes. Prevent //, backslashes and header injection."""
    value = str(raw or "/mini-app/").strip()
    if len(value) > 2048 or any(c in value for c in ("\r", "\n", "\\", "\x00")):
        return "/mini-app/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment or value.startswith("//"):
        return "/mini-app/"
    if parsed.path not in ("/", "/login", "/login/") and not parsed.path.startswith("/mini-app/"):
        return "/mini-app/"
    return parsed.path + (("?" + parsed.query) if parsed.query else "")


def _redirect(path: str) -> web.HTTPFound:
    response = web.HTTPFound(location=path)
    response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    return response


def _json(payload: dict, status: int = 200) -> web.Response:
    return web.json_response(payload, status=status, headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
    })


def _set_session_cookie(response: web.StreamResponse, token: str) -> None:
    response.set_cookie(_SESSION_COOKIE, token, max_age=_SESSION_SECONDS,
                        httponly=True, secure=True, samesite="Lax", path="/")


async def _ensure_tables() -> None:
    async with db_backend.connect() as db:
        await ensure_shared_schema(db)
        if db_backend.is_postgres():
            await db.execute("SELECT pg_advisory_xact_lock(?)", (80420161119,))
        else:
            await db.execute("BEGIN IMMEDIATE")
        try:
            execute_ddl = getattr(db, "execute_native_ddl", db.execute)
            for statement in _DDL:
                await execute_ddl(statement)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def _session_account(request: web.Request) -> str | None:
    raw = request.cookies.get(_SESSION_COOKIE, "")
    try:
        token_hash = _digest(raw)
    except ValueError:
        return None
    await _ensure_tables()
    async with db_backend.connect() as db:
        row = await (await db.execute(
            """SELECT s.account_id FROM web_auth_sessions s
               JOIN shared_accounts a ON a.id = s.account_id
               WHERE s.token_hash = ? AND s.revoked_at_epoch IS NULL
               AND s.expires_at_epoch > ? AND a.status = 'active'""",
            (token_hash, int(time.time())),
        )).fetchone()
        return str(row[0]) if row else None


async def _new_flow(provider: str, mode: str, source: str | None,
                    subject: str | None, destination: str, verifier: str = "") -> str:
    await _ensure_tables()
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    async with db_backend.connect() as db:
        if provider == "email":
            count = await (await db.execute(
                """SELECT COUNT(*) FROM web_auth_flows
                   WHERE provider = 'email' AND subject = ?
                   AND created_at_epoch > ?""", (subject, now - 900),
            )).fetchone()
            if count and int(count[0]) >= 3:
                raise ValueError("Too many email requests")
        await db.execute(
            """INSERT INTO web_auth_flows
               (token_hash, provider, mode, source_account_id, subject,
                destination, verifier, created_at_epoch, expires_at_epoch)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_digest(token), provider, mode, source, subject, destination, verifier, now,
             now + _FLOW_SECONDS),
        )
        await db.commit()
    return token


async def _consume_flow(provider: str, token: str) -> dict | None:
    try:
        token_hash = _digest(token)
    except ValueError:
        return None
    await _ensure_tables()
    async with db_backend.connect() as db:
        if not db_backend.is_postgres():
            await db.execute("BEGIN IMMEDIATE")
        suffix = " FOR UPDATE" if db_backend.is_postgres() else ""
        try:
            cursor = await db.execute(
                """SELECT mode, source_account_id, subject, destination, verifier,
                          expires_at_epoch FROM web_auth_flows
                   WHERE token_hash = ? AND provider = ?""" + suffix,
                (token_hash, provider),
            )
            row = await cursor.fetchone()
            if not row:
                await db.rollback()
                return None
            deleted = await db.execute(
                "DELETE FROM web_auth_flows WHERE token_hash = ? AND provider = ?",
                (token_hash, provider),
            )
            await db.commit()
            if deleted.rowcount != 1 or int(row[5]) <= int(time.time()):
                return None
            return {"mode": row[0], "source": row[1], "subject": row[2],
                    "destination": row[3], "verifier": row[4]}
        except Exception:
            await db.rollback()
            raise


async def _complete_identity(request: web.Request, provider: str, subject: str,
                             flow: dict) -> web.StreamResponse:
    if provider not in _PROVIDERS or not isinstance(subject, str) or not (1 <= len(subject) <= 255):
        return _redirect("/login?error=identity")
    source = flow["source"]
    if flow["mode"] == "link" and (not source or await _session_account(request) != source):
        return _redirect("/login?error=session-expired")
    await _ensure_tables()
    if source:
        from bot.shared_accounts.links import ensure_link_schema
        async with db_backend.connect() as setup_db:
            await ensure_link_schema(setup_db)
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    try:
        async with db_backend.connect() as db:
            if db_backend.is_postgres():
                # Serialize account/identity creation across API workers.
                lock_num = int.from_bytes(hashlib.sha256((provider + ":" + subject).encode()).digest()[:8], "big") % (2**63)
                await db.execute("SELECT pg_advisory_xact_lock(?)", (lock_num,))
            else:
                await db.execute("BEGIN IMMEDIATE")
            try:
                is_telegram = provider == "telegram"
                if is_telegram:
                    external = int(subject)
                    if external <= 0 or external >= 2**63:
                        raise ValueError("Invalid Telegram ID")
                    row = await (await db.execute(
                        "SELECT account_id FROM shared_account_identities WHERE platform = 'telegram' AND external_id = ?",
                        (external,),
                    )).fetchone()
                else:
                    row = await (await db.execute(
                        "SELECT account_id FROM web_auth_identities WHERE provider = ? AND subject = ?",
                        (provider, subject),
                    )).fetchone()
                existing = str(row[0]) if row else None
                if source:
                    account_id = source
                    active = await (await db.execute(
                        "SELECT status FROM shared_accounts WHERE id = ?", (account_id,),
                    )).fetchone()
                    if not active or active[0] != "active":
                        raise ValueError("Account unavailable")
                    if existing and existing != account_id:
                        # Both existing accounts have been independently proven:
                        # a live source browser session plus this fresh verified
                        # provider callback. Preserve wallets through the same
                        # transaction-safe merger used for TG/VK links.
                        from bot.shared_accounts.links import LinkService
                        try:
                            source_session_hash = _digest(request.cookies.get(_SESSION_COOKIE, ""))
                        except (AttributeError, ValueError) as exc:
                            raise AuthConflict() from exc
                        account_id = await LinkService(None)._merge(db, {
                            "id": uuid4().hex,
                            "source_account_id": source,
                            "target_account_id": existing,
                            "_verified_browser_proof": {
                                "session_hash": source_session_hash,
                                "provider": provider,
                                "subject": subject,
                            },
                        })
                        existing = account_id
                    # One connected identity per provider. No silent replacement.
                    if is_telegram:
                        duplicate = await (await db.execute(
                            "SELECT external_id FROM shared_account_identities WHERE account_id = ? AND platform = 'telegram'",
                            (account_id,),
                        )).fetchone()
                        if duplicate and int(duplicate[0]) != external:
                            raise AuthConflict()
                    else:
                        duplicate = await (await db.execute(
                            "SELECT subject FROM web_auth_identities WHERE account_id = ? AND provider = ?",
                            (account_id, provider),
                        )).fetchone()
                        if duplicate and duplicate[0] != subject:
                            raise AuthConflict()
                elif existing:
                    account_id = existing
                else:
                    account_id = uuid4().hex
                    await db.execute("INSERT INTO shared_accounts(id) VALUES (?)", (account_id,))
                if not existing:
                    if is_telegram:
                        await db.execute(
                            """INSERT INTO shared_account_identities(platform, external_id, account_id)
                               VALUES ('telegram', ?, ?)""", (external, account_id),
                        )
                    else:
                        await db.execute(
                            """INSERT INTO web_auth_identities(provider, subject, account_id)
                               VALUES (?, ?, ?)""", (provider, subject, account_id),
                        )
                if is_telegram:
                    legacy = await (await db.execute(
                        "SELECT id FROM users WHERE telegram_id = ?", (external,),
                    )).fetchone()
                    if legacy:
                        old = await (await db.execute(
                            "SELECT account_id FROM shared_account_legacy_links WHERE source = 'telegram' AND legacy_user_id = ?",
                            (legacy[0],),
                        )).fetchone()
                        if old and old[0] != account_id:
                            raise AuthConflict()
                        await db.execute(
                            """INSERT INTO shared_account_legacy_links(source, legacy_user_id, account_id)
                               VALUES ('telegram', ?, ?)
                               ON CONFLICT(source, legacy_user_id) DO NOTHING""",
                            (legacy[0], account_id),
                        )
                active = await (await db.execute(
                    "SELECT status FROM shared_accounts WHERE id = ?", (account_id,),
                )).fetchone()
                if not active or active[0] != "active":
                    raise ValueError("Account unavailable")
                await db.execute(
                    """INSERT INTO web_auth_sessions
                       (token_hash, account_id, created_at_epoch, expires_at_epoch)
                       VALUES (?, ?, ?, ?)""",
                    (_digest(token), account_id, now, now + _SESSION_SECONDS),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    except (AuthConflict, PreviewConflict, ValueError):
        return _redirect("/login?error=already-linked")
    # A link returns to connected methods; sign-in preserves the original route.
    destination = "/login?linked=" + provider if source else _safe_next(flow["destination"])
    response = _redirect(destination)
    _set_session_cookie(response, token)
    return response


async def web_auth_config(request: web.Request) -> web.Response:
    await _ensure_tables()
    account_id = await _session_account(request)
    connected: list[str] = []
    if account_id:
        async with db_backend.connect() as db:
            rows = await (await db.execute(
                "SELECT provider FROM web_auth_identities WHERE account_id = ?",
                (account_id,),
            )).fetchall()
            connected = [str(row[0]) for row in rows]
            row = await (await db.execute(
                "SELECT 1 FROM shared_account_identities WHERE platform = 'telegram' AND account_id = ?",
                (account_id,),
            )).fetchone()
            if row:
                connected.append("telegram")
    return _json({"ok": True, "authenticated": bool(account_id),
                  "account_id": account_id, "connected": sorted(connected),
                  "providers": {
                      "google": all(_credentials("google")),
                      "yandex": all(_credentials("yandex")),
                      "telegram": True,
                      "email": _email_enabled(),
                  }})


def _oauth_urls(provider: str) -> tuple[str, str, str, str]:
    if provider == "google":
        return ("https://accounts.google.com/o/oauth2/v2/auth",
                "https://oauth2.googleapis.com/token",
                "https://openidconnect.googleapis.com/v1/userinfo",
                "openid email profile")
    return ("https://oauth.yandex.ru/authorize",
            "https://oauth.yandex.ru/token",
            "https://login.yandex.ru/info", "login:info login:email")


async def oauth_start(request: web.Request) -> web.StreamResponse:
    provider = request.match_info["provider"]
    if provider not in ("google", "yandex"):
        raise web.HTTPNotFound()
    client_id, client_secret = _credentials(provider)
    if not client_id or not client_secret:
        raise web.HTTPServiceUnavailable(text="OAuth provider is not configured")
    mode = "link" if request.query.get("intent") == "link" else "login"
    account = await _session_account(request)
    if mode == "link" and not account:
        return _redirect("/login?error=session-expired")
    verifier = secrets.token_urlsafe(48)
    challenge = hashlib.sha256(verifier.encode()).digest()
    import base64
    challenge = base64.urlsafe_b64encode(challenge).decode().rstrip("=")
    state = await _new_flow(provider, mode, account if mode == "link" else None, None,
                            _safe_next(request.query.get("next")), verifier)
    authorize, _, _, scope = _oauth_urls(provider)
    callback = _public_origin() + _API + "/callback/" + provider
    url = authorize + "?" + urlencode({
        "client_id": client_id, "redirect_uri": callback, "response_type": "code",
        "scope": scope, "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    response = _redirect(url)
    response.set_cookie(_STATE_COOKIE, _digest(state), httponly=True, secure=True,
                        samesite="Lax", path=_API + "/", max_age=_FLOW_SECONDS)
    return response


async def _remote_json(session: aiohttp.ClientSession, method: str, url: str, **kwargs) -> dict:
    async with session.request(method, url, **kwargs) as resp:
        if resp.status != 200:
            raise ValueError("Identity provider rejected request")
        body = await resp.content.read(32769)
        if len(body) > 32768:
            raise ValueError("Oversized identity response")
        value = json.loads(body)
        if not isinstance(value, dict):
            raise TypeError("Malformed identity response")
        return value


async def oauth_callback(request: web.Request) -> web.StreamResponse:
    provider = request.match_info["provider"]
    if provider not in ("google", "yandex"):
        raise web.HTTPNotFound()
    state = request.query.get("state", "")
    try:
        expected = _digest(state)
    except ValueError:
        return _redirect("/login?error=oauth")
    if not hmac.compare_digest(request.cookies.get(_STATE_COOKIE, ""), expected):
        return _redirect("/login?error=oauth")
    flow = await _consume_flow(provider, state)
    if not flow or not request.query.get("code"):
        return _redirect("/login?error=oauth")
    client_id, client_secret = _credentials(provider)
    if not client_id or not client_secret:
        return _redirect("/login?error=unavailable")
    _, token_url, profile_url, _ = _oauth_urls(provider)
    try:
        timeout = aiohttp.ClientTimeout(total=12, connect=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = await _remote_json(session, "POST", token_url, data={
                "grant_type": "authorization_code", "code": request.query["code"],
                "client_id": client_id, "client_secret": client_secret,
                "redirect_uri": _public_origin() + _API + "/callback/" + provider,
                "code_verifier": flow["verifier"],
            })
            access = data.get("access_token")
            if not isinstance(access, str) or not access:
                raise ValueError("Missing access token")
            profile = await _remote_json(session, "GET", profile_url,
                                         headers={"Authorization": "Bearer " + access})
            subject = profile.get("sub") if provider == "google" else profile.get("id")
            if not isinstance(subject, (str, int)) or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", str(subject)):
                raise ValueError("Missing stable provider subject")
        result = await _complete_identity(request, provider, str(subject), flow)
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError, json.JSONDecodeError):
        result = _redirect("/login?error=oauth")
    result.del_cookie(_STATE_COOKIE, path=_API + "/")
    return result


def _send_magic_link(email: str, link: str) -> None:
    host = os.getenv("WEB_AUTH_SMTP_HOST", "")
    port = int(os.getenv("WEB_AUTH_SMTP_PORT", "587"))
    user = os.getenv("WEB_AUTH_SMTP_USERNAME", "")
    password = os.getenv("WEB_AUTH_SMTP_PASSWORD", "")
    sender = os.getenv("WEB_AUTH_SMTP_FROM", "")
    message = EmailMessage()
    message["From"], message["To"] = sender, email
    message["Subject"] = "NEUROMIX — вход по ссылке"
    message.set_content("Откройте эту ссылку в течение 10 минут:\n\n" + link +
                        "\n\nЕсли вы не запрашивали вход, просто игнорируйте письмо.")
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=10) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            if user:
                smtp.login(user, password)
            smtp.send_message(message)


async def email_start(request: web.Request) -> web.Response:
    if not _email_enabled():
        return _json({"ok": False, "error": "Email sign-in is not configured"}, 503)
    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "Invalid request origin"}, 403)
    if request.content_length and request.content_length > 4096:
        return _json({"ok": False, "error": "Invalid request"}, 413)
    try:
        payload = await request.json()
        email = str(payload.get("email", "")).strip().lower()
        if not _EMAIL_RE.fullmatch(email) or len(email) > 254:
            raise ValueError("Invalid email")
        mode = "link" if payload.get("intent") == "link" else "login"
        account = await _session_account(request)
        if mode == "link" and not account:
            return _json({"ok": False, "error": "Session required"}, 401)
        token = await _new_flow("email", mode, account if mode == "link" else None,
                                email, _safe_next(payload.get("next")))
        url = _public_origin() + _API + "/email/verify?" + urlencode({"ticket": token})
        try:
            await asyncio.wait_for(asyncio.to_thread(_send_magic_link, email, url), timeout=13)
        except (OSError, smtplib.SMTPException, TimeoutError):
            # Unsent challenges are not valid credentials.
            async with db_backend.connect() as db:
                await db.execute("DELETE FROM web_auth_flows WHERE token_hash = ?", (_digest(token),))
                await db.commit()
            return _json({"ok": False, "error": "Email delivery unavailable"}, 503)
        return _json({"ok": True, "message": "Проверьте почту: ссылка действует 10 минут."})
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return _json({"ok": False, "error": "Invalid email or too many requests"}, 400)


async def email_verify(request: web.Request) -> web.StreamResponse:
    flow = await _consume_flow("email", request.query.get("ticket", ""))
    if not flow or not flow["subject"]:
        return _redirect("/login?error=expired")
    return await _complete_identity(request, "email", flow["subject"], flow)


async def telegram_login(request: web.Request) -> web.StreamResponse:
    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "Invalid request origin"}, 403)
    if request.content_length and request.content_length > 8192:
        return _json({"ok": False, "error": "Invalid request"}, 413)
    try:
        from bot.browser_auth import _build_browser_init_data, _verify_telegram_login
        from bot.config import config

        payload = await request.json()
        verified = _verify_telegram_login(payload.get("telegram_auth"), config.BOT_TOKEN)
        mode = "link" if payload.get("intent") == "link" else "login"
        account = await _session_account(request)
        if mode == "link" and not account:
            return _json({"ok": False, "error": "Session required"}, 401)
        flow = {"mode": mode, "source": account if mode == "link" else None,
                "destination": _safe_next(payload.get("next"))}
        result = await _complete_identity(request, "telegram", str(verified["id"]), flow)
        if _SESSION_COOKIE not in result.cookies:
            return _json({"ok": False, "error": "Already linked to another account"}, 409)
        redirect = result.location
        if mode == "login" and redirect.startswith("/mini-app/"):
            from urllib.parse import quote
            fragment = "tgWebAppData=" + quote(_build_browser_init_data(verified, config.BOT_TOKEN), safe="")
            redirect += ("&" if "#" in redirect else "#") + fragment
        response = _json({"ok": True, "redirect": redirect})
        _set_session_cookie(response, result.cookies[_SESSION_COOKIE].value)
        return response
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return _json({"ok": False, "error": "Invalid Telegram signature"}, 401)


async def logout(request: web.Request) -> web.Response:
    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "Invalid request origin"}, 403)
    raw = request.cookies.get(_SESSION_COOKIE, "")
    try:
        digest = _digest(raw)
    except ValueError:
        digest = None
    if digest:
        async with db_backend.connect() as db:
            await db.execute(
                "UPDATE web_auth_sessions SET revoked_at_epoch = ? WHERE token_hash = ?",
                (int(time.time()), digest),
            )
            await db.commit()
    response = _json({"ok": True})
    response.del_cookie(_SESSION_COOKIE, path="/")
    return response


def setup_web_auth_routes(app: web.Application, miniapp_root: str) -> None:
    """Register exact endpoints before /mini-app/api/{tail:.*}."""
    root = miniapp_root + "/api/web-auth"
    app.router.add_get(root + "/config", web_auth_config)
    app.router.add_get(root + "/start/{provider:google|yandex}", oauth_start)
    app.router.add_get(root + "/callback/{provider:google|yandex}", oauth_callback)
    app.router.add_post(root + "/email/start", email_start)
    app.router.add_get(root + "/email/verify", email_verify)
    app.router.add_post(root + "/telegram", telegram_login)
    app.router.add_post(root + "/logout", logout)
