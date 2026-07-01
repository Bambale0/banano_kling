#!/usr/bin/env python3
"""Manually retry failed generation tasks that still have enough inputs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import aiosqlite

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")

from bot.config import config  # noqa: E402
from bot.database import DATABASE_PATH, add_generation_task  # noqa: E402
from bot.handlers.generation import (  # noqa: E402
    _serialize_reference_images,
    normalize_image_options,
)
from bot.services.gpt_image_service import gpt_image_service  # noqa: E402
from bot.services.grok_service import grok_service  # noqa: E402
from bot.services.ideogram_service import ideogram_service  # noqa: E402
from bot.services.kling_service import kling_service  # noqa: E402
from bot.services.nano_banana_2_service import nano_banana_2_service  # noqa: E402
from bot.services.nano_banana_pro_service import nano_banana_pro_service  # noqa: E402
from bot.services.seedream_service import seedream_lite_service as seedream_service  # noqa: E402
from bot.video_models import normalize_video_options  # noqa: E402


SUPPORTED_IMAGE_MODELS = {
    "banana_2",
    "banana_pro",
    "gpt_image_2",
    "grok_t2i",
    "grok_i2i",
    "ideogram_character",
    "seedream_5_lite",
    "seedream_edit",
    "wan_27_image",
    "wan_27_image_pro",
}

SUPPORTED_TEXT_VIDEO_MODELS = {
    "v3_std",
    "v3_pro",
    "seedance2",
}

REF_HINT_RE = re.compile(
    r"(с фото|исходн|референс|reference|не меня[яй]|сохрани внешность|"
    r"сохранить внешность|identity|preserve|лицо на 100|черты лица)",
    re.IGNORECASE,
)
UNSAFE_RE = re.compile(
    r"(голая|голый|обнажен|обнажён|нюд|nude|sex|эрот|интим|трогая себя|"
    r"грудь|чулк|нижн(?:ее|ем) бель|lingerie|nsfw)",
    re.IGNORECASE,
)


def _parse_refs(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _local_upload_exists(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc != urlparse(config.static_base_url).netloc:
        return True
    if not parsed.path.startswith("/uploads/"):
        return True
    return (ROOT / "static" / parsed.path.removeprefix("/")).exists()


def _has_missing_refs(refs: list[str]) -> bool:
    return any(not _local_upload_exists(ref) for ref in refs)


def _safe_to_retry(prompt: str) -> bool:
    return not UNSAFE_RE.search(prompt or "")


def _requires_refs(model: str) -> bool:
    return model in {"grok_i2i", "ideogram_character", "seedream_edit"}


def _should_skip(row: aiosqlite.Row) -> str | None:
    model = row["model"] or ""
    prompt = row["prompt"] or ""
    refs = _parse_refs(row["reference_images"])
    if not prompt.strip():
        return "no_prompt"
    if not _safe_to_retry(prompt):
        return "unsafe_or_policy_likely"
    if _has_missing_refs(refs):
        return "missing_reference_files"
    if row["type"] == "image":
        if model not in SUPPORTED_IMAGE_MODELS:
            return "unsupported_image_model"
        if _requires_refs(model) and not refs:
            return "missing_required_refs"
        if not refs and REF_HINT_RE.search(prompt):
            return "prompt_requires_missing_refs"
        return None
    if row["type"] == "video":
        if model not in SUPPORTED_TEXT_VIDEO_MODELS:
            return "unsupported_or_input_heavy_video_model"
        if refs and _has_missing_refs(refs):
            return "missing_reference_files"
        if not refs and REF_HINT_RE.search(prompt):
            return "prompt_requires_missing_refs"
        return None
    return "unsupported_type"


async def _retry_image(row: aiosqlite.Row) -> dict:
    model = row["model"]
    prompt = row["prompt"]
    refs = _parse_refs(row["reference_images"])
    aspect_ratio = row["aspect_ratio"] or "1:1"
    options = normalize_image_options(model, {"aspect_ratio": aspect_ratio})
    callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None

    if model == "banana_2":
        result = await nano_banana_2_service.generate_image(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            resolution=options.get("resolution", "4K"),
            output_format=options.get("output_format", "png"),
            image_input=refs,
            callback_url=callback_url,
        )
    elif model == "banana_pro":
        result = await nano_banana_pro_service.generate_image(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            resolution=options.get("resolution", "4K"),
            output_format=options.get("output_format", "png"),
            image_input=refs,
            callback_url=callback_url,
        )
    elif model == "gpt_image_2":
        result = await gpt_image_service.generate_image(
            prompt=prompt,
            image_urls=refs,
            aspect_ratio=aspect_ratio,
            nsfw_checker=options.get("nsfw_checker", False),
            callback_url=callback_url,
        )
    elif model == "grok_t2i":
        result = await grok_service.generate_text_to_image(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            nsfw_checker=options.get("nsfw_checker", False),
            callback_url=callback_url,
        )
    elif model == "grok_i2i":
        result = await grok_service.generate_image_to_image(
            image_url=refs[0],
            prompt=prompt,
            nsfw_checker=options.get("nsfw_checker", False),
            callback_url=callback_url,
        )
    elif model in {"seedream_5_lite", "seedream_edit"}:
        api_model = "bytedance/seedream-v5-lite" if model == "seedream_5_lite" else "bytedance/seedream-v4-edit"
        result = await seedream_service.generate_image(
            prompt=prompt,
            model=api_model,
            aspect_ratio=aspect_ratio,
            quality=options.get("quality", "basic"),
            nsfw_checker=options.get("nsfw_checker", False),
            image_urls=refs,
            callback_url=callback_url,
        )
    elif model == "ideogram_character":
        result = await ideogram_service.generate_character(
            prompt=prompt,
            reference_image_urls=refs,
            aspect_ratio=aspect_ratio,
            callback_url=callback_url,
        )
    elif model in {"wan_27_image", "wan_27_image_pro"}:
        result = await kling_service.generate_wan_image(
            prompt=prompt,
            model=model,
            input_urls=refs,
            aspect_ratio=aspect_ratio,
            callback_url=callback_url,
        )
    else:
        return {"error": "unsupported_image_model"}

    return result or {"error": "empty_provider_result"}


async def _retry_video(row: aiosqlite.Row) -> dict:
    model = row["model"]
    options = normalize_video_options(model, {})
    return await kling_service.generate_video(
        prompt=row["prompt"],
        model=model,
        duration=int(row["duration"] or 5),
        aspect_ratio=row["aspect_ratio"] or "16:9",
        generate_audio=options.get("sound", True),
        seedance_resolution=options.get("resolution"),
        seedance_nsfw_checker=options.get("nsfw_checker", False),
        seedance_web_search=options.get("web_search", False),
        webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
    ) or {"error": "empty_provider_result"}


async def _mark_source_retry(source_task_id: str, retry_task_id: str) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE generation_tasks SET source_feed_task_id = COALESCE(source_feed_task_id, ?) WHERE task_id = ?",
            (f"manual_retry_started:{retry_task_id}", source_task_id),
        )
        await db.commit()


async def _run(args: argparse.Namespace) -> int:
    limit_sql = "LIMIT ?" if args.limit else ""
    params: list[object] = []
    where = ["status = 'failed'"]
    if args.since:
        where.append("created_at >= ?")
        params.append(args.since)
    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        where.append("model IN (%s)" % ",".join("?" for _ in models))
        params.extend(models)
    if args.task_id:
        where.append("task_id = ?")
        params.append(args.task_id)
    if args.limit:
        params.append(args.limit)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (
            await db.execute(
                f"SELECT * FROM generation_tasks WHERE {' AND '.join(where)} ORDER BY created_at DESC {limit_sql}",
                params,
            )
        ).fetchall()

    report = {"started": [], "skipped": [], "provider_failed": []}
    for row in rows:
        reason = _should_skip(row)
        if reason:
            report["skipped"].append(
                {"task_id": row["task_id"], "model": row["model"], "reason": reason}
            )
            continue
        retry_task_id = f"manual_{uuid.uuid4().hex[:16]}"
        try:
            if args.dry_run:
                report["started"].append(
                    {
                        "source_task_id": row["task_id"],
                        "new_task_id": retry_task_id,
                        "model": row["model"],
                        "dry_run": True,
                    }
                )
                continue

            result = (
                await _retry_image(row)
                if row["type"] == "image"
                else await _retry_video(row)
            )
            if result.get("error") or "task_id" not in result:
                report["provider_failed"].append(
                    {
                        "task_id": row["task_id"],
                        "model": row["model"],
                        "result": result,
                    }
                )
                continue

            provider_task_id = result["task_id"]
            await add_generation_task(
                row["user_id"],
                row["telegram_id"],
                provider_task_id,
                row["type"],
                row["preset_id"] or f"manual_retry:{row['task_id']}",
                model=row["model"],
                duration=row["duration"],
                aspect_ratio=row["aspect_ratio"],
                prompt=row["prompt"],
                cost=0,
                reference_images=row["reference_images"],
                source_feed_task_id=row["task_id"],
                billing_source="manual_retry",
            )
            await _mark_source_retry(row["task_id"], provider_task_id)
            report["started"].append(
                {
                    "source_task_id": row["task_id"],
                    "new_task_id": provider_task_id,
                    "model": row["model"],
                    "telegram_id": row["telegram_id"],
                }
            )
            await asyncio.sleep(args.delay)
        except Exception as exc:
            report["provider_failed"].append(
                {"task_id": row["task_id"], "model": row["model"], "exception": repr(exc)}
            )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: len(v) for k, v in report.items()}, ensure_ascii=False))
    print(f"report={output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since")
    parser.add_argument("--models")
    parser.add_argument("--task-id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default="logs/manual_retry_failed_tasks.json")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
