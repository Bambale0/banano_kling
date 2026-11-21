"""Website-native public profiles and referral attribution without Telegram credentials.

The referral ledger records owner proof and idempotent signup attribution. It
does NOT move balances, award partner money or infer a legacy Telegram user.
"""
from __future__ import annotations

import re
import secrets
import time
from urllib.parse import urlencode

from aiohttp import web

from bot import db as db_backend

_CODE = re.compile(r"^[A-Z0-9_-]{1,60}$")
_DDL = (
    """CREATE TABLE IF NOT EXISTS web_public_profile_codes (
       account_id TEXT PRIMARY KEY REFERENCES shared_accounts(id),
       code TEXT UNIQUE NOT NULL,
       created_at_epoch BIGINT NOT NULL)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS web_public_profile_codes_code
       ON web_public_profile_codes(code)""",
    """CREATE TABLE IF NOT EXISTS web_referral_attributions (
       referred_account_id TEXT PRIMARY KEY REFERENCES shared_accounts(id),
       referrer_account_id TEXT REFERENCES shared_accounts(id),
       referrer_legacy_user_id BIGINT REFERENCES users(id),
       code TEXT NOT NULL,
       created_at_epoch BIGINT NOT NULL,
       CHECK(referrer_account_id IS NOT NULL OR referrer_legacy_user_id IS NOT NULL))""",
    """CREATE INDEX IF NOT EXISTS web_referral_attributions_inviter
       ON web_referral_attributions(referrer_account_id)""",
)


async def _ensure_schema():
    from bot.web_auth import _ensure_tables

    await _ensure_tables()
    async with db_backend.connect() as db:
        if db_backend.is_postgres():
            await db.execute("SELECT pg_advisory_xact_lock(?)", (80420161120,))
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


def _normalized_code(value) -> str:
    if not isinstance(value, str):
        return ""
    code = value.strip().upper()
    return code if _CODE.fullmatch(code) else ""


async def _owner_code(db, account: str) -> str:
    """Create one stable public code; linked users retain existing TG promo code."""
    found = await (await db.execute(
        "SELECT code FROM web_public_profile_codes WHERE account_id=?",
        (account,),
    )).fetchone()
    if found:
        return str(found[0])
    linked = await (await db.execute(
        """SELECT u.referral_code FROM users u JOIN shared_account_legacy_links l
           ON l.legacy_user_id=u.id AND l.source='telegram'
           WHERE l.account_id=? LIMIT 2""", (account,),
    )).fetchall()
    previous = _normalized_code(linked[0][0]) if len(linked) == 1 else ""
    for index in range(8):
        candidate = previous if index == 0 and previous else "W" + secrets.token_hex(7).upper()
        await db.execute(
            """INSERT INTO web_public_profile_codes(account_id,code,created_at_epoch)
               VALUES(?,?,?) ON CONFLICT DO NOTHING""",
            (account, candidate, int(time.time())),
        )
        row = await (await db.execute(
            "SELECT code FROM web_public_profile_codes WHERE account_id=?",
            (account,),
        )).fetchone()
        if row:
            return str(row[0])
    raise RuntimeError("Unable to allocate public code")


def _website_links(origin: str, code: str) -> dict:
    return {
        "code": code,
        "profile_link": origin + "/mini-app/?" + urlencode(
            {"web": "1", "profile": code, "ref": code}),
        "referral_link": origin + "/login?" + urlencode({"web": "1", "ref": code}),
    }


async def public_links(request: web.Request) -> web.Response:
    from bot.web_auth import _json, _public_origin, _session_account

    account = await _session_account(request)
    if not account:
        return _json({"ok": False, "error": "session_required"}, 401)
    origin = _public_origin()
    if not origin:
        return _json({"ok": False, "error": "website_origin_unconfigured"}, 503)
    await _ensure_schema()
    async with db_backend.connect() as db:
        if not db_backend.is_postgres():
            await db.execute("BEGIN IMMEDIATE")
        # A code is a public identity. No legacy/referral/balance writes.
        code = await _owner_code(db, account)
        await db.commit()
    return _json({"ok": True, **_website_links(origin, code)})


async def _find_owner(db, code: str):
    owner = await (await db.execute(
        "SELECT account_id FROM web_public_profile_codes WHERE code=?",
        (code,),
    )).fetchone()
    if owner:
        from bot.shared_accounts.wallet import canonical_account
        try:
            return await canonical_account(db, str(owner[0])), None
        except (PermissionError, ValueError):
            return None, None
    legacy = await (await db.execute(
        "SELECT id FROM users WHERE referral_code=? LIMIT 2",
        (code,),
    )).fetchall()
    if len(legacy) != 1:
        return None, None
    legacy_id = int(legacy[0][0])
    linked = await (await db.execute(
        """SELECT l.account_id FROM shared_account_legacy_links l
           JOIN shared_accounts a ON a.id=l.account_id AND a.status='active'
           WHERE l.source='telegram' AND l.legacy_user_id=? LIMIT 2""",
        (legacy_id,),
    )).fetchall()
    if len(linked) == 1:
        from bot.shared_accounts.wallet import canonical_account
        try:
            return await canonical_account(db, str(linked[0][0])), legacy_id
        except (PermissionError, ValueError):
            pass
    return None, legacy_id


