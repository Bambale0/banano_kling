"""Complete Wan recipes with per-slot, server-checked publication consent.

Public plans contain settings and slot roles, never the author's hidden prompt or
reference URLs. Only the compiler may combine consented originals with uploads.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from bot.services.wan3_prime_media import (
    WAN3_MODEL_KEY,
    Wan3PrimeValidationError,
    normalize_wan3_body,
)

OUTPUT_FIELDS = ("resolution", "aspect_ratio", "duration", "audio", "nsfw_checker", "seed")
ARRAY_FIELDS = {
    "reference_image_urls": "image", "reference_video_urls": "video",
    "reference_audio_urls": "audio", "reference_file_urls": "file", "reference_link_urls": "link",
}
FRAME_FIELDS = ("first_frame_url", "last_frame_url")
RECIPE_FIELDS = ("model", "scenario", "prompt", *OUTPUT_FIELDS, *FRAME_FIELDS, *ARRAY_FIELDS)
PUBLIC_REQUEST_FIELDS = (*RECIPE_FIELDS, "source_feed_gen_id", "trend_id", "repeat_plan_hash", "repeat_replacements")


def client_recipe(body: dict[str, Any]) -> dict[str, Any]:
    data = normalize_wan3_body(body)
    # Authentication and server-internal fields must never enter snapshots.
    return {key: deepcopy(data[key]) for key in PUBLIC_REQUEST_FIELDS if key in data}


def _json_object(value) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def source_recipe(source: dict[str, Any]) -> dict[str, Any]:
    if source.get("model") != WAN3_MODEL_KEY:
        raise Wan3PrimeValidationError("Откройте повтор с моделью исходной публикации", status=409)
    data = normalize_wan3_body(_json_object(source.get("request_data")))
    if not data.get("scenario"):
        raise Wan3PrimeValidationError("Рецепт Wan сохранён не полностью", status=409)
    result = {key: deepcopy(data[key]) for key in RECIPE_FIELDS if key in data}
    result["model"] = WAN3_MODEL_KEY
    result.setdefault("prompt", str(source.get("prompt") or ""))
    for name in ARRAY_FIELDS:
        values = result.setdefault(name, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
            raise Wan3PrimeValidationError("Исходные референсы повреждены", status=409)
    return result


def source_slots(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    slots = []
    for field in FRAME_FIELDS:
        if recipe.get(field):
            slots.append({"key": field, "kind": "image", "role": field.removesuffix("_url"), "field": field,
                          "index": 0, "url": recipe[field]})
    for field, kind in ARRAY_FIELDS.items():
        for index, value in enumerate(recipe.get(field) or []):
            role = "source_video" if recipe["scenario"] == "edit" and kind == "video" and index == 0 else "reference"
            slots.append({"key": f"{kind}:{index}", "kind": kind, "role": role, "field": field, "index": index, "url": value})
    return slots


def build_repeat_plan(source: dict[str, Any]) -> dict[str, Any]:
    from bot.services.media_input_utils import resolve_reference_source
    from bot.video_repeat_reference_contract import parse_video_repeat_grant

    if source.get("source_feed_gen_id") or str(source.get("action_type") or "") in {"repeat", "remix", "trend"}:
        raise Wan3PrimeValidationError("Чужой приватный рецепт нельзя передать повторно", status=403)
    recipe = source_recipe(source)
    try:
        grant = parse_video_repeat_grant(source.get("feed_repeat_reference_selection"))
    except ValueError as exc:
        raise Wan3PrimeValidationError("Разрешение на повтор повреждено", status=409) from exc
    grant = grant or {"version": 1, "images": [], "videos": []}
    slots = source_slots(recipe)
    fixed = set()
    for kind, plural in (("image", "images"), ("video", "videos")):
        candidates = [slot["url"] for slot in slots if slot["kind"] == kind]
        for value in grant[plural]:
            try:
                resolved = resolve_reference_source(value, candidates)
            except ValueError as exc:
                raise Wan3PrimeValidationError("Разрешение содержит неоднозначный референс", status=409) from exc
            if resolved is None:
                raise Wan3PrimeValidationError("Разрешённый референс отсутствует в рецепте", status=409)
            fixed.add(resolved)
    for slot in slots:
        slot["binding"] = "fixed" if slot["kind"] in {"image", "video"} and slot["url"] in fixed else "upload"
    revision = {
        "id": source.get("id"), "user_id": source.get("user_id"), "recipe": recipe, "grant": grant,
        "status": source.get("status"), "is_public_feed": bool(source.get("is_public_feed")),
        "is_profile_visible": bool(source.get("is_profile_visible")),
    }
    digest = hashlib.sha256(json.dumps(revision, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"source_id": int(source.get("id") or 0), "owner_id": int(source.get("user_id") or 0),
            "owner_telegram_id": int(source.get("telegram_id") or 0), "recipe": recipe, "slots": slots, "hash": digest}


def public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    recipe = plan["recipe"]
    return {"ok": True, **({"trend_id": plan["trend_id"]} if plan.get("trend_id") else {"source_feed_gen_id": plan["source_id"]}), "repeat_plan_hash": plan["hash"],
            "recipe": {"model": WAN3_MODEL_KEY, "scenario": recipe["scenario"], "prompt": "",
                       **{key: recipe[key] for key in OUTPUT_FIELDS if key in recipe}},
            "slots": [{key: slot[key] for key in ("key", "kind", "role", "index", "binding")} for slot in plan["slots"]]}


async def get_repeat_plan(actor, source_id: int) -> dict[str, Any]:
    from bot import database

    if isinstance(source_id, bool) or not isinstance(source_id, int) or source_id <= 0:
        raise Wan3PrimeValidationError("Некорректная публикация", status=400)
    card = await database.get_profile_generation_card(source_id, viewer_user_id=actor.user_id, include_unavailable=True)
    source = await database.get_generation_task_payload(source_id) if card else None
    if not source or source.get("status") != "completed" or source.get("type") != "video":
        raise Wan3PrimeValidationError("Публикация больше недоступна", status=404)
    return build_repeat_plan(source)


class ConsentedMediaProbe:
    """A capability for exact consented URLs, never blanket cross-user access."""
    def __init__(self, probe, actor, plan):
        self.viewer = probe.for_actor(actor) if hasattr(probe, "for_actor") else probe
        owner = SimpleNamespace(user_id=plan["owner_id"], telegram_id=plan["owner_telegram_id"])
        self.owner = probe.for_actor(owner) if hasattr(probe, "for_actor") else probe
        self.allowed = {(slot["kind"], slot["url"]) for slot in plan["slots"] if slot["binding"] == "fixed"}

    async def probe_url(self, url: str, *, kind: str):
        probe = self.owner if (kind, url) in self.allowed else self.viewer
        return await probe.probe_url(url, kind=kind)

    async def probe_file(self, path: str, *, kind: str):
        return await self.viewer.probe_file(path, kind=kind)


async def compile_repeat(actor, body: dict[str, Any], probe):
    public_input = client_recipe(body)
    source_id = public_input.get("source_feed_gen_id")
    trend_id = public_input.get("trend_id")
    if source_id and trend_id:
        raise Wan3PrimeValidationError("Choose a publication or a curated trend, not both")
    if trend_id:
        from bot.services.wan3_prime_trends import get_trend_plan
        plan = await get_trend_plan(actor, trend_id)
    else:
        plan = await get_repeat_plan(actor, source_id)
    if public_input.get("repeat_plan_hash") != plan["hash"]:
        raise Wan3PrimeValidationError("Разрешение изменилось. Откройте повтор заново", status=409)
    replacements = public_input.get("repeat_replacements", {})
    expected = {slot["key"] for slot in plan["slots"] if slot["binding"] == "upload"}
    if not isinstance(replacements, dict) or set(replacements) != expected:
        raise Wan3PrimeValidationError("Загрузите свои файлы для каждого заменяемого места", status=409)
    if any(not isinstance(value, str) or not value.strip() for value in replacements.values()):
        raise Wan3PrimeValidationError("Пустой заменяемый референс", status=400)
    if any(public_input.get(key) for key in (*FRAME_FIELDS, *ARRAY_FIELDS)):
        raise Wan3PrimeValidationError("При повторе используйте пронумерованные места для референсов", status=409)
    if public_input.get("scenario", plan["recipe"]["scenario"]) != plan["recipe"]["scenario"]:
        raise Wan3PrimeValidationError("Режим должен соответствовать исходной публикации", status=409)
    compiled = deepcopy(plan["recipe"])
    for slot in plan["slots"]:
        if slot["binding"] != "upload":
            continue
        value = replacements[slot["key"]].strip()
        # Even a known original URL cannot be smuggled in as a user's upload.
        if actor.user_id != plan["owner_id"] and any(value == item["url"] for item in plan["slots"]):
            raise Wan3PrimeValidationError("Загрузите собственный файл для заменяемого места", status=403)
        if slot["field"] in FRAME_FIELDS:
            compiled[slot["field"]] = value
        else:
            compiled[slot["field"]][slot["index"]] = value
    for key in OUTPUT_FIELDS:
        if key in public_input:
            compiled[key] = public_input[key]
    edits = public_input.get("prompt", "")
    if not isinstance(edits, str):
        raise Wan3PrimeValidationError("Изменения должны быть текстом")
    original = str(compiled.get("prompt") or "")
    compiled["prompt"] = original if not edits.strip() else (original + "\n\nUser requested changes:\n" + edits.strip()).strip()
    context = {"source_id": plan["source_id"], "owner_id": plan["owner_id"], "source_hash": plan["hash"]}
    if plan.get("trend_id"):
        context["trend_id"] = plan["trend_id"]
    return compiled, ConsentedMediaProbe(probe, actor, plan), context, public_input


async def verify_repeat_in_transaction(db, context: dict[str, Any]) -> None:
    from bot import db as db_backend

    if not context:
        return
    if context.get("trend_id"):
        from bot.services.wan3_prime_trends import verify_trend_in_transaction
        await verify_trend_in_transaction(db, context)
        return
    row = await (await db.execute(
        "SELECT * FROM generation_tasks WHERE id = ?" + (" FOR SHARE" if db_backend.is_postgres() else ""),
        (context["source_id"],),
    )).fetchone()
    if (not row or row["status"] != "completed" or not (row["is_public_feed"] or row["is_profile_visible"])
            or build_repeat_plan(dict(row))["hash"] != context["source_hash"]):
        raise Wan3PrimeValidationError("Разрешение на повтор отозвано или изменилось", status=409)


def legacy_video_plan(source: dict[str, Any]) -> dict[str, Any]:
    """Bridge publication checkboxes to Wan's complete, ordered slot contract."""
    plan = build_repeat_plan(source)
    groups = {"images": [], "videos": []}
    for slot in plan["slots"]:
        if slot["kind"] not in {"image", "video"}:
            continue
        kind = "images" if slot["kind"] == "image" else "videos"
        groups[kind].append({"url": slot["url"], "index": len(groups[kind]), "kind": kind,
                             "role": slot["role"] if slot["role"] in {"first_frame", "last_frame"} else "reference",
                             "binding": slot["binding"]})
    return {"version": 1, "model": WAN3_MODEL_KEY, "scenario": plan["recipe"]["scenario"],
            "public_scenario": plan["recipe"]["scenario"], **groups,
            "audio": list(plan["recipe"].get("reference_audio_urls") or [])}
