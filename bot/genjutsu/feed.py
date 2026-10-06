"""Publish owned final outputs, keeping their repeat plans in RecipeStore only."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from .contract import PipelineError, asset_ids, fingerprint, text
from .repository import encode, one


async def copy_public_output(media, asset: dict, step_id: str, *, directory: Path, base_url: str) -> str:
    """Copy only a validated final output; signed private URLs never enter Feed."""
    source = media.path(asset["storage_key"])
    if asset["kind"] != "video" or not source.is_file() or source.suffix not in {".mp4", ".webm"}:
        raise PipelineError("result_unavailable", status=404)
    filename = "genjutsu-" + uuid5(NAMESPACE_URL, "genjutsu-feed:" + step_id).hex + source.suffix
    destination = directory / filename

    def copy():
        directory.mkdir(parents=True, exist_ok=True)
        if destination.is_file() and destination.stat().st_size == source.stat().st_size:
            return
        temporary = directory / ("." + uuid4().hex + ".tmp")
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    try:
        await asyncio.to_thread(copy)
    except OSError as exc:
        raise PipelineError("feed_storage_failed", status=503) from exc
    return base_url.rstrip("/") + "/uploads/feed/" + filename


class FeedPublisher:
    def __init__(self, repository, recipes, copy_output):
        self.repository = repository
        self.recipes = recipes
        self.copy_output = copy_output

    async def publish(self, owner: int, run_id: str, step_id: str, title: str, source_binding: str) -> dict:
        title = text(title, 120, "invalid_title").strip()
        if not title:
            raise PipelineError("invalid_title")
        if source_binding not in {"user", "fixed"}:
            raise PipelineError("invalid_source_binding")

        run = await self.repository.get_run(owner, run_id)
        if run["private_recipe"] or await self.recipes.is_private_project(run["project_id"]):
            raise PipelineError("private_recipe_publication_forbidden", status=403)
        step = next((item for item in run["steps"] if item["id"] == step_id), None)
        if (
            run["state"] != "completed"
            or not step
            or step["status"] != "completed"
            or step["ordinal"] != len(run["plan"]["steps"]) - 1
            or not step["output_asset_id"]
        ):
            raise PipelineError("completed_output_required", status=409)
        # Publication grants access only to this owner's original inputs.
        # A copied/rebound private recipe must never become a new public recipe.
        owned = await self.repository.get_assets(
            owner, asset_ids(run["plan"]) | {step["output_asset_id"]}
        )
        output = owned[step["output_asset_id"]]
        if output["kind"] != "video":
            raise PipelineError("result_unavailable", status=404)
        async with self.repository.connect() as db:
            quote = await one(db, "SELECT revision,plan FROM genjutsu_quotes WHERE id=? AND owner=?", (run["quote_id"], owner))
            existing = await one(db, "SELECT * FROM genjutsu_feed_publications WHERE step_id=?", (step_id,))
        if not quote or fingerprint(json.loads(quote["plan"])) != fingerprint(run["plan"]):
            raise PipelineError("recipe_integrity_failed", status=409)
        if existing and (existing["title"] != title or existing["source_binding"] != source_binding):
            raise PipelineError("feed_publication_conflict", status=409)

        result_url = await self.copy_output(output, step_id)
        task_id = "genjutsu-feed-" + step_id
        now = self.repository.clock()
        recipe_id = existing["recipe_id"] if existing else uuid4().hex
        async with self.repository.transaction() as db:
            # Recheck mutable authorization inside the serialization boundary.
            current = await one(db, """SELECT r.state,r.private_recipe,s.status,s.output_asset_id
                FROM genjutsu_runs r JOIN genjutsu_steps s ON s.run_id=r.id
                WHERE r.id=? AND r.owner=? AND s.id=?""", (run_id, owner, step_id))
            private = await one(db, "SELECT project_id FROM genjutsu_recipe_projects WHERE project_id=?", (run["project_id"],))
            if private or (current and current["private_recipe"]):
                raise PipelineError("private_recipe_publication_forbidden", status=403)
            if not current or current["state"] != "completed" or current["status"] != "completed" or current["output_asset_id"] != output["id"]:
                raise PipelineError("completed_output_required", status=409)
            user = await one(db, "SELECT id FROM users WHERE telegram_id=?", (owner,))
            if not user:
                raise PipelineError("unauthorized", status=403)
            previous = await one(db, "SELECT * FROM genjutsu_feed_publications WHERE step_id=?", (step_id,))
            if previous:
                if previous["title"] != title or previous["source_binding"] != source_binding:
                    raise PipelineError("feed_publication_conflict", status=409)
                recipe_id = previous["recipe_id"]
                recipe = await one(db, "SELECT active FROM genjutsu_recipes WHERE id=?", (recipe_id,))
                if not recipe or recipe["active"] != 1:
                    raise PipelineError("recipe_unavailable", status=404)
                # Ordinary publication edits do not lock genjutsu_control.
                # Lock their task row before checking visibility so a concurrent
                # withdrawal cannot commit between this check and our UPDATE.
                await db.execute("UPDATE generation_tasks SET updated_at=updated_at WHERE task_id=?", (previous["task_id"],))
                publication = await one(db, "SELECT is_public_feed,is_adult_content FROM generation_tasks WHERE task_id=?", (previous["task_id"],))
                if not publication or publication["is_public_feed"] != 1 or publication["is_adult_content"]:
                    raise PipelineError("feed_publication_withdrawn", status=409)
            else:
                await db.execute("""INSERT INTO genjutsu_recipes(
                    id,owner,project_id,revision,verification_run_id,title,plan,user_fields,
                    source_binding,active,created_ms,updated_ms
                    ) VALUES(?,?,?,?,?,?,?,?,?,1,?,?)""",
                    (recipe_id, owner, run["project_id"], quote["revision"], run_id, title,
                     encode(run["plan"]), "[]", source_binding, now, now))
                cost = 0 if run["admin_free"] else sum(
                    int(item["actual_credits"] or 0) for item in run["steps"]
                    if item["variant"] == step["variant"]
                )
                await db.execute("""INSERT INTO generation_tasks(
                    user_id,telegram_id,task_id,type,preset_id,model,duration,prompt,cost,
                    request_data,status,result_url,result_urls,completed_at,updated_at
                    ) VALUES(?,?,?,'video','genjutsu','genjutsu',?,'',?,?,'completed',?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
                    (user["id"], owner, task_id, (int(output.get("duration_ms") or 0) + 999) // 1000, cost,
                     encode({"genjutsu_recipe_id": recipe_id, "genjutsu_title": title}), result_url, encode([result_url])))
                await db.execute("""INSERT INTO genjutsu_feed_publications(
                    step_id,run_id,recipe_id,task_id,title,source_binding,created_ms
                    ) VALUES(?,?,?,?,?,?,?)""", (step_id, run_id, recipe_id, task_id, title, source_binding, now))
            await db.execute("""UPDATE generation_tasks SET is_public_feed=1,is_profile_visible=1,
                is_adult_content=0,feed_prompt_visible=0,feed_references_visible=0,
                feed_reference_selection=NULL,feed_repeat_reference_selection=NULL,
                feed_published_at=COALESCE(feed_published_at,CURRENT_TIMESTAMP),
                result_url=?,result_urls=?,updated_at=CURRENT_TIMESTAMP
                WHERE task_id=? AND user_id=?""", (result_url, encode([result_url]), task_id, user["id"]))
            if not previous:
                await self.repository._event(db, "feed_published", run_id=run_id, step_id=step_id, actor=owner,
                                             details={"recipe_id": recipe_id, "task_id": task_id})
        from bot.database import get_feed_generation_card

        card = await get_feed_generation_card(task_id, viewer_user_id=user["id"])
        if not card:
            raise PipelineError("feed_storage_failed", status=503)
        return {"card": card, "recipe": await self.recipes.public(recipe_id)}


async def redirect_legacy_repeat(callback, task) -> bool:
    """Never let a synthetic Feed task enter legacy billing/provider paths."""
    if str(getattr(task, "model", "") or "") != "genjutsu":
        return False
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    from bot.config import config
    from bot.database import get_profile_generation_card

    from .runtime import studio_url

    card = await get_profile_generation_card(task.id)
    recipe_id = card.get("genjutsu_recipe_id") if card else None
    if not recipe_id:
        await callback.answer("Этот повтор недоступен. Откройте свою работу в Genjutsu.", show_alert=True)
        return True
    await callback.answer()
    await callback.message.answer(
        "Откройте Genjutsu, чтобы подставить свои референсы и проверить стоимость.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="Повторить в Genjutsu",
            web_app=WebAppInfo(url=studio_url(config.mini_app_url, recipe_id=recipe_id)),
        )]]),
    )
    return True
