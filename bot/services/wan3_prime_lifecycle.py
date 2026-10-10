from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from bot import database
from bot import db as db_backend
from bot.services import preset_manager as preset_module
from bot.services.wan3_prime_media import (
    WAN3_MODEL_KEY,
    WAN3_PROVIDER_MODEL,
    MediaProbe,
    Wan3PrimeRecipe,
    Wan3PrimeValidationError,
    validate_wan3_recipe,
)
from bot.services.wan3_prime_storage import wan3_prime_probe, wan3_prime_storage

logger = logging.getLogger(__name__)

TERMINAL_SUCCESS = {"success", "completed", "succeeded", "finished"}
TERMINAL_FAILURE = {"fail", "failed", "error"}
PENDING_STATES = {"waiting", "pending", "queuing", "queued", "generating", "processing", "unknown"}


class Wan3PrimeLifecycleError(RuntimeError):
    def __init__(self, message: str, *, status: int = 400, code: str = "wan3_error"):
        super().__init__(message)
        self.status = status
        self.code = code


class ProviderTransport(Protocol):
    async def create_task(self, recipe: Wan3PrimeRecipe, *, callback_url: str | None) -> dict[str, Any]:
        ...

    async def get_task_status(self, provider_task_id: str) -> dict[str, Any] | None:
        ...

    async def close(self) -> None:
        ...


class ResultDownloader(Protocol):
    async def download(self, url: str, *, task_id: str) -> str:
        ...


@dataclass(frozen=True)
class Wan3PrimeActor:
    user_id: int
    telegram_id: int
    is_admin: bool = False
    miniapp_context: dict[str, Any] | None = None
    operation_context: dict[str, Any] | None = None


@dataclass(frozen=True)
class Wan3PrimeQuote:
    quote_hash: str
    recipe_fingerprint: str
    rate_per_second: float
    rate_revision: str
    input_video_seconds: float
    requested_output_seconds: int | None
    reserved_output_seconds: float
    billable_seconds_reserved: float
    reserve_credits: float
    admin_free: bool
    price_configured: bool
    safe_request: dict[str, Any]

    def as_response(self) -> dict[str, Any]:
        return {
            "quotehash": self.quote_hash,
            "quote_hash": self.quote_hash,
            "recipe_fingerprint": self.recipe_fingerprint,
            "rate_per_second": self.rate_per_second,
            "rate_revision": self.rate_revision,
            "input_video_seconds": self.input_video_seconds,
            "requested_output_seconds": self.requested_output_seconds,
            "reserved_output_seconds": self.reserved_output_seconds,
            "billable_seconds_reserved": self.billable_seconds_reserved,
            "reserve_amount": self.reserve_credits,
            "reserve_credits": self.reserve_credits,
            "admin_free": self.admin_free,
            "price_configured": self.price_configured,
        }


class LazyWan3PrimeTransport:
    def __init__(self) -> None:
        self._service = None

    def _get_service(self):
        if self._service is None:
            from bot.services.wan3_prime_service import wan3_prime_service

            self._service = wan3_prime_service
        return self._service

    async def create_task(self, recipe: Wan3PrimeRecipe, *, callback_url: str | None) -> dict[str, Any]:
        service = self._get_service()
        if not recipe.prepared_input:
            raise Wan3PrimeValidationError("Provider input was not validated before reservation")
        return await service.submit_prepared(recipe.prepared_input, callback_url=callback_url)

    async def get_task_status(self, provider_task_id: str) -> dict[str, Any] | None:
        from bot.services.kie_market_service import kie_market_service

        return await kie_market_service.get_task_status(provider_task_id)

    async def close(self) -> None:
        service = self._service
        if service is not None and hasattr(service, "close"):
            await service.close()


class LocalResultDownloader:
    def __init__(self, root: str | os.PathLike[str] = "static/uploads/wan3_prime/results") -> None:
        self.root = Path(root)

    async def download(self, url: str, *, task_id: str) -> str:
        from bot.services.wan3_prime_storage import fetch_public_asset
        extension = Path(urlparse(url).path).suffix.lower()
        if extension not in {'.mp4', '.mov', '.webm'}:
            extension = '.mp4'
        destination = self.root / (task_id + extension)
        await fetch_public_asset(url, destination=destination,
            max_bytes=int(os.getenv('WAN3_RESULT_MAX_BYTES', str(250 * 1024 * 1024))),
            timeout_seconds=int(os.getenv('WAN3_RESULT_DOWNLOAD_TIMEOUT_SECONDS', '180')))
        return str(destination)


def _database_path() -> str:
    return str(getattr(database, "DATABASE_PATH", None) or os.getenv("DATABASE_PATH") or "bot.db")


def _is_postgres() -> bool:
    return bool(getattr(db_backend, "is_postgres", lambda: False)())


def _param() -> str:
    return "%s" if _is_postgres() else "?"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _round_half_credit(value: float) -> float:
    rounded = round(float(value) * 2) / 2
    return int(rounded) if rounded == int(rounded) else rounded


def _extract_provider_task_id(result: dict[str, Any]) -> str | None:
    for key in ("task_id", "taskId", "id"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = result.get("data")
    if isinstance(data, dict):
        return _extract_provider_task_id(data)
    return None


def _extract_result_urls(task_data: dict[str, Any]) -> list[str]:
    response = task_data.get("response")
    if isinstance(response, dict):
        urls = response.get("resultUrls")
        if isinstance(urls, list):
            return [url for url in urls if isinstance(url, str) and url.strip()]
    result_json = task_data.get("resultJson")
    if isinstance(result_json, str) and result_json:
        try:
            parsed = json.loads(result_json)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("resultUrls"), list):
            return [url for url in parsed["resultUrls"] if isinstance(url, str) and url.strip()]
    urls = task_data.get("resultUrls")
    if isinstance(urls, list):
        return [url for url in urls if isinstance(url, str) and url.strip()]
    return []


def _managed_public_url(local_path: str) -> str:
    path = Path(local_path)
    try:
        rel = path.resolve().relative_to(Path("static/uploads").resolve())
    except ValueError:
        return ""
    try:
        from bot.config import config

        base = str(getattr(config, "static_base_url", "") or "").rstrip("/")
    except (ImportError, AttributeError, ValueError):
        base = ""
    if not base:
        return f"/uploads/{rel.as_posix()}"
    return f"{base}/uploads/{rel.as_posix()}"


