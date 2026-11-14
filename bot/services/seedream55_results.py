"""Durable multi-output Seedream 5.5 layer completion and settlement."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from bot import db as db_backend
from bot.database import DATABASE_PATH, get_task_by_id
from bot.services.media_storage import persist_upload_file

logger = logging.getLogger(__name__)
MAX_ASSET_BYTES = 35 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024


def extract_layers(result_json: dict) -> tuple[list[str], list[dict]]:
    """Use resultUrls for ordering; preserve KIE per-layer metadata."""
    if not isinstance(result_json, dict):
        raise TypeError("Invalid KIE result JSON")
    urls = result_json.get("resultUrls") or []
    if not isinstance(urls, list) or not 2 <= len(urls) <= 100:
        raise ValueError("Layer decomposition must return 2–100 URLs")
    if len(set(urls)) != len(urls) or any(
        not isinstance(u, str) or urllib.parse.urlsplit(u).scheme != "https"
        for u in urls
    ):
        raise ValueError("Malformed or duplicate KIE layer URLs")
    details = (result_json.get("resultObject") or {}).get("layers_data") or []
    if not isinstance(details, list):
        details = []
    safe_details = []
    for i, url in enumerate(urls):
        meta = details[i] if i < len(details) and isinstance(details[i], dict) else {}
        try:
            z_index = int(meta.get("z_index", i))
        except (TypeError, ValueError):
            z_index = i
        safe_details.append({
            "z_index": z_index,
            "name": str(meta.get("name") or ("Основа" if i == 0 else f"Слой {i}"))[:180],
            "description": str(meta.get("description") or "")[:500],
            "size": str(meta.get("size") or "")[:50],
            "output_format": str(meta.get("output_format") or "png")[:10],
            "bounding_box": meta.get("bounding_box") if isinstance(meta.get("bounding_box"), dict) else None,
        })
    return urls, safe_details


def _save_archive(task_id: str, urls: list[str], metadata: list[dict]) -> str:
    """Stream files to a temporary ZIP, then place the archive in persistent S3."""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(task_id))[:90]
    if not safe_id:
        raise ValueError("Invalid task ID")
    with tempfile.TemporaryDirectory(prefix="seedream55-layers-") as tmp:
        archive_path = Path(tmp) / "layers.zip"
        total = 0
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            manifest = []
            for idx, url in enumerate(urls):
                host = urllib.parse.urlsplit(url).hostname or ""
                # These URLs come from KIE, but never permit arbitrary SSRF at
                # the ZIP downloader boundary. Feed persistence validates too.
                if not (host == "tempfile.aiquickdraw.com" or host.endswith(".aiquickdraw.com")):
                    raise ValueError("Unexpected layer asset host")
                extension = ".png" if idx > 0 else (".jpeg" if urllib.parse.urlsplit(url).path.lower().endswith(".jpeg") else ".png")
                filename = f"{idx:03d}_{'base' if idx == 0 else 'layer'}{extension}"
                request = urllib.request.Request(url, headers={"User-Agent": "NEUROMIX/Seedream55"})
                with urllib.request.urlopen(request, timeout=45) as source, archive.open(filename, "w") as target:
                    if source.status != 200:
                        raise OSError("Layer download failed")
                    single_bytes = 0
                    while True:
                        chunk = source.read(65536)
                        if not chunk:
                            break
                        single_bytes += len(chunk)
                        total += len(chunk)
                        if single_bytes > MAX_ASSET_BYTES or total > MAX_TOTAL_BYTES:
                            raise ValueError("Layer archive exceeded maximum size")
                        target.write(chunk)
                manifest.append({"file": filename, **metadata[idx]})
            archive.writestr("layers.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return persist_upload_file(
            f"seedream55-layers/{safe_id}.zip", archive_path,
            content_type="application/zip",
        )


async def make_layers_archive(task_id: str, urls: list[str], metadata: list[dict]) -> str:
    return await asyncio.to_thread(_save_archive, task_id, urls, metadata)


async def settle_layers(task_id: str, urls: list[str], metadata: list[dict], archive_url: str) -> bool:
    """CAS settlement: save all files + refund unused reservation once, atomically."""
    task = await get_task_by_id(task_id)
    if not task or task.model != "seedream_55_layers" or task.status == "failed":
        return False
    data = json.loads(task.request_data or "{}")
    existing = data.get("seedream55_settlement")
    if existing:
        return existing.get("status") == "completed" and existing.get("urls") == urls

    reserved = float(data.get("seedream55_reserved_cost") or task.cost or 0)
    output_price = float(data.get("seedream55_output_unit_cost") or 0)
    input_price = float(data.get("seedream55_input_unit_cost") or 0)
    max_images = int(data.get("img_layers_max_images") or 30)
    if len(urls) > max_images or not 2 <= len(urls) <= 100 or reserved <= 0 or output_price <= 0 or input_price <= 0:
        raise ValueError("Layer settlement data invalid")
    actual = round(len(urls) * output_price + input_price, 3)
    if actual > reserved + 0.00001:
        raise ValueError("Layer result exceeds charged reservation")
    exempt = bool(data.get("seedream55_charge_exempt"))
    refund = round(reserved - actual, 3) if not exempt else 0.0
    data.setdefault("delivery_status", "result_ready")
    data["seedream55_settlement"] = {
        "status": "completed", "count": len(urls), "reserved": reserved,
        "actual": actual, "refund": refund, "urls": urls,
    }
    data["seedream55_layer_metadata"] = metadata
    data["seedream55_layers_archive_url"] = archive_url
    serialized = json.dumps(data, ensure_ascii=False)
    old_json = task.request_data or "{}"
    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """UPDATE generation_tasks
               SET request_data = ?, result_urls = ?, result_url = ?, status = 'completed',
                   cost = ?, completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND COALESCE(request_data, '{}') = ?
                 AND status IN ('pending', 'processing', 'completed')""",
            (serialized, json.dumps(urls, ensure_ascii=False), urls[0],
             actual if not exempt else 0, task.id, old_json),
        )
        if int(getattr(cursor, "rowcount", 0) or 0) != 1:
            await db.rollback()
            return False
        if refund > 0:
            result = await db.execute(
                "UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (refund, task.user_id),
            )
            if int(getattr(result, "rowcount", 0) or 0) != 1:
                await db.rollback()
                raise RuntimeError("Could not atomically refund layers")
        await db.commit()
    logger.info(
        "Seedream 5.5 layers settled: task=%s outputs=%d reserved=%s actual=%s refund=%s",
        task_id, len(urls), reserved, actual, refund,
    )
    return True
