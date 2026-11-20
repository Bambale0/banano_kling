"""Account-owned, paid Gemini Omni Audio ID / Character ID asset workflow.

The provider ids are never accepted as browser credentials. Clients use only
opaque oa_ IDs issued after a verified paid task settles. Transient provider
create failures are not blindly retried; the original web task worker manages
provider-id polling and refund/capture.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from decimal import Decimal

from aiohttp import web

from bot import db as db_backend
from bot.services.gemini_omni_service import gemini_omni_service
from bot.services.preset_manager import preset_manager
from bot.shared_accounts.wallet import amount_units
from bot.web_tasks import ensure_web_tasks_schema

_ASSET_ID = re.compile(r"^oa_[a-f0-9]{32}$")
_PROVIDER_ID = re.compile(r"^[A-Za-z0-9._:-]{2,256}$")
_KEY = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_OMNI_MODELS = {"gemini_omni_audio": "audio", "gemini_omni_character": "character"}


def _price(kind: str) -> str:
    if kind not in ("audio", "character"):
        raise ValueError("Unsupported Omni asset")
    price = Decimal(str(preset_manager.get_video_cost("gemini_omni_" + kind, 6)))
    if not price.is_finite() or price <= 0:
        raise ValueError("Omni asset admin price is missing")
    amount_units(price)
    return str(price)


def _read_asset_fields(body: dict) -> dict:
    kind = body.get("kind")
    if kind not in ("audio", "character"):
        raise ValueError("Omni kind must be audio or character")
    if kind == "audio":
        allowed = {
            "kind", "name", "base_voice", "voice_description",
            "example_dialogue", "request_key", "expected_price",
        }
        name = body.get("name")
        voice = body.get("base_voice", "achernar")
        description = body.get("voice_description", "")
        example = body.get("example_dialogue", "")
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 20
                or not isinstance(voice, str) or voice not in gemini_omni_service.BASE_VOICES
                or not isinstance(description, str) or len(description) > 2000
                or not isinstance(example, str) or len(example) > 2000):
            raise ValueError("Invalid Omni Audio ID fields")
        fields = {
            "kind": kind, "name": name.strip(), "base_voice": voice,
            "voice_description": description, "example_dialogue": example,
        }
    else:
        allowed = {
            "kind", "character_name", "description", "image_reference_id",
            "audio_asset_ids", "request_key", "expected_price",
        }
        name = body.get("character_name")
        description = body.get("description")
        reference = body.get("image_reference_id")
        audio_asset_ids = body.get("audio_asset_ids", [])
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 20
                or not isinstance(description, str) or not 1 <= len(description.strip()) <= 2000
                or not isinstance(reference, str)
                or not re.fullmatch(r"wr_[a-f0-9]{32}", reference)
                or not isinstance(audio_asset_ids, list) or len(audio_asset_ids) > 1
                or any(not isinstance(x, str) or not _ASSET_ID.fullmatch(x)
                       for x in audio_asset_ids)):
            raise ValueError("Invalid Omni Character ID fields")
        fields = {
            "kind": kind, "name": name.strip(),
            "description": description.strip(), "image_reference_id": reference,
            "audio_asset_ids": audio_asset_ids,
        }
    if set(body) - allowed:
        raise ValueError("Unexpected Omni asset fields")
    return fields


async def owned_asset_provider_ids(
    account_id: str, public_ids: list[str], *, kind: str,
) -> list[str]:
    if (kind not in ("audio", "character") or not isinstance(public_ids, list)
            or len(public_ids) > (1 if kind == "audio" else 3)
            or len(set(public_ids)) != len(public_ids)
            or any(not isinstance(x, str) or not _ASSET_ID.fullmatch(x)
                   for x in public_ids)):
        raise ValueError("Invalid Omni asset references")
    if not public_ids:
        return []
    await ensure_web_tasks_schema()
    placeholders = ",".join("?" for _ in public_ids)
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            "SELECT a.asset_id,a.provider_asset_id FROM web_omni_assets a "
            "JOIN web_generation_tasks t ON t.task_id=a.source_task_id "
            "WHERE t.status='completed' AND a.asset_id IN (" + placeholders + ") "
            "AND a.kind=? AND a.account_id IN (WITH RECURSIVE owned(id) AS "
            "(SELECT ? UNION ALL SELECT s.id FROM shared_accounts s "
            "JOIN owned o ON s.merged_into=o.id WHERE s.status='merged') "
            "SELECT id FROM owned)",
            (*public_ids, kind, account_id),
        )).fetchall()
    values = {row[0]: row[1] for row in rows}
    if len(values) != len(public_ids):
        raise PermissionError("Omni asset is not owned by the signed account")
    return [str(values[asset_id]) for asset_id in public_ids]


async def _prepare(account_id: str, raw: dict, *, must_have_key: bool) -> tuple[dict, str]:
    from bot.web_references import owned_reference_urls

    fields = _read_asset_fields(raw)
    expected_price = raw.get("expected_price")
    if expected_price is not None and (
        not isinstance(expected_price, str) or
        amount_units(expected_price) <= 0
    ):
        raise ValueError("Invalid expected Omni price")
    key = raw.get("request_key", "web-omni-asset-quote-check-2026")
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ValueError("Invalid Omni idempotency key")
    kind = fields["kind"]
    if kind == "character":
        fields["image_urls"] = await owned_reference_urls(
            account_id, [fields["image_reference_id"]], kind="image",
        )
        fields["provider_audio_ids"] = await owned_asset_provider_ids(
            account_id, fields["audio_asset_ids"], kind="audio",
        )
    normalized = {
        "model": "gemini_omni_" + kind,
        # DB uses video media_type for now; public type is "asset".
        "media_type": "video",
        "prompt": fields.get("description") or fields.get("name") or "",
        "aspect_ratio": "16:9", "duration": 6,
        "quality": "", "reference_ids": [],
        "video_reference_ids": [], "audio_reference_ids": [],
        "request_key": key, "expected_price": expected_price,
        "max_images": 30, "text_recognition": False,
        "output_format": "png", "background": "auto",
        "nsfw_checker": False, "wan_scenario": "",
        "omni_audio_asset_ids": [], "omni_character_asset_ids": [],
        "omni_seed": None, "file_reference_ids": [], "link_reference_ids": [],
        "asset_payload": fields,
    }
    return normalized, _price(kind)


async def prepare_omni_video(account_id: str, normalized: dict) -> None:
    """Resolve only verified, completed owner assets and measured video."""
    from bot import web_references

    if normalized["model"] != "gemini_omni":
        return
    audio_refs = normalized["omni_audio_asset_ids"]
    character_refs = normalized["omni_character_asset_ids"]
    normalized["omni_audio_provider_ids"] = await owned_asset_provider_ids(
        account_id, audio_refs, kind="audio",
    )
    normalized["omni_character_provider_ids"] = await owned_asset_provider_ids(
        account_id, character_refs, kind="character",
    )
    video_refs = normalized["video_reference_ids"]
    if video_refs:
        inspected = await web_references.owned_reference_media(
            account_id, video_refs, kind="video",
        )
        if len(inspected) != 1:
            raise PermissionError("Unowned Omni video input")
        source = inspected[0]
        seconds = source.duration_seconds
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 1 <= seconds <= 20:
            raise ValueError("Gemini Omni video input duration must be 1-20 seconds")
        if (source.extension or "").lower() not in {".mp4", ".mov"}:
            raise ValueError("Gemini Omni video input must be MP4")
        normalized["omni_video_ends"] = math.ceil(seconds)
    else:
        normalized["omni_video_ends"] = None


async def quote_asset(request: web.Request) -> web.Response:
    from bot.web_auth import _json, _session_account, _valid_browser_origin

    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "origin_rejected"}, 403)
    account = await _session_account(request)
    if not account:
        return _json({"ok": False, "error": "session_required"}, 401)
    if request.content_length and request.content_length > 12000:
        return _json({"ok": False, "error": "Request too large"}, 413)
    try:
        raw = await request.json()
        if not isinstance(raw, dict):
            raise TypeError("Invalid input")
        normalized, cost = await _prepare(account, raw, must_have_key=False)
    except PermissionError:
        return _json({"ok": False, "error": "Не принадлежащий аккаунту Audio/Character ID."}, 403)
    except (ValueError, TypeError, KeyError):
        return _json({"ok": False, "error": "Проверьте параметры Gemini Omni."}, 400)
    return _json({"ok": True, "kind": normalized["asset_payload"]["kind"], "price": cost})


async def create_asset(request: web.Request) -> web.Response:
    from bot import web_generation
    from bot.web_auth import _json, _session_account, _valid_browser_origin

    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "origin_rejected"}, 403)
    account = await _session_account(request)
    if not account:
        return _json({"ok": False, "error": "session_required"}, 401)
    if not web_generation._enabled() or not web_generation.config.KIE_AI_API_KEY:
        return _json({"ok": False, "error": "Web generation is unavailable"}, 503)
    if request.content_length and request.content_length > 12000:
        return _json({"ok": False, "error": "Request too large"}, 413)
    try:
        raw = await request.json()
        if not isinstance(raw, dict):
            raise TypeError("Invalid input")
        if "request_key" not in raw or "expected_price" not in raw:
            raise ValueError("Idempotency and price confirmation required")
        normalized, cost = await _prepare(account, raw, must_have_key=True)
        units = amount_units(cost)
    except PermissionError:
        return _json({"ok": False, "error": "Чужой файл или Audio ID."}, 403)
    except (ValueError, TypeError, KeyError):
        return _json({"ok": False, "error": "Неверные параметры Gemini Omni."}, 400)
    if amount_units(normalized["expected_price"]) != units:
        return _json({
            "ok": False, "code": "price_changed",
            "error": "Стоимость изменилась. Обновите расчёт.",
            "current_price": cost,
        }, 409)
    return await web_generation.reserve_web_task(account, normalized, cost, units)


async def list_assets(request: web.Request) -> web.Response:
    from bot.web_auth import _json, _session_account

    account = await _session_account(request)
    if not account:
        return _json({"ok": False, "error": "session_required"}, 401)
    await ensure_web_tasks_schema()
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            """SELECT a.asset_id,a.kind,a.name,a.created_at_epoch
               FROM web_omni_assets a
               JOIN web_generation_tasks t ON t.task_id=a.source_task_id
               WHERE t.status='completed' AND a.account_id IN (
                 WITH RECURSIVE owned(id) AS (SELECT ? UNION ALL
                   SELECT s.id FROM shared_accounts s JOIN owned o
                   ON s.merged_into=o.id WHERE s.status='merged')
                 SELECT id FROM owned)
               ORDER BY a.created_at_epoch DESC,a.asset_id DESC LIMIT 100""",
            (account,),
        )).fetchall()
    return _json({"ok": True, "base_voices": sorted(gemini_omni_service.BASE_VOICES),
                  "assets": [
        {"asset_id": row[0], "kind": row[1], "name": row[2],
         "created_at_epoch": int(row[3])}
        for row in rows
    ]})


async def submit_omni_asset(task_id: str, payload: dict) -> tuple[str | None, str | None, bool]:
    """(provider task, provider asset, explicit non-billable rejection)."""
    kind = _OMNI_MODELS.get(payload.get("model"))
    if not kind:
        raise ValueError("Unexpected Omni asset model")
    options = payload.get("asset_payload") or {}
    try:
        if kind == "audio":
            response = await gemini_omni_service.create_audio(
                audio_id=options["base_voice"],
                name=options["name"],
                voice_description=options["voice_description"],
                example_dialogue=options["example_dialogue"],
                retry_transient=False,
            )
        else:
            response = await gemini_omni_service.create_character(
                description=options["description"],
                image_urls=options["image_urls"],
                character_name=options["name"],
                audio_ids=options["provider_audio_ids"] or None,
                retry_transient=False,
            )
        if not isinstance(response, dict):
            return None, None, False
        if response.get("status") == "done" and response.get("asset_id"):
            return None, str(response["asset_id"]), False
        if response.get("status") == "pending" and response.get("task_id"):
            return str(response["task_id"]), None, False
        return None, None, response.get("error") in {
            "name_required", "description_required", "image_required",
            "invalid_input", "too_many_audio_ids",
        }
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "web_omni_asset_submission_uncertain task=%s", task_id,
        )
        return None, None, False


async def poll_omni_asset(provider_task_id: str, kind: str) -> tuple[str, str | None]:
    from bot.services.kie_market_service import kie_market_service

    data = await kie_market_service.get_task_status(provider_task_id)
    if not isinstance(data, dict):
        return "pending", None
    returned_id = str(data.get("taskId") or data.get("task_id") or "")
    if returned_id and returned_id != provider_task_id:
        return "pending", None
    state = str(data.get("state") or data.get("status") or "pending").lower()
    if state in ("success", "completed", "succeeded"):
        identity = gemini_omni_service._extract_asset_id({"data": data}, kind)
        if identity and _PROVIDER_ID.fullmatch(str(identity)):
            return "success", str(identity)
    return state, None


async def persist_omni_asset(row, provider_asset_id: str) -> None:
    from bot import web_generation

    task_id, account = str(row[0]), str(row[1])
    kind = _OMNI_MODELS.get(str(row[3]))
    if not kind or not isinstance(provider_asset_id, str) or not _PROVIDER_ID.fullmatch(provider_asset_id):
        raise ValueError("Provider did not confirm a valid Omni asset")
    payload = json.loads(row[7])["asset_payload"]
    name = str(payload["name"])
    public_id = "oa_" + hashlib.sha256(
        (task_id + ":" + kind + ":" + provider_asset_id).encode(),
    ).hexdigest()[:32]
    await ensure_web_tasks_schema()
    async with db_backend.connect() as db:
        if db_backend.is_postgres():
            await db.execute("BEGIN")
        else:
            await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                """INSERT INTO web_omni_assets
                   (asset_id,account_id,provider_asset_id,kind,source_task_id,
                    name,created_at_epoch)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT DO NOTHING""",
                (public_id, account, provider_asset_id, kind, task_id,
                 name, int(time.time())),
            )
            await db.execute(
                """UPDATE web_generation_tasks
                   SET asset_id=?,asset_kind=?,phase='settling',
                       lease_until_epoch=0,updated_at_epoch=?
                   WHERE task_id=? AND account_id=? AND status='pending'
                     AND phase IN ('submitting','provider','checking','settling')""",
                (public_id, kind, int(time.time()), task_id, account),
            )
            record = await (await db.execute(
                "SELECT asset_id FROM web_omni_assets WHERE asset_id=? "
                "AND source_task_id=? AND account_id=? AND kind=?",
                (public_id, task_id, account, kind),
            )).fetchone()
            if not record:
                raise ValueError("Provider asset already exists under a different task")
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    await web_generation._capture_completed(await web_generation._task_row(task_id))


def register_routes(app: web.Application, prefix: str) -> None:
    root = prefix + "/web-omni/assets"
    app.router.add_get(root, list_assets)
    app.router.add_post(root + "/quote", quote_asset)
    app.router.add_post(root + "/create", create_asset)
