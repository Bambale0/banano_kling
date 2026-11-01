"""Paid isolated smoke for Neironych primary and confirmed-rejection KIE fallback."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock


async def run(args) -> None:
    import aiohttp

    from bot import db
    from bot.services import seedance_provider_fallback as routing
    from bot.services.seedance_25_service import Seedance25Service
    from bot.services.seedance_service import SeedanceService

    evidence_path = args.evidence_path
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}

    def save():
        evidence_path.write_text(json.dumps(evidence, indent=2))

    if args.force_primary_rejection:
        routing.neironych_seedance_admin_service.submit = AsyncMock(
            side_effect=routing.NeironychAPIError("controlled rejection", status=402),
        )
    async with db.connect() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS generation_tasks "
            "(task_id TEXT PRIMARY KEY, status TEXT, updated_at TEXT)"
        )
        await conn.commit()
    if not evidence.get("task_id"):
        kwargs = {
            "prompt": "A blue paper boat floats slowly on calm water. Stable camera.",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        }
        if args.fixture_path:
            fixture = json.loads(args.fixture_path.read_text())
            source = fixture["request_data"]
            kwargs.update(
                prompt=fixture["prompt"],
                duration=source["duration"],
                resolution=source["resolution"],
                aspect_ratio=source["aspect_ratio"],
                reference_image_urls=source["reference_images"],
                reference_video_urls=source["v_reference_videos"],
                reference_audio_urls=source["reference_audios"],
            )
            evidence["trend_id"] = fixture["trend_id"]
        service = (
            Seedance25Service() if args.model == "seedance-2.5" else SeedanceService()
        )
        result = await service.generate_video(**kwargs)
        assert result.get("provider") == "neironych", {"error": result.get("error")}
        evidence.update(
            task_id=result["task_id"],
            status="pending",
            model=args.model,
            expected_provider="kie" if args.force_primary_rejection else "neironych",
            customer_balance_mutated=False,
            prompt_sha256=hashlib.sha256(kwargs["prompt"].encode()).hexdigest(),
        )
        save()
    async with db.connect() as conn:
        await conn.execute(
            "INSERT INTO generation_tasks (task_id,status) VALUES (?, 'pending') "
            "ON CONFLICT (task_id) DO NOTHING",
            (evidence["task_id"],),
        )
        await conn.commit()
    deadline = time.monotonic() + args.timeout_seconds
    while time.monotonic() < deadline:
        if evidence.get("status") == "success":
            print(json.dumps(evidence), flush=True)
            return
        record = await routing.resolve_seedance_status(
            evidence["task_id"],
            AsyncMock(side_effect=AssertionError("unexpected KIE primary")),
        )
        route = await routing._load(evidence["task_id"])
        evidence.update(
            status=record["state"], phase=route["phase"], request_id=route["request_id"]
        )
        save()
        if record["state"] == "fail":
            raise RuntimeError("live smoke failed: " + str(record.get("failCode")))
        if record["state"] == "success":
            assert (route["phase"] == "kie_completed") == args.force_primary_rejection
            url = json.loads(record["resultJson"])["resultUrls"][0]
            target = Path("static/uploads/seedance_routing_smoke") / (
                evidence["task_id"] + ".mp4"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            async with (
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=180)
                ) as session,
                session.get(url) as response,
            ):
                response.raise_for_status()
                content = await response.read()
            assert len(content) > 1000 and b"ftyp" in content[:64]
            target.write_bytes(content)
            evidence.update(
                bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                local_file=str(target),
            )
            repeat = await routing.resolve_seedance_status(
                evidence["task_id"], AsyncMock()
            )
            assert repeat == record
            evidence["repeat_poll_same_result"] = True
            save()
            print(json.dumps(evidence), flush=True)
            return
        print(
            json.dumps(
                {k: evidence[k] for k in ["model", "task_id", "status", "phase"]}
            ),
            flush=True,
        )
        await asyncio.sleep(10)
    raise TimeoutError("resume with same database/evidence paths; do not resubmit")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-live", action="store_true", required=True)
    parser.add_argument("--database-path", type=Path, required=True)
    parser.add_argument("--evidence-path", type=Path, required=True)
    parser.add_argument(
        "--model", choices=["seedance-2.0", "seedance-2.5"], required=True
    )
    parser.add_argument("--force-primary-rejection", action="store_true")
    parser.add_argument("--fixture-path", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=2400)
    args = parser.parse_args()
    os.environ["DATABASE_URL"] = ""
    os.environ["DATABASE_PATH"] = str(args.database_path.resolve())
    os.environ["SEEDANCE_PRIMARY_PROVIDER"] = "neironych"
    os.environ["SEEDANCE_FALLBACK_PROVIDER"] = "kie"
    asyncio.run(run(args))
