"""Exact selected snapshot functions against synthetic SQLite, without app imports."""
import ast
import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import aiosqlite

ROOT = Path(__file__).resolve().parents[2]


class QuoteConflict(ValueError):
    pass


def functions(upload_root):
    tree = ast.parse((ROOT / "bot/services/seedance_quote_snapshots.py").read_text())
    names = {"verify_quote_snapshots", "snapshot_is_leased", "_retention_cutoff"}
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    # Replace only explicit application imports with injected test-owned values.
    for node in nodes:
        node.body = [part for part in node.body if not (isinstance(part, ast.ImportFrom) and (part.module or "").startswith("bot."))]
    namespace = {"asyncio": asyncio, "json": json, "Path": Path, "QuoteConflict": QuoteConflict,
                 "UPLOAD_ROOT": upload_root, "_file_hash": lambda path: hashlib.sha256(path.read_bytes()).hexdigest()}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "snapshot_functions", "exec"), namespace)  # noqa: S102
    return namespace


class SnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.fn = functions(self.root)
        self.db = await aiosqlite.connect(":memory:")
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript("""
            CREATE TABLE seedance_quote_receipts (quote_id TEXT,user_id INTEGER,provider_json TEXT,phase TEXT,
                expires_at TEXT,canonical_bound INTEGER,provider_task_id TEXT,updated_at TEXT);
            CREATE TABLE seedance_quote_media_leases (quote_id TEXT,media_id INTEGER);
            CREATE TABLE wan3_prime_media (id INTEGER,public_url TEXT,local_path TEXT,sha256 TEXT,user_id INTEGER,source TEXT);
            CREATE TABLE generation_tasks (task_id TEXT,status TEXT,completed_at TEXT);
        """)
        recipe = {"_snapshot_media_ids": [1,2,1], "video_urls": ["url1","url2","url1"]}
        await self.db.execute("INSERT INTO seedance_quote_receipts VALUES ('q',1,?,'quoted','2999-01-01',0,'job','2000-01-01')", (json.dumps(recipe),))
        for media_id in (1,2):
            path = self.root / f"{media_id}.mp4"
            path.write_bytes(f"synthetic-{media_id}".encode())
            await self.db.execute("INSERT INTO wan3_prime_media VALUES (?,?,?,?,1,'seedance_quote_snapshot')",
                                  (media_id,f"url{media_id}",str(path),hashlib.sha256(path.read_bytes()).hexdigest()))
            await self.db.execute("INSERT INTO seedance_quote_media_leases VALUES ('q',?)", (media_id,))
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        self.directory.cleanup()

    async def verify(self):
        await self.fn["verify_quote_snapshots"](self.db,"q",1)

    async def leased(self):
        return await self.fn["snapshot_is_leased"](self.db,1)

    async def test_repeated_source_slots_have_distinct_provider_urls(self):
        import math
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        tree = ast.parse((ROOT / "bot/services/seedance_quote_snapshots.py").read_text())
        nodes = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "prepare_video_snapshots"]
        @asynccontextmanager
        async def slot(_):
            yield
        async def snapshot(actor, source, storage, *, occurrence):
            return {"url": f"{source}-slot-{occurrence}", "seconds": 3 if source == "A" else 4}
        ns = {"asyncio": asyncio, "math": math, "probe_slot": slot, "_snapshot": snapshot,
              "Wan3PrimeStorage": lambda: SimpleNamespace(init_schema=AsyncMock())}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "snapshot_plan", "exec"), ns)  # noqa: S102
        rows = await ns["prepare_video_snapshots"](SimpleNamespace(user_id=1), ["A", "B", "A"])
        self.assertEqual([row["url"] for row in rows], ["A-slot-0", "B-slot-0", "A-slot-1"])
        self.assertEqual(sum(row["seconds"] for row in rows), 10)
        self.assertEqual(len({row["url"] for row in rows}), 3)

    async def test_complete_ordered_repeated_plan_passes(self):
        await self.verify()

    async def test_missing_media_row_fails(self):
        await self.db.execute("DELETE FROM wan3_prime_media WHERE id=2")
        with self.assertRaises(QuoteConflict):
            await self.verify()

    async def test_missing_lease_row_fails(self):
        await self.db.execute("DELETE FROM seedance_quote_media_leases WHERE media_id=2")
        with self.assertRaises(QuoteConflict):
            await self.verify()

    async def test_reordered_provider_slots_fail(self):
        recipe = {"_snapshot_media_ids":[1,2,1],"video_urls":["url2","url1","url1"]}
        await self.db.execute("UPDATE seedance_quote_receipts SET provider_json=?",(json.dumps(recipe),))
        with self.assertRaises(QuoteConflict):
            await self.verify()

    async def test_owner_or_hash_change_fails(self):
        await self.db.execute("UPDATE wan3_prime_media SET user_id=2 WHERE id=2")
        with self.assertRaises(QuoteConflict):
            await self.verify()
        await self.db.execute("UPDATE wan3_prime_media SET user_id=1 WHERE id=2")
        (self.root / "2.mp4").write_bytes(b"tampered")
        with self.assertRaises(QuoteConflict):
            await self.verify()

    async def test_missing_canonical_task_holds_accepted_snapshot(self):
        await self.db.execute("UPDATE seedance_quote_receipts SET phase='accepted',canonical_bound=1")
        self.assertTrue(await self.leased())

    async def test_retention_starts_at_terminal_completion(self):
        await self.db.execute("UPDATE seedance_quote_receipts SET phase='accepted',canonical_bound=1")
        await self.db.execute("INSERT INTO generation_tasks VALUES ('job','completed',CURRENT_TIMESTAMP)")
        self.assertTrue(await self.leased())
        await self.db.execute("UPDATE generation_tasks SET completed_at='2000-01-01'")
        self.assertFalse(await self.leased())
        await self.db.execute("UPDATE generation_tasks SET completed_at=NULL")
        self.assertTrue(await self.leased())

    async def test_unknown_and_active_hold_expired_quote_releases(self):
        await self.db.execute("UPDATE seedance_quote_receipts SET expires_at='2000-01-01'")
        self.assertFalse(await self.leased())
        for phase in ('submitting','outcome_unknown','accepted'):
            await self.db.execute("UPDATE seedance_quote_receipts SET phase=?",(phase,))
            self.assertTrue(await self.leased())


if __name__ == "__main__":
    unittest.main()
