"""Paid smoke: simulated KIE rejection, real Neironych submission/poll/content.

The CLI requires an isolated SQLite path and never writes customer task rows.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock


async def run(evidence_path: Path) -> None:
    import aiohttp

    from bot import db
    from bot.services.kie_market_service import KieMarketService
    from bot.services.neironych_seedance_admin_service import NeironychAPIError
    from bot.services.seedance_25_service import Seedance25Service
    from bot.services.seedance_service import SeedanceService

    evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}

    def save():
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2))

    async with db.connect() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS generation_tasks "
            "(task_id TEXT PRIMARY KEY, status TEXT, updated_at TEXT)"
        )
        await conn.commit()
    for model, cls in [
        ("seedance-2.0", SeedanceService),
        ("seedance-2.5", Seedance25Service),
    ]:
        if model not in evidence:
            service = cls(kie_key="controlled-primary-rejection")
            service._kie_post = AsyncMock(
                return_value={"error": "api_error", "status_code": 402}
            )
            result = await service.generate_video(
                prompt="A blue paper boat floats slowly on a calm pond in daylight. Stable camera, realistic ripples.",
                duration=4,
                resolution="480p",
                aspect_ratio="16:9",
            )
            assert result.get("provider") == "neironych", result
            evidence[model] = {
                "task_id": result["task_id"],
                "status": "pending",
                "primary": "simulated_402",
                "fallback": "live",
            }
            save()
        async with db.connect() as conn:
            await conn.execute(
                "INSERT INTO generation_tasks (task_id, status) VALUES (?, 'pending') "
                "ON CONFLICT (task_id) DO NOTHING",
                (evidence[model]["task_id"],),
            )
            await conn.commit()
        print(model, json.dumps(evidence[model]), flush=True)
    market = KieMarketService()
    deadline = time.monotonic() + 2400
    try:
        while time.monotonic() < deadline:
            for model, record in evidence.items():
                if record["status"] in {"success", "fail"}:
                    continue
                try:
                    data = await market.get_task_status(record["task_id"])
                except (aiohttp.ClientError, TimeoutError, NeironychAPIError) as exc:
                    print(
                        model, "transient_status_error", type(exc).__name__, flush=True
                    )
                    continue
                if not data:
                    continue
                state = data["state"]
                print(model, state, flush=True)
                if state in {"success", "fail"}:
                    record["status"] = state
                    record["result"] = data
                    async with db.connect() as conn:
                        conn.row_factory = db.Row
                        route = await (
                            await conn.execute(
                                "SELECT request_id FROM seedance_provider_routes WHERE task_id = ?",
                                (record["task_id"],),
                            )
                        ).fetchone()
                    record["provider_request_id"] = route["request_id"]
                    if state == "success":
                        url = json.loads(data["resultJson"])["resultUrls"][0]
                        target = Path("static/uploads") / url.split("/uploads/", 1)[1]
                        assert target.stat().st_size > 1000
                        record["bytes"] = target.stat().st_size
                        record["sha256"] = hashlib.sha256(
                            target.read_bytes()
                        ).hexdigest()
                    save()
            if all(r["status"] in {"success", "fail"} for r in evidence.values()):
                assert all(r["status"] == "success" for r in evidence.values()), (
                    evidence
                )
                return
            await asyncio.sleep(10)
        raise TimeoutError(
            "smoke still pending; resume with the same evidence path and database"
        )
    finally:
        await market.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-live", action="store_true", required=True)
    parser.add_argument("--database-path", type=Path, required=True)
    parser.add_argument("--evidence-path", type=Path, required=True)
    args = parser.parse_args()
    os.environ["DATABASE_URL"] = ""
    os.environ["DATABASE_PATH"] = str(args.database_path.resolve())
    asyncio.run(run(args.evidence_path))
