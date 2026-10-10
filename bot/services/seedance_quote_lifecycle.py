"""Measured quote lifecycle shared by Seedance Telegram, Mini App and repeats."""
from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from types import SimpleNamespace

from bot import database
from bot import db as db_backend
from bot.creator_tariff import quote_video_for_actor
from bot.services.motion_launch_receipts import _has_acceptance_witness
from bot.services.seedance_launch_gate import PAUSE_MESSAGE, launches_allowed
from bot.services.seedance_quote_receipts import (
    QuoteConflict,
    SeedanceQuoteReceipts,
    canonical_json,
)
from bot.services.seedance_quote_snapshots import (
    authorize_video_sources,
    prepare_video_snapshots,
    verify_quote_snapshots,
)
from bot.services.wan3_prime_storage import Wan3PrimeStorage
from bot.services.wan3_prime_storage_policy import lock_storage

logger = logging.getLogger(__name__)


async def receipt_store():
    await Wan3PrimeStorage().init_schema()
    store = SeedanceQuoteReceipts(lambda: db_backend.connect(database.DATABASE_PATH), db_backend.Row,
                                 storage_lock=lock_storage, validate_media=verify_quote_snapshots, allow_new_claim=launches_allowed)
    await store.ensure_schema()
    return store


def public_quote(row: dict) -> dict:
    billing = json.loads(row["billing_json"])
    return {"ok": True, "quote_only": True, "quote_id": row["quote_id"],
            "quote_hash": row["quote_hash"], "cost": billing["cost"],
            "charge_cost": billing["charge_cost"], "input_seconds": billing["input_seconds"],
            "selected_output_seconds": billing["selected_output_seconds"],
            "expires_at": str(row["expires_at"])}


def effective_video_sources(original: dict, video_key: str, model: str) -> list[str]:
    from bot.services.media_input_utils import canonicalize_local_upload_url

    sources = [canonicalize_local_upload_url(str(value).strip()) for value in original[video_key] if str(value or "").strip()]
    # Explicit private/trend slots are deliberate occurrences. Ordinary URL
    # lists retain the existing adapter's canonical de-duplication semantics.
    ordered_slots = bool(original.get("reference_contract") or original.get("_private_repeat")
                         or original.get("video_repeat_contract_version"))
    if not ordered_slots:
        sources = list(dict.fromkeys(sources))
    limit = 3 if model == "seedance_2" else 10
    if not 1 <= len(sources) <= limit:
        raise QuoteConflict("Некорректное число видео-референсов")
    return sources


async def prepare_quote(telegram_id: int, model: str, original: dict, *, video_key: str,
                        duration: int, quality: str, source_locked: bool = False) -> dict:
    """Only call after effective recipe assembly and source/repeat authorization."""
    if duration <= 0 and not source_locked:
        raise QuoteConflict("Для точной цены выберите длительность результата")
    store = await receipt_store()
    if not launches_allowed():
        raise QuoteConflict(PAUSE_MESSAGE)
    user = await database.get_or_create_user(telegram_id)
    actor = SimpleNamespace(user_id=user.id, telegram_id=telegram_id)
    sources = effective_video_sources(original, video_key, model)
    authorized_sources = tuple(original.get("_authorized_video_sources") or ())
    await authorize_video_sources(actor, sources, authorized_sources=authorized_sources)
    snapshots = await prepare_video_snapshots(actor, sources)
    provider = deepcopy(original)
    provider[video_key] = [item["url"] for item in snapshots]
    provider["_snapshot_media_ids"] = [item["media_id"] for item in snapshots]
    source_seconds = sum(item["seconds"] for item in snapshots)
    output_seconds = source_seconds if source_locked else duration
    fingerprint = hashlib.sha256(canonical_json([
        {"sha256": item["sha256"], "seconds": item["seconds"]} for item in snapshots
    ]).encode()).hexdigest()
    billing = await quote_video_for_actor(
        telegram_id, model, duration=duration, quality=quality,
        input_video_seconds=source_seconds, selected_output_seconds=output_seconds,
        references_fingerprint=fingerprint,
    )
    return await store.create(user_id=user.id, telegram_id=telegram_id, original=original,
                              provider=provider, billing=billing.to_dict(),
                              media_ids=[item["media_id"] for item in snapshots])


