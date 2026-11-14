"""Idempotent public feed likes by a verified native VK actor, not a TG user."""
from __future__ import annotations

from bot import database
from bot import db as db_backend


async def like_public_vk_feed(vk_actor_id: int, gen_id: int) -> int | None:
    """Like once per VK actor, atomically adjusting the existing feed counter.

    VK identities are represented in a separate table, never converted to a
    synthetic users.telegram_id or copied to Telegram wallet records.
    """
    if (type(vk_actor_id) is not int or not 0 < vk_actor_id < 2**63
            or type(gen_id) is not int or not 0 < gen_id < 2**63):
        raise ValueError("Invalid signed VK actor or public generation ID")
    # get_feed_generation_card also verifies retained public media availability.
    card = await database.get_feed_generation_card(gen_id, viewer_user_id=None)
    if card is None or card.get("publication_scope") != "feed":
        return None
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        # The same transaction checks current visibility and inserts only
        # for a still-public generation (author may unpublish between reads).
        cursor = await db.execute(
            """INSERT INTO vk_feed_generation_likes (vk_user_id, generation_task_id)
               SELECT ?, id FROM generation_tasks
               WHERE id = ? AND type IN ('image', 'video')
                 AND status = 'completed' AND result_url IS NOT NULL
                 AND is_public_feed = 1 AND COALESCE(is_adult_content, 0) = 0
               ON CONFLICT (vk_user_id, generation_task_id) DO NOTHING""",
            (vk_actor_id, gen_id),
        )
        inserted = cursor.rowcount == 1
        if inserted:
            updated = await db.execute(
                """UPDATE generation_tasks
                   SET likes_count = COALESCE(likes_count, 0) + 1
                   WHERE id = ? AND is_public_feed = 1
                     AND status = 'completed' AND COALESCE(is_adult_content, 0) = 0""",
                (gen_id,),
            )
            if updated.rowcount != 1:
                await db.rollback()
                return None
        if cursor.rowcount not in {0, 1}:
            await db.rollback()
            raise RuntimeError("Uncertain VK like insert result")
        tally = await db.execute(
            """SELECT likes_count FROM generation_tasks
               WHERE id = ? AND is_public_feed = 1
                 AND status = 'completed' AND COALESCE(is_adult_content, 0) = 0""",
            (gen_id,),
        )
        row = await tally.fetchone()
        if not row:
            await db.rollback()
            return None
        total = int(row["likes_count"] or 0)
        await db.commit()
        return total
