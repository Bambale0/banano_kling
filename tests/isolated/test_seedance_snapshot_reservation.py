"""Actual upload reservation and capacity functions against synthetic SQLite."""
import ast
import asyncio
import re
import tempfile
import unittest
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite

ROOT = Path(__file__).resolve().parents[2]
MIB = 1024 * 1024


class ValidationError(ValueError):
    def __init__(self, message, **_kwargs):
        super().__init__(message)


def load(namespace):
    storage = ast.parse((ROOT / "bot/services/wan3_prime_storage.py").read_text())
    names = {"init_upload", "_kind_limit", "_allowed_ext", "_safe_basename", "_expires"}
    nodes = [node for node in ast.walk(storage) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    policy = ast.parse((ROOT / "bot/services/wan3_prime_storage_policy.py").read_text())
    nodes += [node for node in policy.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "assert_capacity"]
    class StripImports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            return None if (node.module or "").startswith("bot.") else node
    nodes = [StripImports().visit(node) for node in nodes]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "actual_reservation", "exec"), namespace)  # noqa: S102


class ReservationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dbpath = self.root / "fixture.sqlite"
        self.settings = {"WAN3_UPLOAD_USER_QUOTA_BYTES": 450 * MIB}
        @asynccontextmanager
        async def connect(_path):
            async with aiosqlite.connect(self.dbpath) as db:
                yield db
        async def lock(db):
            await db.execute("BEGIN IMMEDIATE")
        self.ns = {"Any":object,"Path":Path,"re":re,"uuid":uuid,"datetime":datetime,"UTC":UTC,"timedelta":timedelta,
            "asyncio":asyncio,"Wan3PrimeValidationError":ValidationError,"db_backend":SimpleNamespace(connect=connect,Row=aiosqlite.Row,is_postgres=lambda:False),
            "_sqlite_path":lambda:str(self.dbpath),"lock_storage":lock,"ACTIVE_UPLOAD_STATES":"('open','importing')",
            "RESERVED_UPLOAD_STATES":"('open','importing')","MAX_UNFINISHED_SESSIONS":5,"CHUNK_SIZE":7*MIB,
            "CHUNK_ROOT":self.root/"chunks","canonical_child_path":lambda root,key:root/key,
            "IMAGE_EXTENSIONS":{'.jpg','.png'},"VIDEO_EXTENSIONS":{'.mp4','.mov'},"AUDIO_EXTENSIONS":{'.mp3'},"DOCUMENT_EXTENSIONS":{'.pdf'},
            "positive_setting":lambda key,default:self.settings.get(key,default),
            "shutil":SimpleNamespace(disk_usage=lambda _:SimpleNamespace(free=100*1024**3))}
        load(self.ns)
        self.connect = connect
        self.storage = SimpleNamespace(init_schema=AsyncMock())
        self.actor = SimpleNamespace(user_id=1,telegram_id=5000000001)
        async with connect(None) as db:
            await db.executescript("""
            CREATE TABLE wan3_prime_media(user_id INTEGER,size_bytes INTEGER);
            CREATE TABLE wan3_prime_upload_sessions(upload_id TEXT PRIMARY KEY,user_id INTEGER,telegram_id BIGINT,kind TEXT,filename TEXT,content_type TEXT,declared_size INTEGER,expires_at TEXT,status TEXT);
            """)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def reserve(self, **kwargs):
        args = {"kind":"video","filename":"quote.mp4","size":200*MIB,"importing":True,"seedance_snapshot":True}
        args.update(kwargs)
        return await self.ns["init_upload"](self.storage,self.actor,**args)

    async def test_actual_seedance_200mb_reservation_counts_full_quota(self):
        await self.reserve()
        await self.reserve()
        with self.assertRaisesRegex(ValidationError,"quota"):
            await self.reserve()
        async with self.connect(None) as db:
            row = await (await db.execute("SELECT COUNT(*),SUM(declared_size) FROM wan3_prime_upload_sessions")).fetchone()
        self.assertEqual(tuple(row),(2,400*MIB))

    async def test_wan_limit_unchanged_and_internal_override_is_bounded(self):
        for kwargs in ({"seedance_snapshot":False},{"size":200*MIB+1},{"importing":False},{"kind":"image","filename":"x.png"}):
            with self.assertRaises(ValidationError):
                await self.reserve(**kwargs)
        await self.reserve(size=100*MIB,seedance_snapshot=False)

    async def test_global_capacity_still_applies_to_snapshot(self):
        self.settings["WAN3_UPLOAD_GLOBAL_QUOTA_BYTES"] = 199*MIB
        with self.assertRaisesRegex(ValidationError,"global storage"):
            await self.reserve()

    def test_only_server_snapshot_caller_uses_override(self):
        tree = ast.parse((ROOT / "bot/services/seedance_quote_snapshots.py").read_text())
        call = next(node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr == "init_upload")
        self.assertTrue(any(kw.arg == "seedance_snapshot" and isinstance(kw.value,ast.Constant) and kw.value.value is True for kw in call.keywords))
        for path in ("bot/wan3_prime_api.py", "bot/miniapp.py"):
            self.assertNotIn("seedance_snapshot=", (ROOT/path).read_text())


if __name__ == "__main__":
    unittest.main()
