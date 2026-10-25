"""Durable Kling4 intents and billing. A lost POST acknowledgement is never retried."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

import aiohttp

from bot import database, db
from bot.services.kling4_contract import (
    DEFAULT_SETTINGS,
    Kling4Error,
    canonical,
    digest,
    require_admin,
    validate_recipe,
    validate_settings,
)
from bot.services.wan3_prime_schema import execute_wan_ddl
from bot.services.wan3_prime_storage import (
    ActualWan3PrimeProbe,
    fetch_public_asset,
    wan3_prime_storage,
)

logger = logging.getLogger(__name__)
ROOT = Path("static/uploads/kling4/results")


class Kling4Transport:
    async def _request(self, method, path, **kwargs):
        from bot.config import config

        if not config.KIE_AI_API_KEY:
            raise Kling4Error("KIE API не настроен.", status=503)
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session,
            session.request(
                method,
                "https://api.kie.ai/api/v1/" + path,
                headers={"Authorization": "Bearer " + config.KIE_AI_API_KEY},
                **kwargs,
            ) as response,
        ):
            # Never retry POST; a 5xx/HTML/malformed acknowledgement is ambiguous.
            payload = await response.json(content_type=None)
            return response.status, payload

    async def create(self, model, data):
        return await self._request(
            "POST", "jobs/createTask", json={"model": model, "input": data}
        )

    async def detail(self, task_id):
        status, body = await self._request(
            "GET", "jobs/recordInfo", params={"taskId": task_id}
        )
        if (
            status != 200
            or body.get("code") != 200
            or not isinstance(body.get("data"), dict)
        ):
            raise Kling4Error("Не удалось подтвердить состояние KIE.", status=502)
        return body["data"]


class Kling4Lifecycle:
    def __init__(self, *, transport=None, probe=None):
        self.transport = transport or Kling4Transport()
        self.probe = probe or ActualWan3PrimeProbe(wan3_prime_storage)
        self.runner = None
        self.telegram_bot = None

    async def init_schema(self):
        await wan3_prime_storage.init_schema()
        async with db.connect(database.DATABASE_PATH) as conn:
            await execute_wan_ddl(
                conn,
                """CREATE TABLE IF NOT EXISTS kling4_settings (
                id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL,
                actor BIGINT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            )
            await execute_wan_ddl(
                conn,
                """CREATE TABLE IF NOT EXISTS kling4_settings_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, revision INTEGER NOT NULL,
                payload TEXT NOT NULL, actor BIGINT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            )
            await execute_wan_ddl(
                conn,
                """CREATE TABLE IF NOT EXISTS kling4_intents (
                task_id TEXT PRIMARY KEY, user_id BIGINT NOT NULL, telegram_id BIGINT NOT NULL,
                idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, recipe TEXT NOT NULL,
                quote TEXT NOT NULL, snapshot TEXT NOT NULL, provider_model TEXT NOT NULL,
                provider_task_id TEXT UNIQUE, status TEXT NOT NULL, provider_state TEXT,
                actual_credits TEXT, error_code TEXT, result_url TEXT, result_path TEXT,
                delivery_status TEXT DEFAULT 'pending', delivery_attempts INTEGER DEFAULT 0,
                lease_until REAL NOT NULL DEFAULT 0, created_epoch REAL NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id,idempotency_key))""",
            )
            await self._ensure_billing_columns(conn)
            await conn.execute(
                "INSERT INTO kling4_settings (id,revision,payload,actor) VALUES (1,1,?,0) ON CONFLICT (id) DO NOTHING",
                (canonical(DEFAULT_SETTINGS),),
            )
            await conn.commit()

    @staticmethod
    async def _ensure_billing_columns(conn):
        columns = {
            "charged_credits": "REAL NOT NULL DEFAULT 0",
            "refunded_credits": "REAL NOT NULL DEFAULT 0",
            "settled": "INTEGER NOT NULL DEFAULT 0",
        }
        native = getattr(conn, "execute_native_ddl", None)
        if native is not None:
            for name, definition in columns.items():
                await native(
                    f"ALTER TABLE kling4_intents ADD COLUMN IF NOT EXISTS {name} "
                    + definition.replace("REAL", "DOUBLE PRECISION")
                )
            return
        present = {
            row[1]
            for row in await (
                await conn.execute("PRAGMA table_info(kling4_intents)")
            ).fetchall()
        }
        for name, definition in columns.items():
            if name not in present:
                await conn.execute(
                    f"ALTER TABLE kling4_intents ADD COLUMN {name} {definition}"
                )

    async def settings(self):
        async with db.connect(database.DATABASE_PATH) as conn:
            row = await (
                await conn.execute(
                    "SELECT revision,payload FROM kling4_settings WHERE id=1"
                )
            ).fetchone()
        return json.loads(row[1]), int(row[0])

    async def update_settings(self, actor, payload, expected_revision):
        require_admin(actor)
        value = validate_settings(payload)
        async with db.connect(database.DATABASE_PATH) as conn:
            changed = await conn.execute(
                "UPDATE kling4_settings SET revision=revision+1,payload=?,actor=?,updated_at=CURRENT_TIMESTAMP WHERE id=1 AND revision=?",
                (canonical(value), actor.telegram_id, expected_revision),
            )
            if changed.rowcount != 1:
                raise Kling4Error(
                    "Настройки изменились. Обновите страницу.", status=409
                )
            await conn.execute(
                "INSERT INTO kling4_settings_audit (revision,payload,actor) VALUES (?,?,?)",
                (expected_revision + 1, canonical(value), actor.telegram_id),
            )
            await conn.commit()
        return {"revision": expected_revision + 1, "settings": value}

    async def quote(self, actor, request):
        from bot.kling4_tariff import attach_retail_price, kling4_public_enabled

        if not actor.is_admin and not kling4_public_enabled():
            raise Kling4Error("Kling 4 пока недоступен.", status=403)

        probe = (
            self.probe.for_actor(actor)
            if hasattr(self.probe, "for_actor")
            else self.probe
        )
        settings, revision = await self.settings()
        prepared = request
        if (
            isinstance(probe, ActualWan3PrimeProbe)
            and getattr(probe, "storage", None) is not None
        ):
            from bot.services.kling4_media import prepare_request

            prepared = await prepare_request(
                actor, request, probe, timeout=settings["result_timeout_seconds"]
            )
        recipe = await validate_recipe(prepared, probe)
        return attach_retail_price(
            recipe.quote(settings, revision), is_admin=actor.is_admin
        )

    async def _row(self, task_id):
        async with db.connect(database.DATABASE_PATH) as conn:
            conn.row_factory = db.Row
            row = await (
                await conn.execute(
                    "SELECT * FROM kling4_intents WHERE task_id=?", (task_id,)
                )
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def public(row):
        quote = json.loads(row["quote"])
        return {
            key: row.get(key)
            for key in (
                "task_id",
                "provider_task_id",
                "status",
                "provider_state",
                "actual_credits",
                "result_url",
                "delivery_status",
                "error_code",
            )
        } | {
            "model": "kling_4",
            "cost": quote.get("cost"),
            "charge_cost": quote.get("charge_cost", 0),
            "admin_free": bool(quote.get("admin_free")),
            "charged_credits": float(row.get("charged_credits") or 0),
            "refunded_credits": float(row.get("refunded_credits") or 0),
            "quote": quote,
        }

    async def status(self, actor, task_id):
        row = await self._row(task_id)
        if not row or row["user_id"] != actor.user_id:
            raise Kling4Error("Задача не найдена.", status=404)
        return self.public(row)

    async def history(self, actor):
        async with db.connect(database.DATABASE_PATH) as conn:
            conn.row_factory = db.Row
            rows = await (
                await conn.execute(
                    "SELECT * FROM kling4_intents WHERE user_id=? ORDER BY created_epoch DESC LIMIT 30",
                    (actor.user_id,),
                )
            ).fetchall()
        return [self.public(dict(row)) for row in rows]

    async def owner_recipe(self, actor, task_id):
        await self.status(actor, task_id)
        return json.loads((await self._row(task_id))["recipe"])

    async def launch(self, actor, request, quote_hash, idempotency_key):
        from bot.kling4_tariff import kling4_public_enabled

        if not actor.is_admin and not kling4_public_enabled():
            raise Kling4Error("Kling 4 пока недоступен.", status=403)
        if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 200:
            raise Kling4Error("Нужен стабильный ключ запуска.")
        request_hash = digest(request)
        async with db.connect(database.DATABASE_PATH) as conn:
            conn.row_factory = db.Row
            previous = await (
                await conn.execute(
                    "SELECT * FROM kling4_intents WHERE user_id=? AND idempotency_key=?",
                    (actor.user_id, idempotency_key),
                )
            ).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise Kling4Error(
                    "Этот ключ уже использован для другого запроса.", status=409
                )
            return self.public(dict(previous))
        probe = (
            self.probe.for_actor(actor)
            if hasattr(self.probe, "for_actor")
            else self.probe
        )
        settings, revision = await self.settings()
        prepared = request
        if (
            isinstance(probe, ActualWan3PrimeProbe)
            and getattr(probe, "storage", None) is not None
        ):
            from bot.services.kling4_media import prepare_request

            prepared = await prepare_request(
                actor, request, probe, timeout=settings["result_timeout_seconds"]
            )
        recipe = await validate_recipe(prepared, probe)
        from bot.kling4_tariff import attach_retail_price

        quote = attach_retail_price(
            recipe.quote(settings, revision), is_admin=actor.is_admin
        )
        if not quote_hash or quote["quote_hash"] != quote_hash:
            raise Kling4Error("Расчёт устарел. Пересчитайте стоимость.", status=409)
        task_id = "kling4_" + uuid.uuid4().hex
        from bot.services.wan3_prime_storage_policy import lock_storage

        async with db.connect(database.DATABASE_PATH) as conn:
            await lock_storage(conn)
            current = await (
                await conn.execute("SELECT revision FROM kling4_settings WHERE id=1")
            ).fetchone()
            if current[0] != revision:
                raise Kling4Error("Тариф изменился. Повторите расчёт.", status=409)
            conn.row_factory = db.Row
            previous = await (
                await conn.execute(
                    "SELECT * FROM kling4_intents WHERE user_id=? AND idempotency_key=?",
                    (actor.user_id, idempotency_key),
                )
            ).fetchone()
            if previous:
                if previous["request_hash"] != request_hash:
                    raise Kling4Error(
                        "Этот ключ уже использован для другого запроса.", status=409
                    )
                await conn.commit()
                return self.public(dict(previous))
            active = await (
                await conn.execute(
                    "SELECT COUNT(*) FROM kling4_intents WHERE status IN ('submitting','pending')"
                )
            ).fetchone()
            if active[0] >= settings["max_active"]:
                raise Kling4Error(
                    "Очередь Kling 4 заполнена. Дождитесь текущих задач.", status=429
                )
            upload_volume = Path("static/uploads")
            upload_volume.mkdir(parents=True, exist_ok=True)
            if (
                shutil.disk_usage(upload_volume).free
                < 1024**3 + (active[0] + 2) * settings["result_max_bytes"]
            ):
                raise Kling4Error(
                    "Недостаточно места для сохранения результата.", status=503
                )
            for info in recipe.media:
                match = await (
                    await conn.execute(
                        "SELECT local_path FROM wan3_prime_media WHERE public_url=? AND user_id=? AND sha256=?",
                        (info.url, actor.user_id, info.sha256),
                    )
                ).fetchone()
                if not match or not Path(match[0]).is_file():
                    raise Kling4Error(
                        "Материал истёк; загрузите его повторно.", status=409
                    )
            inserted = await conn.execute(
                """INSERT INTO kling4_intents (task_id,user_id,telegram_id,idempotency_key,request_hash,
                recipe,quote,snapshot,provider_model,status,charged_credits,created_epoch,lease_until) VALUES (?,?,?,?,?,?,?,?,?,'submitting',?,?,?)
                ON CONFLICT (user_id,idempotency_key) DO NOTHING""",
                (
                    task_id,
                    actor.user_id,
                    actor.telegram_id,
                    idempotency_key,
                    request_hash,
                    canonical(request),
                    canonical(quote),
                    canonical(recipe.snapshot()),
                    recipe.model,
                    float(quote["charge_cost"]),
                    time.time(),
                    time.time() + 120,
                ),
            )
            if inserted.rowcount != 1:
                await conn.rollback()
                return await self.launch(actor, request, quote_hash, idempotency_key)
            # Existing history API owns presentation; no generic KIE poller may submit/settle this task.
            from bot.partner_policy import generation_partner_snapshot

            metadata = generation_partner_snapshot(
                {
                    "provider": "kling4_kie",
                    "provider_model": recipe.model,
                    "kling4": True,
                    "quote": quote,
                    "recipe": recipe.snapshot(),
                    "admin_free": bool(actor.is_admin),
                    "refund_on_failure": float(quote["charge_cost"]) > 0,
                    "private_recipe": True,
                    "prompt_actions_allowed": False,
                },
                accepted=False,
                invite_eligible=not actor.is_admin,
            )
            charge_cost = float(quote["charge_cost"])
            if charge_cost > 0:
                debited = await conn.execute(
                    "UPDATE users SET credits=credits-?,updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=? AND credits>=?",
                    (charge_cost, actor.user_id, charge_cost),
                )
                if debited.rowcount != 1:
                    await conn.rollback()
                    raise Kling4Error("Недостаточно бананов.", status=402)
            await conn.execute(
                """INSERT INTO generation_tasks (user_id,telegram_id,task_id,type,preset_id,model,duration,
                aspect_ratio,prompt,cost,request_data,status) VALUES (?,?,?,'video','kling_4','kling_4',?,?,?,?,?,'processing')""",
                (
                    actor.user_id,
                    actor.telegram_id,
                    task_id,
                    recipe.input["duration"],
                    recipe.input.get("aspect_ratio", "auto"),
                    recipe.input["prompt"],
                    charge_cost,
                    canonical(metadata),
                ),
            )
            await conn.commit()  # intent and history BEFORE outbound POST
        status, provider_id, error = "unknown", None, "submission_unknown"
        try:
            http, response = await self.transport.create(recipe.model, recipe.input)
            data = response.get("data") if isinstance(response, dict) else None
            if (
                http == 200
                and response.get("code") == 200
                and isinstance(data, dict)
                and isinstance(data.get("taskId"), str)
                and data["taskId"].strip()
            ):
                status, provider_id, error = "pending", data["taskId"], None
            elif (
                isinstance(response, dict)
                and response.get("code") in (400, 401, 402, 403, 404, 422, 429)
                and not data
            ):
                status, error = "failed", "provider_rejected"
        except Exception as exc:  # noqa: BLE001 - isolate boundary failures; persist uncertain outcomes
            logger.warning(
                "Kling4 submit uncertain task=%s error_type=%s",
                task_id,
                type(exc).__name__,
            )
        if status == "failed":
            await self._terminal_failure(task_id, error or "provider_rejected")
        else:
            async with db.connect(database.DATABASE_PATH) as conn:
                await conn.execute(
                    "UPDATE kling4_intents SET status=?,provider_task_id=?,error_code=?,lease_until=0,updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
                    (status, provider_id, error, task_id),
                )
                await conn.commit()
            if status == "pending" and provider_id:
                await self._record_provider_acceptance(task_id, provider_id)
        logger.info(
            "Kling4 submitted task=%s provider_task=%s status=%s model=%s",
            task_id,
            provider_id,
            status,
            recipe.model,
        )
        return self.public(await self._row(task_id))

    async def _record_provider_acceptance(self, task_id, provider_task_id):
        """Freeze accepted partner terms without making provider success synchronous."""
        try:
            async with db.connect(database.DATABASE_PATH) as conn:
                conn.row_factory = db.Row
                row = await (
                    await conn.execute(
                        "SELECT request_data FROM generation_tasks WHERE task_id=?",
                        (task_id,),
                    )
                ).fetchone()
                if not row:
                    return
                from bot.partner_policy import generation_partner_snapshot

                try:
                    metadata = json.loads(row[0] or "{}")
                except (TypeError, ValueError):
                    metadata = {}
                metadata = generation_partner_snapshot(
                    metadata, accepted=True, previous=metadata
                )
                metadata["provider_task_id"] = provider_task_id
                await conn.execute(
                    "UPDATE generation_tasks SET request_data=?,updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
                    (canonical(metadata), task_id),
                )
                await conn.commit()
            from bot.partner_policy import mark_generation_accepted

            await mark_generation_accepted(task_id)
        except Exception as exc:  # noqa: BLE001 - billing/provider acceptance stays durable
            logger.warning(
                "Kling4 partner acceptance deferred task=%s error_type=%s",
                task_id,
                type(exc).__name__,
            )

    async def _terminal_failure(self, task_id, error_code, *, resolved_by=None):
        """Mark one proven failure and refund its frozen charge exactly once."""
        claim_sql = (
            """UPDATE kling4_intents SET status='failed',provider_state='fail',
            error_code=?,settled=1,lease_until=0,updated_at=CURRENT_TIMESTAMP
            WHERE task_id=? AND settled=0 AND status IN ('submitting','pending','unknown')"""
            if resolved_by is not None
            else """UPDATE kling4_intents SET status='failed',provider_state='fail',
            error_code=?,settled=1,lease_until=0,updated_at=CURRENT_TIMESTAMP
            WHERE task_id=? AND settled=0 AND status IN ('submitting','pending')"""
        )
        async with db.connect(database.DATABASE_PATH) as conn:
            conn.row_factory = db.Row
            claimed = await conn.execute(claim_sql, (error_code, task_id))
            if claimed.rowcount != 1:
                await conn.rollback()
                return False
            row = await (
                await conn.execute(
                    "SELECT user_id,charged_credits FROM kling4_intents WHERE task_id=?",
                    (task_id,),
                )
            ).fetchone()
            charged = float(row["charged_credits"] or 0)
            if charged > 0:
                refunded = await conn.execute(
                    "UPDATE users SET credits=credits+?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (charged, row["user_id"]),
                )
                if refunded.rowcount != 1:
                    await conn.rollback()
                    raise RuntimeError("Kling4 refund user missing")
            await conn.execute(
                "UPDATE kling4_intents SET refunded_credits=? WHERE task_id=?",
                (charged, task_id),
            )
            if resolved_by is None:
                await conn.execute(
                    "UPDATE generation_tasks SET status='failed',updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
                    (task_id,),
                )
            else:
                task = await (
                    await conn.execute(
                        "SELECT request_data FROM generation_tasks WHERE task_id=?",
                        (task_id,),
                    )
                ).fetchone()
                try:
                    metadata = json.loads(task[0] or "{}") if task else {}
                except (TypeError, ValueError):
                    metadata = {}
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata["kling4_unknown_resolution"] = {
                    "actor_telegram_id": int(resolved_by),
                    "reason": error_code,
                }
                await conn.execute(
                    "UPDATE generation_tasks SET status='failed',request_data=?,updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
                    (canonical(metadata), task_id),
                )
            await conn.commit()
        logger.info("Kling4 failure settled task=%s refund=%s", task_id, charged)
        return True

    async def reject_unknown(self, actor, task_id, resolution):
        """Admin-only release after externally proving an unknown task was not created."""
        require_admin(actor)
        if resolution != "provider_not_created":
            raise Kling4Error(
                "Подтвердите, что задача не создана у провайдера.", status=400
            )
        row = await self._row(task_id)
        if not row or row["status"] != "unknown":
            raise Kling4Error(
                "Возврат доступен только для неопределённого запуска.", status=409
            )
        settled = await self._terminal_failure(
            task_id,
            "operator_verified_not_created",
            resolved_by=actor.telegram_id,
        )
        if not settled:
            raise Kling4Error("Задача уже изменена.", status=409)
        logger.info(
            "Kling4 unknown resolved task=%s actor_telegram_id=%s",
            task_id,
            actor.telegram_id,
        )
        return self.public(await self._row(task_id))

    async def adopt(self, actor, task_id, provider_task_id):
        """Explicit recovery of a lost acknowledgement; never submits a generation."""
        require_admin(actor)
        row = await self._row(task_id)
        if (
            not row
            or row["status"] != "unknown"
            or not isinstance(provider_task_id, str)
            or not 1 <= len(provider_task_id) <= 256
        ):
            raise Kling4Error(
                "Привязка доступна только для неопределённого запуска.", status=409
            )
        data = await self.transport.detail(provider_task_id)
        self._verify(row, data, expected_id=provider_task_id, require_input=True)
        async with db.connect(database.DATABASE_PATH) as conn:
            changed = await conn.execute(
                "UPDATE kling4_intents SET provider_task_id=?,status='pending',error_code=NULL WHERE task_id=? AND status='unknown'",
                (provider_task_id, task_id),
            )
            if changed.rowcount != 1:
                raise Kling4Error("Задача уже изменена.", status=409)
            await conn.commit()
        await self._record_provider_acceptance(task_id, provider_task_id)
        return self.public(await self._row(task_id))

    @staticmethod
    def _verify(row, data, *, expected_id=None, require_input=False):
        if (
            data.get("taskId") != (expected_id or row["provider_task_id"])
            or data.get("model") != row["provider_model"]
        ):
            raise Kling4Error("KIE вернул другую задачу или модель.", status=502)
        if require_input:
            param = data.get("param")
            if isinstance(param, str):
                param = json.loads(param)
            provider_input = param.get("input") if isinstance(param, dict) else None
            if isinstance(provider_input, str):
                provider_input = json.loads(provider_input)
            if provider_input != json.loads(row["snapshot"])["input"]:
                raise Kling4Error(
                    "Запрос KIE не совпадает с сохранённым запуском.", status=409
                )

    async def reconcile(self, task_id):
        lease = time.time() + 1200
        async with db.connect(database.DATABASE_PATH) as conn:
            claimed = await conn.execute(
                "UPDATE kling4_intents SET lease_until=? WHERE task_id=? AND lease_until<? AND status='pending'",
                (lease, task_id, time.time()),
            )
            await conn.commit()
        if claimed.rowcount != 1:
            return
        try:
            row = await self._row(task_id)
            data = await self.transport.detail(row["provider_task_id"])
            self._verify(row, data)
            state = data.get("state")
            if state not in {"waiting", "queuing", "generating", "success", "fail"}:
                raise Kling4Error("Неизвестное состояние KIE.", status=502)
            actual = data.get("creditsConsumed")
            if actual is not None:
                from decimal import Decimal

                if (
                    isinstance(actual, bool)
                    or not Decimal(str(actual)).is_finite()
                    or Decimal(str(actual)) < 0
                ):
                    raise Kling4Error("Неверный расход KIE.", status=502)
                actual = str(actual)
            result_url = result_path = None
            status = "failed" if state == "fail" else "pending"
            if state == "fail":
                await self._terminal_failure(task_id, "provider_failed")
                logger.info(
                    "Kling4 reconcile task=%s provider_task=%s state=%s actual_credits=%s",
                    task_id,
                    row["provider_task_id"],
                    state,
                    actual,
                )
                return
            if state == "success":
                # A malformed resultJson is recoverable even when response happens to look valid.
                if data.get("resultJson") is not None:
                    parsed = json.loads(data["resultJson"])
                else:
                    parsed = data.get("response")
                urls = parsed.get("resultUrls") if isinstance(parsed, dict) else None
                if (
                    not isinstance(urls, list)
                    or not urls
                    or not all(isinstance(u, str) and u for u in urls)
                ):
                    raise Kling4Error(
                        "KIE ещё не вернул корректный результат.", status=502
                    )
                settings, _ = await self.settings()
                ROOT.mkdir(parents=True, exist_ok=True)
                path = ROOT / (task_id + ".mp4")
                temporary = ROOT / (task_id + ".part.mp4")
                try:
                    await fetch_public_asset(
                        urls[0],
                        destination=temporary,
                        max_bytes=settings["result_max_bytes"],
                        timeout_seconds=settings["result_timeout_seconds"],
                    )
                    info = await ActualWan3PrimeProbe().probe_file(
                        str(temporary), kind="video"
                    )
                    if not info.duration_seconds or not info.size_bytes:
                        raise Kling4Error("Результат не является видео.", status=502)
                    await asyncio.to_thread(os.replace, temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
                from bot.config import config

                base = str(config.static_base_url or "").rstrip("/")
                if not base.startswith("https://"):
                    raise Kling4Error(
                        "Публичный адрес результатов не настроен.", status=503
                    )
                from bot.services.wan3_prime_storage import _public_url_for_path

                result_path, result_url = str(path), _public_url_for_path(path)
                status = "done"
            async with db.connect(database.DATABASE_PATH) as conn:
                await conn.execute(
                    """UPDATE kling4_intents SET status=?,provider_state=?,actual_credits=?,result_url=?,result_path=?,
                    error_code=?,settled=?,updated_at=CURRENT_TIMESTAMP WHERE task_id=? AND lease_until=? AND status='pending' """,
                    (
                        status,
                        state,
                        actual,
                        result_url,
                        result_path,
                        "provider_failed" if state == "fail" else None,
                        1 if status == "done" else 0,
                        task_id,
                        lease,
                    ),
                )
                if status in {"done", "failed"}:
                    await conn.execute(
                        """UPDATE generation_tasks SET status=?,result_url=?,completed_at=CURRENT_TIMESTAMP,
                        updated_at=CURRENT_TIMESTAMP WHERE task_id=?""",
                        (
                            "completed" if status == "done" else "failed",
                            result_url,
                            task_id,
                        ),
                    )
                await conn.commit()
            if status == "done":
                from bot.partner_policy import mark_generation_accepted

                await mark_generation_accepted(task_id)
            logger.info(
                "Kling4 reconcile task=%s provider_task=%s state=%s actual_credits=%s",
                task_id,
                row["provider_task_id"],
                state,
                actual,
            )
        finally:
            async with db.connect(database.DATABASE_PATH) as conn:
                await conn.execute(
                    "UPDATE kling4_intents SET lease_until=0 WHERE task_id=? AND lease_until=?",
                    (task_id, lease),
                )
                await conn.commit()

    async def deliver(self, task_id):
        if not self.telegram_bot:
            return
        row = await self._row(task_id)
        if not row:
            return
        async with db.connect(database.DATABASE_PATH) as conn:
            claimed = await conn.execute(
                "UPDATE kling4_intents SET delivery_status='sending',lease_until=? WHERE task_id=? AND status IN ('done','failed') AND delivery_status<>'delivered' AND lease_until<?",
                (time.time() + 120, task_id, time.time()),
            )
            await conn.commit()
        if claimed.rowcount != 1:
            return
        delivered = False
        try:
            if row["status"] == "failed":
                refund = float(row.get("refunded_credits") or 0)
                billing = (
                    f"Списание {refund:g}🍌 возвращено."
                    if refund > 0
                    else "Баланс не списан."
                )
                await self.telegram_bot.send_message(
                    row["telegram_id"],
                    f"Kling 4: не удалось создать видео. {billing}\nЗадача: {task_id}",
                )
            elif (
                row["result_path"]
                and Path(row["result_path"]).is_file()
                and Path(row["result_path"]).stat().st_size <= 49 * 1024**2
            ):
                from aiogram.types import FSInputFile

                await self.telegram_bot.send_video(
                    row["telegram_id"],
                    video=FSInputFile(row["result_path"]),
                    caption=f"Kling 4: видео готово.\nЗадача: {task_id}",
                    supports_streaming=True,
                )
            else:
                from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

                await self.telegram_bot.send_message(
                    row["telegram_id"],
                    f"Kling 4: видео готово.\nЗадача: {task_id}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="Скачать оригинал", url=str(row["result_url"]))
                    ]]),
                )
            delivered = True
        finally:
            async with db.connect(database.DATABASE_PATH) as conn:
                await conn.execute(
                    "UPDATE kling4_intents SET delivery_status=?,delivery_attempts=delivery_attempts+1,lease_until=0 WHERE task_id=?",
                    ("delivered" if delivered else "retry", task_id),
                )
                await conn.commit()

    async def tick(self):
        async with db.connect(database.DATABASE_PATH) as conn:
            await conn.execute(
                "UPDATE kling4_intents SET status='unknown',error_code='submission_unknown',lease_until=0 WHERE status='submitting' AND lease_until<?",
                (time.time(),),
            )
            rows = await (
                await conn.execute(
                    "SELECT task_id,status FROM kling4_intents WHERE status='pending' OR (status IN ('done','failed') AND delivery_status<>'delivered' AND delivery_attempts<5) LIMIT 30"
                )
            ).fetchall()
            await conn.commit()
        for row in rows:
            # PG rows are mappings: iteration yields column names, not values.
            task_id, status = row[0], row[1]
            try:
                if status == "pending":
                    await self.reconcile(task_id)
                else:
                    await self.deliver(task_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - isolate boundary failures; persist uncertain outcomes
                logger.warning(
                    "Kling4 recovery deferred task=%s error_type=%s",
                    task_id,
                    type(exc).__name__,
                )

    async def cleanup_results(self):
        settings, _ = await self.settings()
        cutoff = time.time() - settings["retention_days"] * 86400
        async with db.connect(database.DATABASE_PATH) as conn:
            conn.row_factory = db.Row
            rows = await (
                await conn.execute(
                    "SELECT task_id,result_path FROM kling4_intents WHERE status='done' AND delivery_status='delivered' AND result_path IS NOT NULL AND created_epoch<? AND NOT EXISTS (SELECT 1 FROM generation_tasks g WHERE g.task_id=kling4_intents.task_id AND (COALESCE(g.is_public_feed,FALSE) OR COALESCE(g.is_profile_visible,FALSE))) ORDER BY created_epoch LIMIT 20",
                    (cutoff,),
                )
            ).fetchall()
        for row in rows:
            async with db.connect(database.DATABASE_PATH) as conn:
                # Publication writers use this same storage lock. Published originals are retained.
                from bot.services.wan3_prime_storage_policy import lock_storage

                await lock_storage(conn)
                task = await (
                    await conn.execute(
                        "SELECT is_public_feed,is_profile_visible FROM generation_tasks WHERE task_id=?",
                        (row["task_id"],),
                    )
                ).fetchone()
                if task and (task[0] or task[1]):
                    continue
                path = Path(row["result_path"]).resolve()
                if ROOT.resolve() not in path.parents:
                    continue
                await asyncio.to_thread(path.unlink, missing_ok=True)
                await conn.execute(
                    "UPDATE kling4_intents SET result_path=NULL,result_url=NULL WHERE task_id=?",
                    (row["task_id"],),
                )
                await conn.execute(
                    "UPDATE generation_tasks SET result_url=NULL,result_urls=NULL WHERE task_id=?",
                    (row["task_id"],),
                )
                await conn.commit()

    async def start(self):
        await self.init_schema()
        if self.runner is None or self.runner.done():
            self.runner = asyncio.create_task(self._loop(), name="kling4-reconcile")

    async def _loop(self):
        while True:
            await asyncio.sleep(1)
            try:
                await self.tick()
                await self.cleanup_results()
                settings, _ = await self.settings()
                await asyncio.sleep(settings["poll_seconds"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - isolate boundary failures; persist uncertain outcomes
                logger.error("Kling4 worker error_type=%s", type(exc).__name__)
                await asyncio.sleep(30)

    async def close(self):
        if self.runner:
            self.runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.runner
            self.runner = None


kling4_lifecycle = Kling4Lifecycle()
