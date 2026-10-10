"""Fresh publication-consent fence in the same transaction as measured debit."""
import json

from bot import database
from bot import db as db_backend
from bot.services.seedance_quote_receipts import QuoteConflict


async def verify_repeat_claim(db, row):
    from bot.handlers.miniapp_video_continuity_compat import _video_repeat_snapshot

    original = json.loads(row["original_json"])
    guard = original.get("_repeat_guard")
    if not guard:
        return
    if guard.get("viewer_user_id") != row["user_id"]:
        raise QuoteConflict("Владелец разрешения на повтор изменился")
    clause, identifier = database._generation_identifier_clause(guard["source_id"])
    current = await (await db.execute(
        f"SELECT * FROM generation_tasks WHERE {clause}" + (" FOR UPDATE" if db_backend.is_postgres() else ""),
        (identifier,),
    )).fetchone()
    if (not current or current["type"] != "video" or current["status"] != "completed"
            or not (current["is_public_feed"] or current["is_profile_visible"])
            or current["is_adult_content"]
            or _video_repeat_snapshot(dict(current)) != guard["snapshot"]):
        raise QuoteConflict("Разрешение на повтор изменилось. Откройте публикацию заново")
    # PostgreSQL publication/consent UPDATE now waits until this transaction
    # commits the debit+receipt, or rollback leaves both untouched.
