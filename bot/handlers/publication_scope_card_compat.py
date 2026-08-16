"""Normalize feed publication results to the scoped card contract."""

from __future__ import annotations

from functools import wraps

from bot import database

from . import publication_scope_compat as scope_module

_INSTALLED = False


def install_publication_scope_card_compat() -> None:
    """Ensure feed publication returns the same scope fields as profile publication.

    ``publication_scope_compat`` delegates feed writes to the established database
    implementation. That implementation returns the legacy card shape, so callers
    could publish successfully but receive a card without ``is_public_feed`` and
    the other scope flags. Re-fetching the just-published row through the scoped
    card builder keeps the write path unchanged while making the response contract
    consistent for Telegram, Mini App and tests.
    """

    global _INSTALLED
    if _INSTALLED:
        return

    original_share = scope_module.share_to_feed_scoped

    @wraps(original_share)
    async def share_to_feed_with_scoped_card(gen_id, user_id, **kwargs):
        card = await original_share(gen_id, user_id, **kwargs)
        if not card:
            return card

        identifier = card.get("id") or gen_id
        scoped_card = await scope_module._profile_card(
            identifier,
            viewer_user_id=user_id,
            require_visible=True,
        )
        return scoped_card or card

    scope_module.share_to_feed_scoped = share_to_feed_with_scoped_card
    database.share_to_feed = share_to_feed_with_scoped_card
    _INSTALLED = True