def _public_callback_base(miniapp_root: str = "") -> str | None:
    try:
        from bot.config import config

        configured_host = getattr(config, "WEBHOOK_HOST", "")
    except (ImportError, AttributeError, ValueError):
        configured_host = ""
    for value in (
        os.getenv("WAN3_CALLBACK_BASE_URL"),
        configured_host,
        os.getenv("WEBHOOK_HOST"),
    ):
        base = str(value or "").rstrip("/")
        if base.startswith(("http://", "https://")):
            return f"{base}{miniapp_root.rstrip('/')}/api/wan3/callback"
    return None


class Wan3PrimeLifecycle:
    def __init__(
        self,
        *,
        transport: ProviderTransport | None = None,
        probe: MediaProbe | None = None,
        downloader: ResultDownloader | None = None,
        preset_manager: Any | None = None,
        miniapp_root: str = "/mini-app",
    ) -> None:
        self.transport = transport or LazyWan3PrimeTransport()
        self.probe = probe or wan3_prime_probe
        self.downloader = downloader
        self.preset_manager = preset_manager or preset_module.preset_manager
        self.miniapp_root = miniapp_root
        self.telegram_bot = None
        self._runner = None

    async def init_schema(self) -> None:
        from bot.services.wan3_prime_schema import execute_wan_ddl

        await wan3_prime_storage.init_schema()
        async with db_backend.connect(_database_path()) as db:
            await execute_wan_ddl(db,
                """
                CREATE TABLE IF NOT EXISTS wan3_prime_intents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    internal_task_id TEXT UNIQUE NOT NULL,
                    user_id BIGINT NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    recipe_fingerprint TEXT NOT NULL,
                    quote_hash TEXT NOT NULL,
                    quote_json TEXT NOT NULL,
                    request_summary TEXT NOT NULL,
                    raw_recipe TEXT NOT NULL,
                    callback_nonce TEXT UNIQUE NOT NULL,
                    provider_task_id TEXT,
                    provider_model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider_state TEXT,
                    reserve_credits REAL NOT NULL DEFAULT 0,
                    charged_credits REAL NOT NULL DEFAULT 0,
                    refunded_credits REAL NOT NULL DEFAULT 0,
                    reserve_refunded INTEGER NOT NULL DEFAULT 0,
                    settled INTEGER NOT NULL DEFAULT 0,
                    result_url TEXT,
                    result_path TEXT,
                    result_seconds REAL,
                    delivery_status TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    lease_until TIMESTAMP,
                    next_attempt_at TIMESTAMP,
                    last_checked_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, idempotency_key)
                )
                """
            )
            await execute_wan_ddl(db,
                "CREATE INDEX IF NOT EXISTS idx_wan3_prime_provider ON wan3_prime_intents(provider_task_id)"
            )
            await execute_wan_ddl(db,
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_wan3_prime_provider_task_id ON wan3_prime_intents(provider_task_id) WHERE provider_task_id IS NOT NULL"
            )
            await execute_wan_ddl(db,
                "CREATE INDEX IF NOT EXISTS idx_wan3_prime_status ON wan3_prime_intents(status, updated_at)"
            )
            await db.commit()
        from bot.services.wan3_prime_recovery import init_recovery_schema

        await init_recovery_schema()
        from bot.services.wan3_prime_trends import init_trend_schema
        await init_trend_schema()

    async def startup(self) -> None:
        await self.init_schema()
        async with db_backend.connect(_database_path()) as db:
            await db.execute(
                "UPDATE wan3_prime_intents SET status = 'unknown', provider_state = 'unknown', updated_at = CURRENT_TIMESTAMP WHERE status = 'submitting' AND (lease_until IS NULL OR lease_until < CURRENT_TIMESTAMP)"
            )
            await db.execute(
                "UPDATE generation_tasks SET status = 'processing', updated_at = CURRENT_TIMESTAMP WHERE task_id IN (SELECT internal_task_id FROM wan3_prime_intents WHERE status = 'unknown')"
            )
            await db.commit()

    async def start_worker(self) -> None:
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._recovery_loop(), name='wan3-prime-recovery')

    async def _recovery_loop(self) -> None:
        await asyncio.sleep(1)
        while True:
            try:
                await self.reconcile_once()
                await wan3_prime_storage.cleanup_expired(limit=50)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - isolate transport/storage failures with durable outcome state
                logger.error('Wan3 recovery iteration failed: error_type=%s', type(exc).__name__)
            await asyncio.sleep(30)

    async def cleanup(self) -> None:
        if self._runner is not None:
            self._runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._runner
            self._runner = None
        if hasattr(self.transport, "close"):
            await self.transport.close()

    def _rate_snapshot(self, recipe: Wan3PrimeRecipe, actor: Wan3PrimeActor) -> tuple[float, str, bool]:
        costs = self.preset_manager.get_video_quality_costs(WAN3_MODEL_KEY)
        if not isinstance(costs, dict):
            costs = {}
        normalized = {str(k).strip().lower(): v for k, v in costs.items()}
        key = recipe.resolution.lower()
        raw = normalized.get(key)
        configured = raw is not None
        try:
            if isinstance(raw, bool):
                raise TypeError("Boolean is not a generation rate")
            rate = float(raw)
        except (TypeError, ValueError):
            rate = 0.0
        if actor.is_admin and not configured:
            return 0.0, "missing-admin-free", False
        if not math.isfinite(rate) or rate <= 0:
            raise Wan3PrimeLifecycleError("Wan 3.0 Prime rate is not configured", status=503, code="missing_rate")
        return rate, f"{WAN3_MODEL_KEY}:{key}:{rate}", True

    def _quote_from_recipe(self, actor: Wan3PrimeActor, recipe: Wan3PrimeRecipe) -> Wan3PrimeQuote:
        rate, revision, configured = self._rate_snapshot(recipe, actor)
        requested = None if recipe.duration == -1 else recipe.duration
        if recipe.duration == -1:
            billable = 30.0
            reserved_output = max(0.0, 30.0 - float(recipe.input_video_seconds))
        else:
            reserved_output = float(recipe.duration)
            billable = float(recipe.input_video_seconds + recipe.duration)
        reserve = 0.0 if actor.is_admin else _round_half_credit(rate * billable)
        if not actor.is_admin and reserve <= 0:
            raise Wan3PrimeLifecycleError("Wan 3.0 Prime reserve rounded to zero", status=503, code="missing_rate")
        fingerprint = recipe.fingerprint()
        quote_payload = {
            # The editor template and exact final prompt are part of the user's quote.
            "prepared_input": recipe.prepared_input,
            "fingerprint": fingerprint,
            "rate": rate,
            "revision": revision,
            "billable": billable,
            "reserve": reserve,
            "admin": actor.is_admin,
        }
        quote_hash = uuid.uuid5(uuid.NAMESPACE_URL, _json_dumps(quote_payload)).hex
        return Wan3PrimeQuote(
            quote_hash=quote_hash,
            recipe_fingerprint=fingerprint,
            rate_per_second=rate,
            rate_revision=revision,
            input_video_seconds=recipe.input_video_seconds,
            requested_output_seconds=requested,
            reserved_output_seconds=reserved_output,
            billable_seconds_reserved=billable,
            reserve_credits=reserve,
            admin_free=actor.is_admin,
            price_configured=configured,
            safe_request=recipe.safe_summary(),
        )

    async def _validated_recipe(self, actor: Wan3PrimeActor, body: dict[str, Any]) -> Wan3PrimeRecipe:
        from bot.services.wan3_prime_repeat import client_recipe, compile_repeat
        from bot.services.wan3_prime_service import wan3_prime_service

        request = client_recipe(body)
        context = {}
        probe = self.probe.for_actor(actor) if hasattr(self.probe, "for_actor") else self.probe
        effective = request
        if request.get("source_feed_gen_id") is not None or request.get("trend_id") is not None:
            effective, probe, context, request = await compile_repeat(actor, request, self.probe)
        recipe = await validate_wan3_recipe(effective, probe)
        try:
            prepared = await wan3_prime_service.prepare_request(**recipe.raw_provider_args())
        except ValueError as exc:
            raise Wan3PrimeValidationError(str(exc)) from exc
        return replace(recipe, prepared_input=prepared, client_request=request, repeat_context=context)

    async def quote(self, actor: Wan3PrimeActor, body: dict[str, Any]) -> Wan3PrimeQuote:
        recipe = await self._validated_recipe(actor, body)
        return self._quote_from_recipe(actor, recipe)

    async def _recipe_and_quote(
        self, actor: Wan3PrimeActor, body: dict[str, Any], quote: Wan3PrimeQuote | dict[str, Any] | None
    ) -> tuple[Wan3PrimeRecipe, Wan3PrimeQuote]:
        if quote is None:
            raise Wan3PrimeLifecycleError("quote_hash is required", status=409, code="missing_quote")
        recipe = await self._validated_recipe(actor, body)
        server_quote = self._quote_from_recipe(actor, recipe)
        supplied_hash = quote.quote_hash if isinstance(quote, Wan3PrimeQuote) else str(quote.get("quote_hash") or quote.get("quotehash") or "")
        if not supplied_hash:
            raise Wan3PrimeLifecycleError("quote_hash is required", status=409, code="missing_quote")
        if supplied_hash != server_quote.quote_hash:
            raise Wan3PrimeLifecycleError("Quote is stale", status=409, code="stale_quote")
        if recipe.fingerprint() != server_quote.recipe_fingerprint:
            raise Wan3PrimeLifecycleError("Quote fingerprint mismatch", status=409, code="stale_quote")
        return recipe, server_quote

    def _callback_url(self, internal_task_id: str, nonce: str) -> str | None:
        base = _public_callback_base(self.miniapp_root)
        if not base:
            return None
        return f"{base}?intent={internal_task_id}&nonce={nonce}"

    async def launch(
        self,
        actor: Wan3PrimeActor,
        body: dict[str, Any],
        quote: Wan3PrimeQuote | dict[str, Any] | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        await self.init_schema()
        key = str(idempotency_key or "").strip()
        if not key or len(key) > 200:
            raise Wan3PrimeLifecycleError("idempotency_key is required", status=400, code="missing_idempotency_key")
        async with db_backend.connect(_database_path()) as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute(
                "SELECT * FROM wan3_prime_intents WHERE user_id = ? AND idempotency_key = ?",
                (actor.user_id, key),
            )
            existing_before_quote = await cursor.fetchone()
        if existing_before_quote:
            from bot.services.wan3_prime_repeat import client_recipe

            persisted = json.loads(existing_before_quote["request_summary"])
            original = persisted.get("client_request")
            if original is not None:
                same_request = _json_dumps(original) == _json_dumps(client_recipe(body))
            else:
                checked = await validate_wan3_recipe(body, self.probe.for_actor(actor) if hasattr(self.probe, "for_actor") else self.probe)
                same_request = existing_before_quote["recipe_fingerprint"] == checked.fingerprint()
            if not same_request:
                raise Wan3PrimeLifecycleError("Same idempotency key used for a different request", status=409, code="idempotency_conflict")
            return self._status_from_row(existing_before_quote)

        recipe, server_quote = await self._recipe_and_quote(actor, body, quote)
        internal_task_id = f"wan3_{uuid.uuid4().hex}"
        nonce = secrets.token_urlsafe(24)
        submission_lease_until = (datetime.now(UTC) + timedelta(minutes=10)).replace(tzinfo=None).isoformat(sep=" ")

        async with db_backend.connect(_database_path()) as db:
            from bot.services.wan3_prime_storage_policy import lock_storage

            db.row_factory = db_backend.Row
            await lock_storage(db)
            from bot.services.wan3_prime_repeat import verify_repeat_in_transaction

            await verify_repeat_in_transaction(db, recipe.repeat_context)
            # Serialize expiry with task persistence: no file may disappear
            # between the validated quote and the committed generation recipe.
            for inputs in recipe.media.values():
                for info in inputs:
                    if info.sha256:
                        present = await (await db.execute(
                            "SELECT local_path FROM wan3_prime_media WHERE public_url = ? AND sha256 = ?",
                            (info.url, info.sha256),
                        )).fetchone()
                        if not present or not Path(present["local_path"]).is_file():
                            raise Wan3PrimeValidationError("Media expired before launch; upload it again", status=409)
            insert_prefix = "INSERT INTO" if _is_postgres() else "INSERT OR IGNORE INTO"
            insert_sql = f"""
                {insert_prefix} wan3_prime_intents (
                    internal_task_id, user_id, telegram_id, idempotency_key,
                    recipe_fingerprint, quote_hash, quote_json, request_summary,
                    raw_recipe, callback_nonce, provider_model, status, reserve_credits, lease_until
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'submitting', ?, ?)
            """
            if _is_postgres():
                insert_sql += " ON CONFLICT (user_id, idempotency_key) DO NOTHING"
            inserted = await db.execute(
                insert_sql,
                (
                    internal_task_id,
                    actor.user_id,
                    actor.telegram_id,
                    key,
                    server_quote.recipe_fingerprint,
                    server_quote.quote_hash,
                    _json_dumps(server_quote.as_response()),
                    _json_dumps(server_quote.safe_request),
                    _json_dumps(recipe.client_request if recipe.repeat_context else recipe.raw_provider_args()),
                    nonce,
                    WAN3_PROVIDER_MODEL,
                    server_quote.reserve_credits,
                    submission_lease_until,
                ),
            )
            if inserted.rowcount != 1:
                cursor = await db.execute(
                    "SELECT * FROM wan3_prime_intents WHERE user_id = ? AND idempotency_key = ?",
                    (actor.user_id, key),
                )
                existing = await cursor.fetchone()
                if existing and existing["recipe_fingerprint"] == server_quote.recipe_fingerprint:
                    await db.commit()
                    return self._status_from_row(existing)
                await db.rollback()
                raise Wan3PrimeLifecycleError("Same idempotency key used for a different request", status=409, code="idempotency_conflict")

            if not actor.is_admin and server_quote.reserve_credits > 0:
                updated = await db.execute(
                    "UPDATE users SET credits = credits - ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND credits >= ?",
                    (server_quote.reserve_credits, actor.user_id, server_quote.reserve_credits),
                )
                if updated.rowcount != 1:
                    await db.rollback()
                    raise Wan3PrimeLifecycleError("Insufficient credits", status=402, code="insufficient_credits")

            from bot.partner_policy import generation_partner_snapshot

            task_metadata = generation_partner_snapshot({
                **recipe.raw_provider_args(),
                "v_model": WAN3_MODEL_KEY,
                "provider": "kie", "provider_model": WAN3_PROVIDER_MODEL,
                "wan3_prime": True, "quote": server_quote.as_response(),
                "delivery_status": "pending", "stable_task_id": internal_task_id,
            }, accepted=False, invite_eligible=not actor.is_admin)
            if recipe.repeat_context:
                task_metadata.update(private_recipe=True, prompt_hidden=True, prompt_actions_allowed=False)
                if recipe.repeat_context.get("trend_id"):
                    task_metadata.update(trend_id=recipe.repeat_context["trend_id"], action_type="trend")
                else:
                    task_metadata.update(source_feed_gen_id=recipe.repeat_context["source_id"], action_type="repeat")
            if actor.operation_context:
                if not actor.is_admin:
                    raise Wan3PrimeLifecycleError("Trusted operator context required", status=403)
                task_metadata["admin_replay"] = dict(actor.operation_context)
                task_metadata["action_type"] = "admin_replay"
            await db.execute(
                """
                INSERT INTO generation_tasks
                    (user_id, telegram_id, task_id, type, preset_id, model, duration,
                     aspect_ratio, prompt, cost, request_data, status)
                VALUES (?, ?, ?, 'video', ?, ?, ?, ?, ?, ?, ?, 'processing')
                """,
                (
                    actor.user_id,
                    actor.telegram_id,
                    internal_task_id,
                    WAN3_MODEL_KEY,
                    WAN3_MODEL_KEY,
                    None if recipe.duration == -1 else recipe.duration,
                    recipe.aspect_ratio,
                    recipe.prompt,
                    server_quote.reserve_credits,
                    _json_dumps(task_metadata),
                ),
            )
            if recipe.repeat_context:
                if recipe.repeat_context.get("trend_id"):
                    await db.execute("UPDATE generation_tasks SET action_type = 'trend' WHERE task_id = ?", (internal_task_id,))
                    await db.execute("INSERT INTO trend_generation_runs (task_id, trend_id, user_id) VALUES (?, ?, ?) ON CONFLICT (task_id) DO NOTHING",
                                     (internal_task_id, recipe.repeat_context["trend_id"], actor.user_id))
                else:
                    await db.execute("UPDATE generation_tasks SET source_feed_gen_id = ?, parent_generation_id = ?, "
                                     "action_type = 'repeat' WHERE task_id = ?",
                                     (recipe.repeat_context["source_id"], recipe.repeat_context["source_id"], internal_task_id))
            if actor.operation_context:
                await db.execute("UPDATE generation_tasks SET parent_generation_id = ?, action_type = 'admin_replay' WHERE task_id = ?",
                                 (actor.operation_context["source_operation_id"], internal_task_id))
            await db.commit()

        callback_url = self._callback_url(internal_task_id, nonce)
        logger.info('Wan3 submit: task_id=%s model=%s scenario=%s reserve=%s', internal_task_id, WAN3_MODEL_KEY, recipe.scenario, server_quote.reserve_credits)
        try:
            result = await self.transport.create_task(recipe, callback_url=callback_url)
        except asyncio.CancelledError:
            await asyncio.shield(self._mark_unknown(internal_task_id, 'submission_interrupted', 'Submission interrupted'))
            raise
        except TimeoutError:
            await self._mark_unknown(internal_task_id, "network_error", "Provider createTask timed out")
            return await self.status(actor, internal_task_id)
        except Exception as exc:  # noqa: BLE001 - isolate transport/storage failures with durable outcome state
            await self._mark_unknown(internal_task_id, "network_error", type(exc).__name__)
            return await self.status(actor, internal_task_id)

        classification, provider_task_id, error_message = self._classify_create_result(result)
        if classification == "accepted" and provider_task_id:
            try:
                await self._bind_provider_id(internal_task_id, provider_task_id)
            except Exception as exc:  # noqa: BLE001 - isolate transport/storage failures with durable outcome state
                logger.error('Wan3 acceptance persistence pending: task_id=%s provider_task_id=%s error_type=%s', internal_task_id, provider_task_id, type(exc).__name__)
                with contextlib.suppress(Exception):
                    await self._mark_unknown(internal_task_id, 'acceptance_persistence_pending', 'Accepted task needs reconciliation')
                return {'ok': True, 'task_id': internal_task_id, 'internal_task_id': internal_task_id,
                        'provider_task_id': provider_task_id, 'status': 'unknown', 'reserve_amount': server_quote.reserve_credits}
            logger.info('Wan3 accepted: task_id=%s provider_task_id=%s', internal_task_id, provider_task_id)
        elif classification == "api_error":
            await self._terminal_failure(internal_task_id, "api_error", error_message or "Provider rejected request")
        else:
            await self._mark_unknown(internal_task_id, classification, error_message or "Provider acceptance unknown")
        return await self.status(actor, internal_task_id)

    def _classify_create_result(self, result: Any) -> tuple[str, str | None, str | None]:
        if not isinstance(result, dict):
            return "invalid_response_type", None, None
        error = str(result.get("error") or "").strip().lower()
        if error in {"network_error", "invalid_json", "invalid_response_type", "invalid_data_structure", "no_task_id"}:
            return error, None, str(result.get("message") or result.get("msg") or result.get("error") or "")
        code = result.get("code")
        provider_task_id = _extract_provider_task_id(result)
        if provider_task_id:
            return "accepted", provider_task_id, None
        if code == 200:
            return "no_task_id", None, str(result.get("message") or result.get("msg") or "")
        if isinstance(code, (int, str)) and str(code).isdigit() and 500 <= int(code) <= 599:
            # A gateway can fail after createTask was accepted. Keep the same
            # reservation/identity until canonical or operator reconciliation.
            return "upstream_submission_unknown", None, "Provider acknowledgement unavailable"
        if error == "api_error":
            return "api_error", None, str(result.get("message") or result.get("msg") or result.get("error") or "")
        if code not in (None, 200) and not result.get("success"):
            return "api_error", None, str(result.get("msg") or result.get("error") or code)
        if result.get("success") is False and (result.get("code") or result.get("error")):
            return "invalid_data_structure", None, str(result.get("error") or result.get("msg") or result.get("code"))
        return "no_task_id", None, None

    async def _mark_unknown(self, internal_task_id: str, code: str, message: str) -> None:
        async with db_backend.connect(_database_path()) as db:
            await db.execute(
                "UPDATE wan3_prime_intents SET status = 'unknown', provider_state = 'unknown', error_code = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE internal_task_id = ? AND settled = 0 AND status IN ('submitting', 'submitted', 'unknown')",
                (code, message, internal_task_id),
            )
            await db.commit()

    async def _bind_provider_id(self, internal_task_id: str, provider_task_id: str) -> None:
        async with db_backend.connect(_database_path()) as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute(
                "SELECT request_data FROM generation_tasks WHERE task_id = ?",
                (internal_task_id,),
            )
            task_row = await cursor.fetchone()
            try:
                request_data = json.loads(task_row["request_data"] or "{}") if task_row else {}
            except (TypeError, json.JSONDecodeError):
                request_data = {}
            if not isinstance(request_data, dict):
                request_data = {}
            from bot.partner_policy import generation_partner_snapshot

            request_data = generation_partner_snapshot(request_data, accepted=True, previous=request_data)
            request_data["provider_task_id"] = provider_task_id
            request_data["delivery_status"] = "pending"
            updated = await db.execute(
                "UPDATE wan3_prime_intents SET provider_task_id = ?, status = 'submitted', provider_state = 'waiting', lease_until = NULL, updated_at = CURRENT_TIMESTAMP WHERE internal_task_id = ? AND provider_task_id IS NULL AND settled = 0 AND status IN ('submitting', 'unknown', 'submitted')",
                (provider_task_id, internal_task_id),
            )
            if updated.rowcount != 1:
                await db.rollback()
                return
            await db.execute(
                "UPDATE generation_tasks SET request_data = ?, updated_at = CURRENT_TIMESTAMP WHERE task_id = ?",
                (_json_dumps(request_data), internal_task_id),
            )
            if request_data.get("trend_id"):
                await db.execute("UPDATE user_prompts SET uses_count = uses_count + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                 (request_data["trend_id"],))
            await db.commit()
        from bot.partner_policy import mark_generation_accepted

        await mark_generation_accepted(internal_task_id)

    async def handle_callback(self, payload: Any, *, internal_task_id: str | None = None, nonce: str | None = None) -> tuple[dict[str, Any] | None, int]:
        # A public provider task id is not authentication. Validate the per-intent
        # secret before any task lookup that could cause upstream traffic.
        if not isinstance(internal_task_id, str) or not internal_task_id.startswith("wan3_") or not isinstance(nonce, str) or not 20 <= len(nonce) <= 200:
            return None, 403
        if not isinstance(payload, dict):
            return None, 400
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        provider_task_id = data.get("taskId") or data.get("task_id")
        if not isinstance(provider_task_id, str) or not provider_task_id.strip() or len(provider_task_id) > 200:
            return None, 400
        provider_task_id = provider_task_id.strip()
        if data.get("model") and data["model"] != WAN3_PROVIDER_MODEL:
            return None, 200
        async with db_backend.connect(_database_path()) as db:
            db.row_factory = db_backend.Row
            row = await (await db.execute(
                "SELECT * FROM wan3_prime_intents WHERE internal_task_id = ? AND callback_nonce = ?",
                (internal_task_id, nonce),
            )).fetchone()
        if not row:
            return None, 200
        if row["settled"]:
            return await self.result(internal_task_id, public=True), 200
        if row["provider_task_id"] and row["provider_task_id"] != provider_task_id:
            return None, 200
        if not row["provider_task_id"]:
            from bot.services.wan3_prime_recovery import remember_candidate

            await remember_candidate(internal_task_id, provider_task_id)
            await self._mark_unknown(internal_task_id, "callback_unbound_provider", "Provider callback requires canonical lineage reconciliation")
            return None, 200
        # The worker owns canonical GET + terminal transitions. Its lease/backoff
        # also throttles callback replays; never poll once here and once there.
        await self.reconcile_once(provider_task_id=provider_task_id, respect_backoff=True)
        return await self.result(internal_task_id, public=True), 200

    async def reconcile_once(self, *, provider_task_id: str | None = None, limit: int = 50, respect_backoff: bool = False) -> int:
        await self.init_schema()
        if provider_task_id is None:
            from bot.services.wan3_prime_recovery import (
                recover_candidates,
                recover_expired_submissions,
            )

            await recover_expired_submissions()
            await recover_candidates(self, limit=limit)
        async with db_backend.connect(_database_path()) as db:
            db.row_factory = db_backend.Row
            if provider_task_id:
                cursor = await db.execute(
                    "SELECT * FROM wan3_prime_intents WHERE provider_task_id = ?",
                    (provider_task_id,),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT * FROM wan3_prime_intents
                    WHERE provider_task_id IS NOT NULL
                      AND status IN ('submitted', 'unknown', 'settlement_pending')
                      AND (next_attempt_at IS NULL OR next_attempt_at <= CURRENT_TIMESTAMP)
                      AND (lease_until IS NULL OR lease_until <= CURRENT_TIMESTAMP)
                    ORDER BY updated_at ASC, id ASC
                    LIMIT ?
                    """,
                    (limit,),
                )
            rows = await cursor.fetchall()
        processed = 0
        for row in rows:
            if not await self._claim_reconcile_lease(row["internal_task_id"], respect_backoff=respect_backoff):
                continue
            try:
                status = await self.transport.get_task_status(row["provider_task_id"])
            except Exception as exc:  # noqa: BLE001 - isolate transport/storage failures with durable outcome state
                logger.info('Wan3 poll failed: task_id=%s error_type=%s', row['internal_task_id'], type(exc).__name__)
                await self._mark_checked(row['internal_task_id'], retry_seconds=60)
                continue
            if not isinstance(status, dict):
                await self._mark_checked(row["internal_task_id"], retry_seconds=30)
                continue
            if status.get("taskId") != row["provider_task_id"] or (status.get('model') and status.get('model') != WAN3_PROVIDER_MODEL):
                await self._mark_checked(row["internal_task_id"], retry_seconds=60)
                continue
            state = str(status.get("state") or status.get("status") or "").lower()
            if state in TERMINAL_SUCCESS:
                if await self._settle_success(row, status):
                    processed += 1
                else:
                    await self._mark_checked(row['internal_task_id'], retry_seconds=60)
            elif state in TERMINAL_FAILURE:
                await self._terminal_failure(
                    row["internal_task_id"],
                    str(status.get("failCode") or "provider_failed"),
                    str(status.get("failMsg") or "Provider generation failed"),
                )
                processed += 1
            elif state in PENDING_STATES:
                retry_at = (datetime.now(UTC) + timedelta(seconds=30)).replace(tzinfo=None).isoformat(sep=" ")
                async with db_backend.connect(_database_path()) as db:
                    await db.execute(
                        "UPDATE wan3_prime_intents SET provider_state = ?, lease_until = NULL, last_checked_at = CURRENT_TIMESTAMP, next_attempt_at = ?, updated_at = CURRENT_TIMESTAMP WHERE internal_task_id = ? AND settled = 0",
                        (state, retry_at, row["internal_task_id"]),
                    )
                    await db.commit()
            else:
                await self._mark_checked(row['internal_task_id'], retry_seconds=60)
        if self.telegram_bot is not None:
            await self.deliver_ready_once(self.telegram_bot, limit=limit)
        return processed

    async def _finish_delivery(self, row, lease: str, outcome) -> bool:
        """Commit the Telegram receipt and public history marker together, fenced by lease."""
        retry_at = None
        if outcome.status in {"pending", "link_sent"}:
            retry_at = (datetime.now(UTC) + timedelta(seconds=outcome.retry_after)).replace(tzinfo=None).isoformat(sep=" ")
        async with db_backend.connect(_database_path()) as db:
            db.row_factory = db_backend.Row
            await db.execute("BEGIN IMMEDIATE" if not _is_postgres() else "BEGIN")
            changed = await db.execute(
                "UPDATE wan3_prime_intents SET delivery_status = ?, lease_until = NULL, "
                "next_attempt_at = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE internal_task_id = ? AND delivery_status = 'delivering' AND lease_until = ?",
                (outcome.status, retry_at, row["internal_task_id"], lease),
            )
            if changed.rowcount != 1:
                await db.rollback()
                return False
            task = await (await db.execute(
                "SELECT request_data FROM generation_tasks WHERE task_id = ?", (row["internal_task_id"],),
            )).fetchone()
            if not task:
                await db.rollback()
                return False
            metadata = json.loads(task["request_data"] or "{}")
            metadata["delivery_status"] = outcome.status
            metadata["delivery_error"] = outcome.error
            metadata["delivery_attempts"] = int(metadata.get("delivery_attempts") or 0) + 1
            if outcome.message_id is not None:
                metadata["delivery_message_id"] = outcome.message_id
            if outcome.status == "link_sent":
                metadata["delivery_link_sent"] = True
            await db.execute("UPDATE generation_tasks SET request_data = ?, updated_at = CURRENT_TIMESTAMP WHERE task_id = ?",
                             (_json_dumps(metadata), row["internal_task_id"]))
            if outcome.status == "unavailable":
                await db.execute("UPDATE users SET telegram_chat_state = CASE WHEN telegram_chat_state = 'never_started' "
                                 "THEN 'never_started' ELSE 'unavailable' END WHERE id = ?", (row["user_id"],))
            elif outcome.message_id is not None:
                await db.execute("UPDATE users SET telegram_chat_state = 'available' WHERE id = ?", (row["user_id"],))
            await db.commit()
        logger.info("Wan3 delivery: task_id=%s provider_task_id=%s status=%s message_id=%s error=%s",
                    row["internal_task_id"], row["provider_task_id"], outcome.status, outcome.message_id, outcome.error)
        return True

    async def deliver_ready_once(self, bot: Any, *, limit: int = 20) -> int:
        from bot.services.wan3_prime_delivery import (
            DeliveryOutcome,
            deliver_wan_result,
            delivery_timeout,
        )

        # A crash after a Telegram send has an ambiguous outcome. A stale lease
        # must not silently send the same video again.
        async with db_backend.connect(_database_path()) as db:
            db.row_factory = db_backend.Row
            expired = await (await db.execute(
                "SELECT * FROM wan3_prime_intents WHERE delivery_status = 'delivering' "
                "AND lease_until <= CURRENT_TIMESTAMP LIMIT ?", (limit,),
            )).fetchall()
        for row in expired:
            await self._finish_delivery(row, row["lease_until"], DeliveryOutcome("uncertain", error="delivery_receipt_unknown"))

        async with db_backend.connect(_database_path()) as db:
            db.row_factory = db_backend.Row
            rows = await (await db.execute(
                """
                SELECT * FROM wan3_prime_intents
                WHERE status IN ('completed', 'failed')
                  AND (lease_until IS NULL OR lease_until <= CURRENT_TIMESTAMP)
                  AND (
                    (delivery_status IN ('result_ready', 'failure_ready', 'pending', 'link_sent')
                     AND (next_attempt_at IS NULL OR next_attempt_at <= CURRENT_TIMESTAMP))
                    OR (delivery_status = 'unavailable' AND EXISTS (
                        SELECT 1 FROM users WHERE users.id = wan3_prime_intents.user_id
                        AND users.telegram_chat_state = 'available'
                    ))
                  )
                ORDER BY updated_at ASC, id ASC LIMIT ?
                """, (limit,),
            )).fetchall()
        delivered = 0
        for row in rows:
            lease = await self._claim_delivery_lease(row["internal_task_id"], seconds=delivery_timeout() * 4 + 60)
            if not lease:
                continue
            try:
                allowed = await asyncio.wait_for(database.can_attempt_telegram_delivery(
                    int(row["telegram_id"]), probe=getattr(bot, "get_chat", None)), timeout=15)
            except Exception as exc:  # noqa: BLE001 - isolate transport/storage failures with durable outcome state
                outcome = DeliveryOutcome("pending", error=f"chat_check_{type(exc).__name__}")
            else:
                outcome = (await deliver_wan_result(bot, dict(row))) if allowed else DeliveryOutcome("unavailable", error="chat_not_started")
            if await self._finish_delivery(row, lease, outcome) and outcome.status == "delivered":
                delivered += 1
        return delivered

    async def _claim_delivery_lease(self, internal_task_id: str, seconds: int = 420) -> str | None:
        lease_until = (datetime.now(UTC) + timedelta(seconds=seconds)).replace(tzinfo=None).isoformat(sep=" ")
        async with db_backend.connect(_database_path()) as db:
            updated = await db.execute(
                "UPDATE wan3_prime_intents SET delivery_status = 'delivering', lease_until = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE internal_task_id = ? AND status IN ('completed', 'failed') "
                "AND delivery_status IN ('result_ready', 'failure_ready', 'pending', 'link_sent', 'unavailable') "
                "AND (lease_until IS NULL OR lease_until <= CURRENT_TIMESTAMP)",
                (lease_until, internal_task_id),
            )
            await db.commit()
            return lease_until if updated.rowcount == 1 else None

    async def _claim_reconcile_lease(self, internal_task_id: str, seconds: int = 120, *, respect_backoff: bool = False) -> bool:
        lease_until = (datetime.now(UTC) + timedelta(seconds=seconds)).replace(tzinfo=None).isoformat(sep=" ")
        schedule_clause = " AND (next_attempt_at IS NULL OR next_attempt_at <= CURRENT_TIMESTAMP)" if respect_backoff else ""
        async with db_backend.connect(_database_path()) as db:
            updated = await db.execute(
                "UPDATE wan3_prime_intents SET lease_until = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE internal_task_id = ? AND settled = 0 "
                "AND (lease_until IS NULL OR lease_until <= CURRENT_TIMESTAMP)" + schedule_clause,
                (lease_until, internal_task_id),
            )
            await db.commit()
            return updated.rowcount == 1

    async def _mark_checked(self, internal_task_id: str, *, retry_seconds: int) -> None:
        retry_at = (datetime.now(UTC) + timedelta(seconds=retry_seconds)).replace(tzinfo=None).isoformat(sep=" ")
        async with db_backend.connect(_database_path()) as db:
            await db.execute(
                "UPDATE wan3_prime_intents SET lease_until = NULL, last_checked_at = CURRENT_TIMESTAMP, next_attempt_at = ?, updated_at = CURRENT_TIMESTAMP WHERE internal_task_id = ? AND settled = 0",
                (retry_at, internal_task_id),
            )
            await db.commit()

    async def _settle_success(self, row: db_backend.Row, provider_data: dict[str, Any]) -> bool:
        urls = _extract_result_urls(provider_data)
        if not urls:
            return False
        downloader = self.downloader
        if downloader is None:
            downloader = LocalResultDownloader()
        try:
            stored_path = dict(row).get('result_path')
            local_path = stored_path if stored_path and os.path.isfile(stored_path) else await downloader.download(urls[0], task_id=row["internal_task_id"])
        except Exception as exc:  # noqa: BLE001 - isolate transport/storage failures with durable outcome state
            logger.warning("Wan3 result download failed: task=%s reason=%s", row["internal_task_id"], type(exc).__name__)
            return False
        if not local_path or not os.path.exists(local_path):
            return False
        public_url = _managed_public_url(local_path)
        if not public_url:
            logger.warning("Wan3 result not under managed public upload root: task=%s", row["internal_task_id"])
            return False
        result_seconds = None
        if self.probe is not None:
            try:
                info = await self.probe.probe_file(local_path, kind="video")
                result_seconds = info.duration_seconds
            except (ImportError, AttributeError, ValueError):
                result_seconds = None
        if result_seconds is None or not math.isfinite(float(result_seconds)) or float(result_seconds) <= 0:
            async with db_backend.connect(_database_path()) as db:
                await db.execute(
                    "UPDATE wan3_prime_intents SET status = 'settlement_pending', provider_state = 'success', result_path = ?, result_url = ?, updated_at = CURRENT_TIMESTAMP WHERE internal_task_id = ? AND settled = 0",
                    (local_path, public_url, row["internal_task_id"]),
                )
                await db.commit()
            return False

        quote = json.loads(row["quote_json"])
        rate = float(quote["rate_per_second"])
        input_seconds = float(quote["input_video_seconds"])
        actual_billable = input_seconds + float(result_seconds)
        reserve = float(row["reserve_credits"] or 0)
        charge = min(reserve, _round_half_credit(rate * actual_billable))
        refund = max(0.0, reserve - charge)
        async with db_backend.connect(_database_path()) as db:
            db.row_factory = db_backend.Row
            await db.execute("BEGIN IMMEDIATE" if not _is_postgres() else "BEGIN")
            claimed = await db.execute(
                """
                UPDATE wan3_prime_intents
                SET status = 'settling_success', updated_at = CURRENT_TIMESTAMP
                WHERE internal_task_id = ?
                  AND settled = 0
                  AND status IN ('submitted', 'unknown', 'settlement_pending')
                """,
                (row["internal_task_id"],),
            )
            if claimed.rowcount != 1:
                await db.rollback()
                return False
            if refund > 0:
                balance_update = await db.execute(
                    "UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (refund, row["user_id"]),
                )
                if balance_update.rowcount != 1:
                    await db.rollback()
                    return False
            await db.execute(
                """
                UPDATE wan3_prime_intents
                SET status = 'completed', provider_state = 'success', settled = 1,
                    charged_credits = ?, refunded_credits = ?, reserve_refunded = ?,
                    result_url = ?, result_path = ?, result_seconds = ?,
                    delivery_status = 'result_ready', lease_until = NULL,
                    last_checked_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE internal_task_id = ? AND settled = 0
                """,
                (charge, refund, 1 if refund else 0, public_url, local_path, float(result_seconds), row["internal_task_id"]),
            )
            task = await (await db.execute("SELECT request_data FROM generation_tasks WHERE task_id = ?", (row['internal_task_id'],))).fetchone()
            if not task:
                await db.rollback()
                return False
            request_data = json.loads(task['request_data'] or '{}')
            request_data.update({
                "provider": "kie",
                "provider_model": WAN3_PROVIDER_MODEL,
                "provider_task_id": row["provider_task_id"],
                "wan3_prime": True,
                "delivery_status": "result_ready",
                "stable_task_id": row["internal_task_id"],
                "settled_cost": charge,
                "actual_duration_seconds": float(result_seconds),
                "billing_status": "settled",
                "provider_duration_exceeded_reserve": actual_billable > float(quote['billable_seconds_reserved']) + 0.05,
            })
            await db.execute(
                """
                UPDATE generation_tasks
                SET status = 'completed', result_url = ?, cost = ?, request_data = ?,
                    completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
                """,
                (public_url, charge, _json_dumps(request_data), row["internal_task_id"]),
            )
            context = json.loads(row["request_summary"]).get("repeat_context") or {}
            if context and charge > 0:
                await database._credit_prompt_repeat_reward_in_db(
                    db, author_id=int(context["owner_id"]), repeater_id=int(row["user_id"]),
                    source_type="prompt" if context.get("trend_id") else "feed", source_id=int(context.get("trend_id") or context["source_id"]),
                    repeat_task_id=row["internal_task_id"], credits_spent=charge,
                )
            await db.commit()
        return True

    async def resolve_unknown_refund(self, internal_task_id: str, *, admin_telegram_id: int, reason: str) -> None:
        from bot.config import config

        if not config.is_admin(admin_telegram_id):
            raise Wan3PrimeLifecycleError("Administrator access required", status=403, code="admin_required")
        if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 1000:
            raise Wan3PrimeLifecycleError("Document the provider/operator finding before resolving", status=400, code="reason_required")
        await self._terminal_failure(internal_task_id, "operator_resolved_unknown", "Operator confirmed resolution",
                                     operator=(admin_telegram_id, reason.strip()))

    async def _terminal_failure(self, internal_task_id: str, code: str, message: str,
                                *, operator: tuple[int, str] | None = None) -> None:
        async with db_backend.connect(_database_path()) as db:
            db.row_factory = db_backend.Row
            await db.execute("BEGIN IMMEDIATE" if not _is_postgres() else "BEGIN")
            cur = await db.execute(
                "SELECT * FROM wan3_prime_intents WHERE internal_task_id = ?",
                (internal_task_id,),
            )
            row = await cur.fetchone()
            if not row:
                await db.rollback()
                return
            claimed = await db.execute(
                """
                UPDATE wan3_prime_intents
                SET status = 'settling_failure', updated_at = CURRENT_TIMESTAMP
                WHERE internal_task_id = ?
                  AND settled = 0
                  AND status IN ('submitting', 'submitted', 'unknown', 'settlement_pending')
                """ + (" AND status = 'unknown' AND provider_task_id IS NULL" if operator else ""),
                (internal_task_id,),
            )
            if claimed.rowcount != 1:
                await db.rollback()
                return
            reserve = float(row["reserve_credits"] or 0)
            if reserve > 0:
                balance_update = await db.execute(
                    "UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (reserve, row["user_id"]),
                )
                if balance_update.rowcount != 1:
                    await db.rollback()
                    return
            await db.execute(
                """
                UPDATE wan3_prime_intents
                SET status = 'failed', provider_state = 'fail', settled = 1,
                    delivery_status = 'failure_ready', reserve_refunded = 1, refunded_credits = ?,
                    error_code = ?, error_message = ?, lease_until = NULL,
                    last_checked_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE internal_task_id = ?
                """,
                (reserve, code, "Provider generation failed", internal_task_id),
            )
            await db.execute(
                "UPDATE generation_tasks SET status = 'failed', cost = 0, updated_at = CURRENT_TIMESTAMP WHERE task_id = ?",
                (internal_task_id,),
            )
            if operator:
                await db.execute("INSERT INTO wan3_prime_operator_audit "
                                 "(internal_task_id, admin_telegram_id, action, reason, details) VALUES (?, ?, 'refund_unknown', ?, ?)",
                                 (internal_task_id, operator[0], operator[1], _json_dumps({"refunded_credits": reserve})))
            await db.commit()

    async def _intent(self, internal_task_id: str, *, user_id: int | None = None) -> db_backend.Row | None:
        async with db_backend.connect(_database_path()) as db:
            db.row_factory = db_backend.Row
            if user_id is None:
                cur = await db.execute(
                    "SELECT * FROM wan3_prime_intents WHERE internal_task_id = ?",
                    (internal_task_id,),
                )
            else:
                cur = await db.execute(
                    "SELECT * FROM wan3_prime_intents WHERE internal_task_id = ? AND user_id = ?",
                    (internal_task_id, user_id),
                )
            return await cur.fetchone()

    async def status(self, actor: Wan3PrimeActor, internal_task_id: str) -> dict[str, Any]:
        row = await self._intent(internal_task_id, user_id=actor.user_id)
        if not row:
            raise Wan3PrimeLifecycleError("Task not found", status=404, code="not_found")
        return self._status_from_row(row)

    def _status_from_row(self, row: db_backend.Row) -> dict[str, Any]:
        return {
            "ok": True,
            "task_id": row["internal_task_id"],
            "internal_task_id": row["internal_task_id"],
            "provider_task_id": row["provider_task_id"],
            "status": row["status"],
            "provider_state": row["provider_state"],
            "reserve_amount": float(row["reserve_credits"] or 0),
            "charged_credits": float(row["charged_credits"] or 0),
            "refunded_credits": float(row["refunded_credits"] or 0),
            "result_url": row["result_url"],
            "delivery_status": row["delivery_status"],
            "error_code": row["error_code"],
            "error_message": "Generation failed. Reserve was refunded." if row["status"] == "failed" else row["error_message"],
        }

    async def result(self, internal_task_id: str, *, public: bool = False) -> dict[str, Any] | None:
        row = await self._intent(internal_task_id)
        if not row:
            return None
        payload = {
            "task_id": row["internal_task_id"],
            "provider_task_id": row["provider_task_id"],
            "status": row["status"],
            "result_url": row["result_url"],
            "cost": row["charged_credits"],
            "delivery_status": row["delivery_status"],
        }
        if not public:
            payload["result_path"] = row["result_path"]
        return payload

    async def owner_recipe(self, actor: Wan3PrimeActor, internal_task_id: str) -> dict[str, Any]:
        row = await self._intent(internal_task_id, user_id=actor.user_id)
        if not row:
            raise Wan3PrimeLifecycleError("Task not found", status=404, code="not_found")
        return json.loads(row["raw_recipe"])


wan3_prime_lifecycle = Wan3PrimeLifecycle()
