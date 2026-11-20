"""Independent browser sign-in, verified providers and opt-in account linking.

This is an identity surface, NOT a synthetic Telegram identity. Never expose
provider access tokens or use an email match to merge wallets.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import aiohttp
from aiohttp import web

from bot import db as db_backend
from bot.shared_accounts.errors import PreviewConflict
from bot.shared_accounts.schema import ensure_schema as ensure_shared_schema

_API = "/mini-app/api/web-auth"
_SESSION_COOKIE = "nm_web_session"
_STATE_COOKIE = "nm_web_oauth_state"
_SESSION_SECONDS = 7 * 86400
_FLOW_SECONDS = 600
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}$")
_PROVIDERS = ("google", "yandex", "telegram", "email")
_WEB_REFERRAL_RE = re.compile(r"^NW[A-F0-9]{16}$")


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
    """CREATE TABLE IF NOT EXISTS web_referral_codes (
        code TEXT PRIMARY KEY,
        account_id TEXT NOT NULL UNIQUE REFERENCES shared_accounts(id),
        created_at_epoch BIGINT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS web_referral_attributions (
        referred_account_id TEXT PRIMARY KEY REFERENCES shared_accounts(id),
        referrer_account_id TEXT NOT NULL REFERENCES shared_accounts(id),
        created_at_epoch BIGINT NOT NULL,
        CHECK(referred_account_id != referrer_account_id))""",
    """CREATE INDEX IF NOT EXISTS web_referral_referrer
       ON web_referral_attributions(referrer_account_id)""",
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
    from bot.email_otp import email_enabled

    return email_enabled()


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
                # Only a newly created account may adopt a referral. Linking
                # an existing identity must never rewrite its attribution.
                if not source and not existing:
                    destination = _safe_next(flow.get("destination"))
                    ref = parse_qs(urlsplit(destination).query).get("ref", [""])[0]
                    if _WEB_REFERRAL_RE.fullmatch(ref):
                        ref_owner = await (await db.execute(
                            "SELECT account_id FROM web_referral_codes WHERE code = ?",
                            (ref,),
                        )).fetchone()
                        if ref_owner and str(ref_owner[0]) != account_id:
                            await db.execute(
                                """INSERT INTO web_referral_attributions
                                   (referred_account_id, referrer_account_id, created_at_epoch)
                                   VALUES (?, ?, ?)
                                   ON CONFLICT(referred_account_id) DO NOTHING""",
                                (account_id, str(ref_owner[0]), now),
                            )
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
    from bot.shared_accounts.store import linked_telegram_id
    studio_ready = bool(account_id and await linked_telegram_id(account_id))
    return _json({"ok": True, "authenticated": bool(account_id),
                  "account_id": account_id, "connected": sorted(connected),
                  "studio_ready": studio_ready,
                  "providers": {
                      "google": all(_credentials("google")),
                      "yandex": all(_credentials("yandex")),
                      "telegram": True,
                      "email": _email_enabled(),
                  }})


async def web_referral_link(request: web.Request) -> web.Response:
    """Stable, messenger-independent referral link for a verified web account.

    Registration attribution is written when a new verified identity signs in.
    No money or referral reward is credited on mere registration.
    """
    account_id = await _session_account(request)
    if not account_id:
        return _json({"ok": False, "error": "session_required"}, 401)
    await _ensure_tables()
    async with db_backend.connect() as db:
        if db_backend.is_postgres():
            lock = int.from_bytes(hashlib.sha256(
                ("web:referral:" + account_id).encode()).digest()[:8], "big") % (2**63)
            await db.execute("SELECT pg_advisory_xact_lock(?)", (lock,))
        else:
            await db.execute("BEGIN IMMEDIATE")
        row = await (await db.execute(
            "SELECT code FROM web_referral_codes WHERE account_id = ?", (account_id,),
        )).fetchone()
        if row:
            code = str(row[0])
        else:
            code = "NW" + secrets.token_hex(8).upper()
            await db.execute(
                """INSERT INTO web_referral_codes(code, account_id, created_at_epoch)
                   VALUES (?, ?, ?) ON CONFLICT(account_id) DO NOTHING""",
                (code, account_id, int(time.time())),
            )
            row = await (await db.execute(
                "SELECT code FROM web_referral_codes WHERE account_id = ?",
                (account_id,),
            )).fetchone()
            if not row:
                raise RuntimeError("Referral code persistence failed")
            code = str(row[0])
        registrations = await (await db.execute(
            "SELECT COUNT(*) FROM web_referral_attributions WHERE referrer_account_id = ?",
            (account_id,),
        )).fetchone()
        await db.commit()
    return _json({
        "ok": True, "code": code,
        "url": _public_origin() + "/login?" + urlencode({"ref": code}),
        "registrations": int(registrations[0]),
    })


async def web_account(request: web.Request) -> web.Response:
    """A first-class browser identity; never manufacture a Telegram user ID.

    This endpoint exposes only the independently owned account and its own
    ledger. The Telegram Mini App and its legacy wallet are not consulted.
    Generation/payment controls remain disabled until their native web
    account-scoped adapters have been implemented and audited.
    """
    account_id = await _session_account(request)
    if not account_id:
        return _json({"ok": False, "error": "session_required"}, 401)
    from bot.shared_accounts.wallet import WalletService

    async with db_backend.connect() as db:
        rows = await (await db.execute(
            "SELECT provider FROM web_auth_identities WHERE account_id = ?",
            (account_id,),
        )).fetchall()
        linked = await (await db.execute(
            """SELECT 1 FROM shared_account_identities
               WHERE platform = 'telegram' AND account_id = ?""",
            (account_id,),
        )).fetchone()

    balance = (await WalletService("live").snapshot(account_id))["balance"]
    return _json({
        "ok": True, "account_id": account_id, "studio_mode": "web",
        "connected": sorted(str(row[0]) for row in rows),
        "telegram_linked": bool(linked),
        "providers": {
            "yandex": all(_credentials("yandex")),
            "google": all(_credentials("google")),
            "email": _email_enabled(),
        },
        "balance": balance,
        # This is a real account, but the legacy Telegram-dependent generation
        # pipeline is explicitly inaccessible: no counterfeit identity or funds.
        "can_generate": False,
    })


def _oauth_urls(provider: str) -> tuple[str, str, str, str]:
    if provider == "google":
        return ("https://accounts.google.com/o/oauth2/v2/auth",
                "https://oauth2.googleapis.com/token",
                "https://openidconnect.googleapis.com/v1/userinfo",
                "openid email profile")
    # Yandex's registered application permissions are authoritative.
    # Explicitly requesting login:email when only Yandex ID login is enabled
    # causes invalid_scope before the user can approve sign-in.
    return ("https://oauth.yandex.ru/authorize",
            "https://oauth.yandex.ru/token",
            "https://login.yandex.ru/info", "")


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
    # Never redirect an unlinked browser-only identity into Telegram-only
    # Mini App routes. /login resolves the verified web session safely.
    destination = _safe_next(request.query.get("next"))
    if destination.startswith("/mini-app/") or destination == "/":
        destination = "/login"
    state = await _new_flow(provider, mode, account if mode == "link" else None, None,
                            destination, verifier)
    authorize, _, _, scope = _oauth_urls(provider)
    callback = _public_origin() + _API + "/callback/" + provider
    params = {
        "client_id": client_id, "redirect_uri": callback, "response_type": "code",
        "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if scope:
        params["scope"] = scope
    url = authorize + "?" + urlencode(params)
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
            # Yandex ID requires "Authorization: OAuth <token>" for /info;
            # Google's OIDC UserInfo endpoint accepts Bearer.
            profile_auth = "OAuth " if provider == "yandex" else "Bearer "
            profile = await _remote_json(session, "GET", profile_url,
                                         headers={"Authorization": profile_auth + access})
            subject = profile.get("sub") if provider == "google" else profile.get("id")
            if not isinstance(subject, (str, int)) or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", str(subject)):
                raise ValueError("Missing stable provider subject")
        result = await _complete_identity(request, provider, str(subject), flow)
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError, json.JSONDecodeError):
        result = _redirect("/login?error=oauth")
    result.del_cookie(_STATE_COOKIE, path=_API + "/")
    return result


async def web_auth_studio(request: web.Request) -> web.Response:
    """Enter legacy Mini App only if the browser account owns a real Telegram link.

    Verified Yandex-only users remain web identities. This endpoint never
    manufactures Telegram IDs or reassigns legacy wallets.
    """
    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "origin_rejected"}, 403)
    account_id = await _session_account(request)
    if not account_id:
        return _json({"ok": False, "error": "session_required"}, 401)
    from bot.shared_accounts.store import linked_telegram_id
    telegram_id = await linked_telegram_id(account_id)
    if not telegram_id:
        return _json({"ok": False, "error": "needs_telegram_link"}, 409)
    async with db_backend.connect() as db:
        owner = await (await db.execute(
            "SELECT username, first_name, last_name, photo_url "
            "FROM users WHERE telegram_id = ?", (telegram_id,),
        )).fetchone()
    if owner is None:
        return _json({"ok": False, "error": "missing_telegram_owner"}, 409)
    from bot.browser_auth import _build_browser_init_data
    from bot.config import config
    payload = {
        "id": telegram_id, "username": str(owner[0] or ""),
        "first_name": str(owner[1] or ""), "last_name": str(owner[2] or ""),
        "photo_url": str(owner[3] or ""), "language_code": "ru",
    }
    return _json({"ok": True,
                  "init_data": _build_browser_init_data(payload, config.BOT_TOKEN)})


async def email_start(request: web.Request) -> web.Response:
    from bot.email_otp import email_start as start_otp

    return await start_otp(request)


async def email_verify(request: web.Request) -> web.Response:
    from bot.email_otp import email_verify as verify_otp

    return await verify_otp(request)


async def telegram_oidc_login(request: web.Request) -> web.Response:
    """Verified Telegram OIDC login/link into a shared-account web session.

    The OIDC nonce is issued by the existing Telegram browser-auth config.
    Never treat an unsigned JSON profile or an id_token without that cookie as
    proof of account ownership.
    """
    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "Invalid origin"}, 403)
    if request.content_length and request.content_length > 8192:
        return _json({"ok": False, "error": "Invalid request"}, 413)
    from bot.browser_auth import (
        _OIDC_NONCE_COOKIE, _telegram_oidc_client_id, _build_browser_init_data,
    )
    from bot.telegram_oidc import fetch_telegram_jwks, verify_telegram_id_token
    from bot.config import config

    try:
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("id_token"), str):
            raise ValueError("Invalid Telegram OIDC payload")
        nonce = request.cookies.get(_OIDC_NONCE_COOKIE, "")
        client_id = _telegram_oidc_client_id()
        if not nonce or not client_id:
            raise ValueError("Missing Telegram OIDC challenge")
        verified = verify_telegram_id_token(
            body["id_token"], client_id=client_id, nonce=nonce,
            jwks=await fetch_telegram_jwks(),
        )
        mode = "link" if body.get("intent") == "link" else "login"
        source = await _session_account(request)
        if mode == "link" and not source:
            return _json({"ok": False, "error": "Session required"}, 401)
        flow = {
            "mode": mode,
            "source": source if mode == "link" else None,
            "destination": _safe_next(body.get("next")),
        }
        completed = await _complete_identity(request, "telegram", str(verified["id"]), flow)
        if _SESSION_COOKIE not in completed.cookies:
            return _json({"ok": False, "error": "Account linking failed"}, 409)
        payload = {
            "ok": True, "redirect": completed.location,
        }
        payload["init_data"] = _build_browser_init_data(verified, config.BOT_TOKEN)
        response = _json(payload)
        _set_session_cookie(response, completed.cookies[_SESSION_COOKIE].value)
        response.del_cookie(
            _OIDC_NONCE_COOKIE,
            path=(config.MINI_APP_PATH or "/mini-app").rstrip("/") + "/api/browser-auth",
            secure=True, httponly=True, samesite="Lax",
        )
        return response
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return _json({"ok": False, "error": "Invalid Telegram proof"}, 401)
    except (aiohttp.ClientError, TimeoutError, ConnectionError):
        return _json({"ok": False, "error": "Telegram verification unavailable"}, 503)


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
        response = _json({
            "ok": True, "redirect": redirect,
            "init_data": _build_browser_init_data(verified, config.BOT_TOKEN),
        })
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
    app.router.add_get(root + "/account", web_account)
    app.router.add_get(root + "/referral", web_referral_link)
    from bot.web_tasks import setup_web_task_routes
    setup_web_task_routes(app, root)
    app.router.add_post(root + "/studio", web_auth_studio)
    app.router.add_get(root + "/start/{provider:google|yandex}", oauth_start)
    app.router.add_get(root + "/callback/{provider:google|yandex}", oauth_callback)
    app.router.add_post(root + "/email/start", email_start)
    app.router.add_post(root + "/email/verify", email_verify)
    app.router.add_post(root + "/telegram", telegram_login)
    app.router.add_post(root + "/logout", logout)
