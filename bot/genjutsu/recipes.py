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
        active INTEGER NOT NULL DEFAULT 1,
        created_ms BIGINT NOT NULL,
        updated_ms BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS genjutsu_recipe_projects (
        project_id TEXT PRIMARY KEY REFERENCES genjutsu_projects(id),
        recipe_id TEXT NOT NULL REFERENCES genjutsu_recipes(id)
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


def _fixed_assets(plan: dict) -> set[str]:
    result = {str(plan.get("source_asset_id") or "")}
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
        row["plan"] = json.loads(row["plan"])
        row["user_fields"] = json.loads(row["user_fields"])
        return row

    async def publish(
        self,
        owner: int,
        project_id: str,
        revision: int,
        title: str,
        user_fields: Any,
        verification_run_id: str,
    ) -> dict:
        title = text(title, 120, "invalid_title").strip()
        if not title:
            raise PipelineError("invalid_title")
        if type(revision) is not int or revision < 1:
            raise PipelineError("invalid_revision")
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
                    id,owner,project_id,revision,verification_run_id,title,plan,user_fields,active,created_ms,updated_ms
                ) VALUES(?,?,?,?,?,?,?,?,1,?,?)""",
                (rid, owner, project_id, revision, verification_run_id, title,
                 encode(plan), encode(normalized_fields), now, now),
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
        return [await self.public(row["id"]) for row in rows]

    async def public(self, recipe_id: str) -> dict:
        row = await self._row(recipe_id)
        plan = row["plan"]
        source = await self.repository.get_asset_internal(plan["source_asset_id"])
        current_cost = None
        if source:
            try:
                settings, _ = await self.repository.settings()
                current_cost = quote_plan(plan, {plan["source_asset_id"]: source}, settings)["total_credits"]
            except PipelineError:
                current_cost = None
        return {
            "id": row["id"],
            "title": row["title"],
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
    ) -> dict:
        row = await self._row(recipe_id)
        plan = copy.deepcopy(row["plan"])
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
                """SELECT rp.recipe_id,r.plan,p.owner
                   FROM genjutsu_recipe_projects rp
                   JOIN genjutsu_recipes r ON r.id=rp.recipe_id
                   JOIN genjutsu_projects p ON p.id=rp.project_id
                   WHERE rp.project_id=? AND p.owner=? AND r.active=1""",
                (project_id, owner),
            )
        if not row:
            return draft, set(), False
        template = json.loads(row["plan"])
        if draft.get("source_asset_id") != template.get("source_asset_id"):
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
        return draft, _fixed_assets(template), True

    async def dispatch(self, owner: int, admin: bool, action: str, body: dict, api) -> dict:
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
            api.fields(body, {"project_id", "revision", "title", "user_fields", "verification_run_id"})
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
                )
            }
        if action == "recipe_archive":
            api.fields(body, {"recipe_id"})
            if not admin:
                raise PipelineError("admin_required", status=403)
            await self.archive(owner, api.ident(body, "recipe_id"))
            return {"archived": True}
        if action == "recipe_quote":
            api.fields(body, {"recipe_id", "reference_asset_ids", "user_values"})
            await api.require_creation(admin)
            recipe_id = api.ident(body, "recipe_id")
            project = await self.instantiate(
                owner,
                recipe_id,
                body.get("reference_asset_ids"),
                body.get("user_values"),
            )
            quote = await api.pipeline.quote(owner, project["id"], project["revision"])
            return {
                "quote": quote,
                "admin_free": admin,
                "recipe": await self.public(recipe_id),
            }
        raise PipelineError("invalid_action")
