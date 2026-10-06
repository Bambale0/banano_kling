"""Private, versioned Genjutsu recipes used by curated Trends.

Recipes keep executable prompts, fixed media and provider settings server-side.
Public callers receive only the input contract. Instantiated recipe projects are
archived and bound to the recipe so normal project endpoints cannot expose the
hidden plan.
"""
from __future__ import annotations

import copy
import json
from typing import Any
from uuid import uuid4

import aiosqlite

from bot.trend_user_fields import (
    TrendUserFieldsError,
    clean_submitted_user_values,
    normalize_user_fields_settings,
    render_trend_prompt,
)

from .contract import PipelineError, asset_ids, compile_plan, quote_plan, text
from .repository import encode, many, one

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS genjutsu_recipes (
        id TEXT PRIMARY KEY,
        owner BIGINT NOT NULL,
        project_id TEXT NOT NULL,
        revision INTEGER NOT NULL,
        verification_run_id TEXT NOT NULL,
        title TEXT NOT NULL,
        plan TEXT NOT NULL,
        user_fields TEXT NOT NULL,
        source_binding TEXT NOT NULL DEFAULT 'fixed',
        active INTEGER NOT NULL DEFAULT 1,
        created_ms BIGINT NOT NULL,
        updated_ms BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS genjutsu_recipe_projects (
        project_id TEXT PRIMARY KEY REFERENCES genjutsu_projects(id),
        recipe_id TEXT NOT NULL REFERENCES genjutsu_recipes(id)
    )""",
    """CREATE TABLE IF NOT EXISTS genjutsu_feed_publications (
        step_id TEXT PRIMARY KEY REFERENCES genjutsu_steps(id),
        run_id TEXT NOT NULL REFERENCES genjutsu_runs(id),
        recipe_id TEXT NOT NULL UNIQUE REFERENCES genjutsu_recipes(id),
        task_id TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        source_binding TEXT NOT NULL,
        created_ms BIGINT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS genjutsu_recipes_owner ON genjutsu_recipes(owner,updated_ms)",
]


def _slots(plan: dict) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for step_index, step in enumerate(plan.get("steps") or []):
        for reference_index, ref in enumerate(step.get("references") or []):
            if ref.get("binding", "user") != "user":
                continue
            label = str(ref.get("label") or "").strip()
            slots.append({
                "step_index": step_index,
                "reference_index": reference_index,
                "role": str(ref.get("role") or "character"),
                "label": label or f"Фото {len(slots) + 1}",
            })
    return slots


def _fixed_assets(plan: dict, *, source_binding: str = "fixed") -> set[str]:
    result = set()
    if source_binding == "fixed":
        result.add(str(plan.get("source_asset_id") or ""))
    for step in plan.get("steps") or []:
        for ref in step.get("references") or []:
            if ref.get("binding", "user") == "fixed":
                result.add(str(ref.get("asset_id") or ""))
    result.discard("")
    return result


class RecipeStore:
    def __init__(self, repository):
        self.repository = repository

    async def migrate(self) -> None:
        async with self.repository.connect() as db:
            execute_ddl = getattr(db, "execute_native_ddl", db.execute)
            for sql in SCHEMA:
                await execute_ddl(sql)
            # Commit the base schema before the additive compatibility migration.
            # PostgreSQL rolls back the current transaction on duplicate-column
            # errors, so a later idempotent ALTER must not undo a fresh CREATE.
            await db.commit()
            try:
                await execute_ddl(
                    "ALTER TABLE genjutsu_recipes "
                    "ADD COLUMN source_binding TEXT NOT NULL DEFAULT 'fixed'"
                )
            except aiosqlite.OperationalError as exc:
                message = str(exc).lower()
                if "already exists" not in message and "duplicate column" not in message:
                    raise
            await db.commit()

    async def _row(self, recipe_id: str, *, active_only: bool = True) -> dict:
        if not isinstance(recipe_id, str) or len(recipe_id) != 32:
            raise PipelineError("recipe_unavailable", status=404)
        async with self.repository.connect() as db:
            row = await one(
                db,
                "SELECT * FROM genjutsu_recipes WHERE id=?" + (" AND active=1" if active_only else ""),
                (recipe_id,),
            )
        if not row:
            raise PipelineError("recipe_unavailable", status=404)
        if active_only:
            await self.require_publication(recipe_id)
        row["plan"] = json.loads(row["plan"])
        row["user_fields"] = json.loads(row["user_fields"])
        return row

    async def require_publication(self, recipe_id: str) -> None:
        """Feed withdrawal revokes new repeats without exposing the saved plan."""
        async with self.repository.connect() as db:
            binding = await one(db, "SELECT task_id FROM genjutsu_feed_publications WHERE recipe_id=?", (recipe_id,))
            if not binding:
                return  # Curated Trends recipes retain their existing lifecycle.
            task = await one(db, """SELECT id FROM generation_tasks WHERE task_id=?
                AND model='genjutsu' AND status='completed'
                AND (is_public_feed=1 OR COALESCE(is_profile_visible,0)=1)""", (binding["task_id"],))
        if not task:
            raise PipelineError("recipe_unavailable", status=404)

    async def preview(self, recipe_id: str, viewer: int) -> dict | None:
        """Resolve a published recipe to its ordinary, privacy-filtered card."""
        if not isinstance(recipe_id, str) or len(recipe_id) != 32:
            raise PipelineError("recipe_unavailable", status=404)
        async with self.repository.connect() as db:
            publication = await one(db, """SELECT fp.recipe_id AS publication_recipe_id,fp.task_id,u.id AS viewer_user_id
                FROM genjutsu_recipes r
                LEFT JOIN genjutsu_feed_publications fp ON fp.recipe_id=r.id
                LEFT JOIN users u ON u.telegram_id=?
                WHERE r.id=? AND r.active=1""", (viewer, recipe_id))
        if not publication:
            raise PipelineError("recipe_unavailable", status=404)
        if publication["publication_recipe_id"] is None:
            return None  # Curated recipes without a Feed publication keep their editor flow.

        from bot.database import get_profile_generation_card

        card = await get_profile_generation_card(
            publication["task_id"], viewer_user_id=publication["viewer_user_id"]
        )
        if not card or card.get("model") != "genjutsu" or card.get("genjutsu_recipe_id") != recipe_id:
            raise PipelineError("recipe_unavailable", status=404)
        # Fail closed if the recipe or publication was revoked during resolution.
        async with self.repository.connect() as db:
            active = await one(db, """SELECT r.id FROM genjutsu_recipes r
                JOIN genjutsu_feed_publications fp ON fp.recipe_id=r.id
                JOIN generation_tasks gt ON gt.task_id=fp.task_id
                WHERE r.id=? AND r.active=1 AND fp.task_id=?
                AND gt.model='genjutsu' AND gt.status='completed'
                AND gt.result_url IS NOT NULL
                AND (gt.is_public_feed=1 OR COALESCE(gt.is_profile_visible,0)=1)""",
                (recipe_id, publication["task_id"]))
        if not active:
            raise PipelineError("recipe_unavailable", status=404)
        return card

    async def validate_start(self, db, quote: dict) -> None:
        """Serialize Feed withdrawal with admission; accepted runs keep running."""
        binding = await one(db, """SELECT fp.task_id,fp.recipe_id
            FROM genjutsu_recipe_projects rp
            JOIN genjutsu_feed_publications fp ON fp.recipe_id=rp.recipe_id
            WHERE rp.project_id=?""", (quote["project_id"],))
        if not binding:
            return  # Unrelated legacy/curated recipes retain their admission path.
        # UPDATE locks the publication on PostgreSQL too. Feed withdrawal uses
        # this same task row, so its commit cannot race the balance reservation.
        await db.execute("UPDATE generation_tasks SET updated_at=updated_at WHERE task_id=?", (binding["task_id"],))
        row = await one(db, """SELECT gt.status,gt.is_public_feed,gt.is_profile_visible,r.active
            FROM generation_tasks gt JOIN genjutsu_recipes r ON r.id=?
            WHERE gt.task_id=? AND gt.model='genjutsu'""", (binding["recipe_id"], binding["task_id"]))
        if not row or row["active"] != 1 or not (row["is_public_feed"] or row["is_profile_visible"]) or row["status"] != "completed":
            raise PipelineError("recipe_unavailable", status=404)

    async def publish(
        self,
        owner: int,
        project_id: str,
        revision: int,
        title: str,
        user_fields: Any,
        verification_run_id: str,
        *,
        source_binding: str = "fixed",
    ) -> dict:
        title = text(title, 120, "invalid_title").strip()
        if not title:
            raise PipelineError("invalid_title")
        if type(revision) is not int or revision < 1:
            raise PipelineError("invalid_revision")
        if source_binding not in {"fixed", "user"}:
            raise PipelineError("invalid_source_binding")
        project = await self.repository.get_project(owner, project_id, revision)
        settings, _ = await self.repository.settings()
        owned = await self.repository.get_assets(owner, asset_ids(project["plan"]))
        # Validate the exact immutable recipe now. Restyle preset existence is
        # checked again against the live catalog at quote/submit time.
        plan = compile_plan(project["plan"], owned, settings, presets=None)
        if not isinstance(verification_run_id, str) or not await self.repository.verified_admin_run(
            owner, verification_run_id, project_id, revision, plan
        ):
            raise PipelineError("recipe_live_verification_required", status=409)
        try:
            normalized_fields = normalize_user_fields_settings(
                {"user_fields": user_fields or []},
                prompt="\n".join(str(step.get("prompt") or "") for step in plan["steps"]),
            ).get("user_fields", [])
        except TrendUserFieldsError as exc:
            raise PipelineError("invalid_recipe_fields") from exc
        rid, now = uuid4().hex, self.repository.clock()
        async with self.repository.transaction() as db:
            await db.execute(
                """INSERT INTO genjutsu_recipes(
                    id,owner,project_id,revision,verification_run_id,title,plan,user_fields,
                    source_binding,active,created_ms,updated_ms
                ) VALUES(?,?,?,?,?,?,?,?,?,1,?,?)""",
                (rid, owner, project_id, revision, verification_run_id, title,
                 encode(plan), encode(normalized_fields), source_binding, now, now),
            )
        return await self.public(rid)

    async def archive(self, owner: int, recipe_id: str) -> None:
        async with self.repository.transaction() as db:
            cursor = await db.execute(
                "UPDATE genjutsu_recipes SET active=0,updated_ms=? WHERE id=? AND owner=?",
                (self.repository.clock(), recipe_id, owner),
            )
            if cursor.rowcount != 1:
                raise PipelineError("recipe_unavailable", status=404)

    async def list_admin(self, owner: int) -> list[dict]:
        async with self.repository.connect() as db:
            rows = await many(
                db,
                "SELECT id FROM genjutsu_recipes WHERE owner=? AND active=1 ORDER BY updated_ms DESC LIMIT 100",
                (owner,),
            )
        items = []
        for row in rows:
            try:
                items.append(await self.public(row["id"]))
            except PipelineError as exc:
                # A withdrawn Feed recipe or a concurrent archive must not
                # hide unrelated healthy curated recipes from the selector.
                if exc.code != "recipe_unavailable":
                    raise
        return items

    async def public(self, recipe_id: str) -> dict:
        row = await self._row(recipe_id)
        plan = row["plan"]
        source_binding = row.get("source_binding") or "fixed"
        current_cost = None
        if source_binding == "fixed":
            source = await self.repository.get_asset_internal(plan["source_asset_id"])
            if source:
                try:
                    settings, _ = await self.repository.settings()
                    current_cost = quote_plan(
                        plan, {plan["source_asset_id"]: source}, settings
                    )["total_credits"]
                except PipelineError:
                    current_cost = None
        return {
            "id": row["id"],
            "title": row["title"],
            "source_slot": (
                {"kind": "video", "label": "Видео с нужным движением"}
                if source_binding == "user"
                else None
            ),
            "slots": _slots(plan),
            "user_fields": row["user_fields"],
            "steps": [
                {"operation": step["operation"], "resolution": step["resolution"]}
                for step in plan["steps"]
            ],
            "variants": plan["variants"],
            "continuation": plan["continuation"],
            "current_cost": current_cost,
        }

    async def instantiate(
        self,
        owner: int,
        recipe_id: str,
        reference_asset_ids: Any,
        user_values: Any,
        *,
        source_asset_id: Any = None,
    ) -> dict:
        row = await self._row(recipe_id)
        plan = copy.deepcopy(row["plan"])
        source_binding = row.get("source_binding") or "fixed"
        if source_binding == "user":
            if not isinstance(source_asset_id, str) or not source_asset_id or len(source_asset_id) > 100:
                raise PipelineError("source_required")
            try:
                source_assets = await self.repository.get_assets(owner, {source_asset_id})
            except PipelineError as exc:
                if exc.code == "asset_unavailable":
                    raise PipelineError("source_unavailable", status=404) from exc
                raise
            if source_assets[source_asset_id]["kind"] != "video":
                raise PipelineError("source_unavailable", status=404)
            plan["source_asset_id"] = source_asset_id
        elif source_asset_id not in (None, ""):
            raise PipelineError("source_not_replaceable")

        slots = _slots(plan)
        if not isinstance(reference_asset_ids, list) or len(reference_asset_ids) != len(slots):
            raise PipelineError("recipe_reference_count")
        clean_ids: list[str] = []
        for value in reference_asset_ids:
            if not isinstance(value, str) or not value or len(value) > 100:
                raise PipelineError("invalid_asset_id")
            clean_ids.append(value)
        if clean_ids:
            owned = await self.repository.get_assets(owner, set(clean_ids))
            if any(owned[aid]["kind"] != "image" for aid in set(clean_ids)):
                raise PipelineError("reference_unavailable", status=404)
        try:
            values = clean_submitted_user_values(user_values)
            field_settings = {"user_fields": row["user_fields"]}
            for step in plan["steps"]:
                step["prompt"] = render_trend_prompt(step.get("prompt", ""), field_settings, values)
        except TrendUserFieldsError as exc:
            raise PipelineError("invalid_recipe_fields") from exc

        for slot, aid in zip(slots, clean_ids):
            ref = plan["steps"][slot["step_index"]]["references"][slot["reference_index"]]
            ref["asset_id"] = aid
            ref["binding"] = "user"

        project_id, now = uuid4().hex, self.repository.clock()
        serialized = encode(plan)
        async with self.repository.transaction() as db:
            await db.execute(
                """INSERT INTO genjutsu_projects(
                    id,owner,title,revision,plan,archived,created_ms,updated_ms
                ) VALUES(?,?,?,?,?,1,?,?)""",
                (project_id, owner, row["title"], 1, serialized, now, now),
            )
            await db.execute(
                "INSERT INTO genjutsu_versions(project_id,revision,plan,title,created_ms) VALUES(?,?,?,?,?)",
                (project_id, 1, serialized, row["title"], now),
            )
            await db.execute(
                "INSERT INTO genjutsu_recipe_projects(project_id,recipe_id) VALUES(?,?)",
                (project_id, recipe_id),
            )
        return {"id": project_id, "revision": 1, "title": row["title"]}

    async def is_private_project(self, project_id: str) -> bool:
        async with self.repository.connect() as db:
            row = await one(db, "SELECT project_id FROM genjutsu_recipe_projects WHERE project_id=?", (project_id,))
        return row is not None

    async def resolve_project(self, owner: int, project_id: str, revision: int, draft: dict):
        async with self.repository.connect() as db:
            row = await one(
                db,
                """SELECT rp.recipe_id,r.plan,r.source_binding,r.active,p.owner
                   FROM genjutsu_recipe_projects rp
                   JOIN genjutsu_projects p ON p.id=rp.project_id
                   LEFT JOIN genjutsu_recipes r ON r.id=rp.recipe_id
                   WHERE rp.project_id=? AND p.owner=?""",
                (project_id, owner),
            )
        if not row:
            return draft, set(), False
        # A recipe binding remains private even when its recipe is archived
        # or missing; never reinterpret its saved plan as an ordinary project.
        if row["active"] != 1:
            raise PipelineError("recipe_unavailable", status=404)
        await self.require_publication(row["recipe_id"])
        template = json.loads(row["plan"])
        source_binding = row.get("source_binding") or "fixed"
        if (
            source_binding == "fixed"
            and draft.get("source_asset_id") != template.get("source_asset_id")
        ):
            raise PipelineError("recipe_integrity_failed", status=409)
        if source_binding == "user" and not draft.get("source_asset_id"):
            raise PipelineError("recipe_integrity_failed", status=409)
        if len(draft.get("steps") or []) != len(template.get("steps") or []):
            raise PipelineError("recipe_integrity_failed", status=409)
        for step_index, (current, original) in enumerate(zip(draft["steps"], template["steps"])):
            if (
                current.get("operation") != original.get("operation")
                or current.get("resolution") != original.get("resolution")
                or len(current.get("references") or []) != len(original.get("references") or [])
            ):
                raise PipelineError("recipe_integrity_failed", status=409)
            for current_ref, original_ref in zip(current["references"], original["references"]):
                if (
                    original_ref.get("binding", "user") == "fixed"
                    and current_ref.get("asset_id") != original_ref.get("asset_id")
                ):
                    raise PipelineError("recipe_integrity_failed", status=409)
        return draft, _fixed_assets(template, source_binding=source_binding), True

    async def dispatch(self, owner: int, admin: bool, action: str, body: dict, api) -> dict:
        if action == "recipe_preview":
            api.fields(body, {"recipe_id"})
            card = await self.preview(api.ident(body, "recipe_id"), owner)
            if card:
                if admin:
                    card["can_remove"] = True
                if admin or bool(card.get("is_mine")):
                    card["can_blur"] = True
            return {"card": card}
        if action == "recipe_get":
            api.fields(body, {"recipe_id"})
            return {"recipe": await self.public(api.ident(body, "recipe_id"))}
        if action == "recipe_costs":
            api.fields(body, {"recipe_ids"})
            raw_ids = body.get("recipe_ids")
            if not isinstance(raw_ids, list) or len(raw_ids) > 100:
                raise PipelineError("invalid_recipe_ids")
            costs: dict[str, int | None] = {}
            for raw_id in raw_ids:
                if not isinstance(raw_id, str) or raw_id in costs:
                    continue
                try:
                    recipe = await self.public(raw_id)
                except PipelineError as exc:
                    if exc.code == "recipe_unavailable":
                        continue
                    raise
                costs[raw_id] = recipe["current_cost"]
            return {"costs": costs}
        if action == "recipe_list":
            api.fields(body, set())
            if not admin:
                raise PipelineError("admin_required", status=403)
            return {"items": await self.list_admin(owner)}
        if action == "recipe_publish":
            api.fields(
                body,
                {
                    "project_id",
                    "revision",
                    "title",
                    "user_fields",
                    "verification_run_id",
                    "source_binding",
                },
            )
            if not admin:
                raise PipelineError("admin_required", status=403)
            await api.require_creation(True)
            return {
                "recipe": await self.publish(
                    owner,
                    api.ident(body, "project_id"),
                    body.get("revision"),
                    body.get("title"),
                    body.get("user_fields"),
                    api.ident(body, "verification_run_id"),
                    source_binding=body.get("source_binding", "fixed"),
                )
            }
        if action == "recipe_archive":
            api.fields(body, {"recipe_id"})
            if not admin:
                raise PipelineError("admin_required", status=403)
            await self.archive(owner, api.ident(body, "recipe_id"))
            return {"archived": True}
        if action == "recipe_quote":
            api.fields(
                body,
                {"recipe_id", "source_asset_id", "reference_asset_ids", "user_values"},
            )
            await api.require_creation(admin)
            recipe_id = api.ident(body, "recipe_id")
            project = await self.instantiate(
                owner,
                recipe_id,
                body.get("reference_asset_ids"),
                body.get("user_values"),
                source_asset_id=body.get("source_asset_id"),
            )
            quote = await api.pipeline.quote(owner, project["id"], project["revision"])
            return {
                "quote": quote,
                "admin_free": admin,
                "recipe": await self.public(recipe_id),
            }
        raise PipelineError("invalid_action")