async def public_profile(request: web.Request) -> web.Response:
    from bot.web_auth import _json

    code = _normalized_code(request.query.get("code"))
    if not code:
        return _json({"ok": False, "error": "invalid_code"}, 400)
    await _ensure_schema()
    async with db_backend.connect() as db:
        owner, legacy_id = await _find_owner(db, code)
        if owner and legacy_id is None:
            row = await (await db.execute(
                """SELECT u.id FROM users u JOIN shared_account_legacy_links l
                   ON l.legacy_user_id=u.id AND l.source='telegram'
                   WHERE l.account_id=? LIMIT 2""",
                (owner,),
            )).fetchall()
            legacy_id = int(row[0][0]) if len(row) == 1 else None
        if owner is None and legacy_id is None:
            return _json({"ok": False, "error": "profile_not_found"}, 404)
        display = "Автор NEUROMIX"
        if legacy_id is not None:
            row = await (await db.execute(
                "SELECT username,first_name,last_name FROM users WHERE id=?",
                (legacy_id,),
            )).fetchone()
            if row:
                # Only fields already shown on public Telegram profiles.
                name = " ".join(str(s or "").strip() for s in (row[1], row[2])).strip()
                display = name[:80] if name else (
                    ("@" + str(row[0]).lstrip("@")[:64]) if row[0] else display)
    return _json({"ok": True, "code": code, "display_name": display})


async def _existing_attribution(db, account: str):
    """Protect one-time signup attribution across verified account merges.

    Merged aliases remain in shared_accounts and may own prior web history.
    Never grant a second invitation by moving a browser identity to a new
    canonical account, even before there are any financial rewards.
    """
    return await (await db.execute(
        """WITH RECURSIVE aliases(id) AS (
             SELECT ? UNION ALL
             SELECT a.id FROM shared_accounts a
             JOIN aliases o ON a.merged_into=o.id WHERE a.status='merged'
           )
           SELECT r.code FROM web_referral_attributions r
           WHERE r.referred_account_id IN (SELECT id FROM aliases)
           LIMIT 1""",
        (account,),
    )).fetchone()


async def _has_any_prior_web_activity(db, account: str) -> bool:
    # Referrals are registration-time only, never post-purchase retroactive.
    for table in ("web_payment_orders", "web_generation_tasks"):
        if db_backend.is_postgres():
            exists = await (await db.execute(
                "SELECT to_regclass(?) IS NOT NULL", (table,),
            )).fetchone()
        else:
            exists = await (await db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )).fetchone()
        if not exists or not exists[0]:
            continue
        row = await (await db.execute(
            """WITH RECURSIVE aliases(id) AS (
                 SELECT ? UNION ALL
                 SELECT a.id FROM shared_accounts a JOIN aliases o
                 ON a.merged_into=o.id WHERE a.status='merged'
               )
               SELECT 1 FROM """ + table +
            " WHERE account_id IN (SELECT id FROM aliases) LIMIT 1",
            (account,),
        )).fetchone()
        if row:
            return True
    return False


async def attach_referral(request: web.Request) -> web.Response:
    from bot.web_auth import _json, _session_account, _valid_browser_origin

    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "origin_rejected"}, 403)
    if request.content_length and request.content_length > 2048:
        return _json({"ok": False, "error": "request_too_large"}, 413)
    account = await _session_account(request)
    if not account:
        return _json({"ok": False, "error": "session_required"}, 401)
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) != {"code"}:
            return _json({"ok": False, "error": "invalid_payload"}, 400)
        code = _normalized_code(payload["code"])
        if not code:
            return _json({"ok": False, "error": "invalid_code"}, 400)
    except (ValueError, TypeError):
        return _json({"ok": False, "error": "invalid_payload"}, 400)
    await _ensure_schema()
    async with db_backend.connect() as db:
        if not db_backend.is_postgres():
            await db.execute("BEGIN IMMEDIATE")
        suffix = " FOR UPDATE" if db_backend.is_postgres() else ""
        row = await (await db.execute(
            "SELECT status FROM shared_accounts WHERE id=?" + suffix, (account,),
        )).fetchone()
        if not row or row[0] != "active":
            return _json({"ok": False, "error": "account_unavailable"}, 403)
        native = await (await db.execute(
            """SELECT 1 FROM shared_account_identities
               WHERE platform IN ('telegram','vk') AND account_id=? LIMIT 1""",
            (account,),
        )).fetchone()
        if native:
            return _json({"ok": False, "error": "legacy_referral_authority"}, 409)
        existing = await _existing_attribution(db, account)
        if existing:
            return _json({"ok": existing[0] == code, "attached": False,
                          "code": str(existing[0]),
                          "error": None if existing[0] == code else "already_attributed"},
                         200 if existing[0] == code else 409)
        inviter, legacy_id = await _find_owner(db, code)
        if inviter is None and legacy_id is None:
            return _json({"ok": False, "error": "referral_not_found"}, 404)
        if inviter == account:
            return _json({"ok": False, "error": "self_referral"}, 409)
        if await _has_any_prior_web_activity(db, account):
            return _json({"ok": False, "error": "referral_after_activity"}, 409)
        created = await db.execute(
            """INSERT INTO web_referral_attributions
               (referred_account_id,referrer_account_id,referrer_legacy_user_id,
                code,created_at_epoch) VALUES (?,?,?,?,?)
               ON CONFLICT(referred_account_id) DO NOTHING""",
            (account, inviter, legacy_id, code, int(time.time())),
        )
        saved = await (await db.execute(
            "SELECT code FROM web_referral_attributions WHERE referred_account_id=?",
            (account,),
        )).fetchone()
        await db.commit()
    if not saved or saved[0] != code:
        return _json({"ok": False, "error": "already_attributed"}, 409)
    # Financial reward is not granted here. Provider-paid referral rewards
    # require a separately audited wallet payout and anti-fraud reconciliation.
    return _json({"ok": True, "attached": created.rowcount == 1, "code": code})


def register_routes(app: web.Application, root: str) -> None:
    root = root.rstrip("/") + "/api/web-auth"
    app.router.add_get(root + "/public-links", public_links)
    app.router.add_get(root + "/public-profile", public_profile)
    app.router.add_post(root + "/referral/attach", attach_referral)