async def claim_quote(telegram_id: int, quote_id: str, quote_hash: str, original: dict) -> dict:
    store = await receipt_store()
    row = await store.find(telegram_id, quote_id)
    if not row:
        raise QuoteConflict("Расчёт не найден. Рассчитайте цену ещё раз")
    frozen = json.loads(row["billing_json"])
    # A replay of a committed launch keeps its old snapshot, even after price
    # or role changes. Only an unclaimed quote must match the current tariff.
    current = frozen
    if row["phase"] == "quoted":
        current = (await quote_video_for_actor(
            telegram_id, frozen["model"], duration=frozen["duration"], quality=frozen["quality"],
            input_video_seconds=frozen["input_seconds"],
            selected_output_seconds=frozen["selected_output_seconds"],
            references_fingerprint=frozen["references_fingerprint"],
        )).to_dict()
    return await store.claim(telegram_id=telegram_id, quote_id=quote_id, quote_hash=quote_hash,
                             original=original, current_billing=current)


def confirmed_rejection(result) -> bool:
    if not isinstance(result, dict) or _has_acceptance_witness(result):
        return False
    if result.get("error") in {"missing_api_key", "prompt_required", "invalid_seedance_scenario",
                              "missing_local_references", "local_image_upload_failed",
                              "invalid_image_references", "missing_seedance_references"}:
        return True
    return result.get("error") == "api_error" and result.get("status_code") in {400, 401, 402, 403, 404, 422, 429}


async def submit_claimed_quote(row: dict, *, submit, bind) -> dict:
    """One committed claim owns provider submission. No ambiguous retry/refund."""
    store = await receipt_store()
    if not row.get("created"):
        if row["phase"] == "accepted":
            await bind(row)
        return row
    quote_id = row["quote_id"]
    try:
        result = await submit(json.loads(row["provider_json"]))
    except Exception as exc:  # noqa: BLE001 - unknown transport outcomes must retain their paid receipt
        logger.warning("Seedance acceptance unknown: quote_id=%s error_type=%s", quote_id, type(exc).__name__)
        await store.unknown(quote_id)
        return dict(row, phase="outcome_unknown")
    task_id = result.get("task_id") if isinstance(result, dict) else None
    if not task_id:
        if confirmed_rejection(result):
            await store.rejected_and_refund(quote_id)
            return dict(row, phase="rejected")
        await store.unknown(quote_id)
        return dict(row, phase="outcome_unknown")
    logger.info("Seedance provider accepted: quote_id=%s provider_task_id=%r", quote_id, str(task_id))
    if not await store.accepted(quote_id, str(task_id)):
        raise QuoteConflict("Accepted task receipt could not be reconciled")
    accepted = dict(row, phase="accepted", provider_task_id=str(task_id))
    await bind(accepted)
    return accepted


async def recover_accepted_quotes():
    store = await receipt_store()
    for row in await store.unbound_accepted():
        billing = json.loads(row["billing_json"])
        try:
            if billing["model"] == "seedance_2_5":
                from bot.handlers.seedance_25_public_release import (
                    _bind_measured_seedance25,
                )
                await _bind_measured_seedance25(row)
            elif billing["model"] == "seedance_2":
                from bot.handlers.seedance_measured_launch import bind_seedance2
                await bind_seedance2(row)
        except Exception as exc:  # noqa: BLE001 - one deferred binding must not stop other receipts
            logger.error("Seedance binding deferred: quote_id=%s provider_task_id=%r error_type=%s",
                         row["quote_id"], row["provider_task_id"], type(exc).__name__)
