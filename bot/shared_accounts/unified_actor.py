"""Verified platform-agnostic ownership without pretending wallets are merged.

All callers get a canonical account UUID and the proven authentication channel.
Never convert a browser-only user to a fake Telegram ID.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl

from bot import db as db_backend
from bot.config import config

from .auth import verify_telegram
from .errors import AuthenticationError
from .store import (
    linked_platforms,
    linked_telegram_id,
    resolve_verified_identity_account,
)

AuthChannel = Literal["telegram", "web"]
WalletAuthority = Literal["telegram_legacy", "web_live"]


@dataclass(frozen=True, slots=True)
class AccountActor:
    account_id: str
    auth_channel: AuthChannel
    telegram_id: int | None
    wallet_authority: WalletAuthority
    telegram_linked: bool = False

    @property
    def can_access_legacy_telegram_wallet(self) -> bool:
        # Merely linking an identity never authorizes a web API to debit the
        # legacy Telegram wallet, or to display the sum of two wallets.
        # Billing authority follows the verified credential and actual studio
        # source, not just the physical browser/native launch channel.
        return self.wallet_authority == "telegram_legacy"

    def payload(self) -> dict:
        return {
            "ok": True,
            "account_id": self.account_id,
            "auth_channel": self.auth_channel,
            "telegram_linked": self.telegram_linked,
            "wallet_authority": self.wallet_authority,
        }


async def resolve_account_actor(request, *, init_data: str | None = None) -> AccountActor:
    """Verify native Telegram initData OR a revocable same-site web cookie.

    Native signed Telegram launch takes precedence. A cookie belonging to an
    unrelated account cannot change the owner of a signed Telegram request.
    This resolver does *not* give permission to debit either wallet.
    """
    if init_data is not None:
        if not isinstance(init_data, str):
            raise AuthenticationError("Invalid launch credentials")
        verified = verify_telegram(
            init_data, config.BOT_TOKEN, max_age=86400,
        )
        # The legacy website/bridge signs its own Telegram-shaped initData
        # with query_id=browser_*. Such credentials must never be confused with
        # a real Telegram WebView launch that can use the Telegram wallet.
        # Require the still-active browser cookie AND its verified TG identity,
        # so a signed bridge cannot outlive logout or cross another account.
        query_id = dict(parse_qsl(init_data, keep_blank_values=True)).get("query_id", "")
        if query_id.startswith("webstudio_"):
            from bot.web_auth import verify_studio_bridge

            account_id = await verify_studio_bridge(query_id, verified.external_id)
            return AccountActor(
                account_id=account_id,
                auth_channel="web",
                telegram_id=verified.external_id,
                # The legacy studio deducts users.credits for a real,
                # verified Telegram link, even when entered from the web.
                wallet_authority="telegram_legacy",
                telegram_linked=True,
            )
        if query_id.startswith("browser_"):
            browser = await resolve_account_actor(request)
            if not browser.telegram_linked:
                raise PermissionError("Telegram account not linked")
            async with db_backend.connect() as db:
                link = await (await db.execute(
                    """SELECT account_id FROM shared_account_identities
                       WHERE platform='telegram' AND external_id=?""",
                    (verified.external_id,),
                )).fetchone()
            if not link or str(link[0]) != browser.account_id:
                raise PermissionError("Telegram link belongs to another account")
            return AccountActor(
                account_id=browser.account_id,
                auth_channel="web", telegram_id=verified.external_id,
                wallet_authority="web_live", telegram_linked=True,
            )
        account_id = await resolve_verified_identity_account(verified)
        return AccountActor(
            account_id=account_id, auth_channel="telegram",
            telegram_id=verified.external_id,
            wallet_authority="telegram_legacy", telegram_linked=True,
        )

    from bot.web_auth import _session_account

    account_id = await _session_account(request)
    if not account_id:
        raise AuthenticationError("Missing or revoked web session")
    platforms = await linked_platforms(account_id)
    telegram_linked = "telegram" in platforms
    # A verified Telegram OIDC account can exist before that user has ever
    # started the bot. Do not conflate this link with a legacy users row.
    linked_id = await linked_telegram_id(account_id) if telegram_linked else None
    return AccountActor(
        account_id=account_id, auth_channel="web",
        telegram_id=linked_id, wallet_authority="web_live",
        telegram_linked=telegram_linked,
    )
