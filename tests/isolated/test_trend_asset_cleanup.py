"""Exercise the real cleanup loop on synthetic files without app/DB imports."""
import ast
import asyncio
import logging
import os
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[2]


class EndIteration(BaseException):
    """Stop the infinite worker after one completed test iteration."""


class TrendAssetCleanupTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.old_cwd = Path.cwd()
        os.chdir(self.workspace.name)
        self.addCleanup(os.chdir, self.old_cwd)
        self.now = time.time()
        self.log = logging.getLogger("isolated.cleanup")

    def file(self, relative, *, old=True):
        path = Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic fixture")
        timestamp = self.now - 1000 if old else self.now
        os.utime(path, (timestamp, timestamp))
        return path

    def run_iteration(self, *, protected=()):
        sleeps = 0

        async def sleep(_seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 2:
                raise EndIteration

        namespace = {
            "os": os, "time": types.SimpleNamespace(time=lambda: self.now),
            "logger": self.log, "asyncio": types.SimpleNamespace(sleep=sleep),
            "CLEANUP_INTERVAL_SECONDS": 1, "UPLOAD_RETENTION_SECONDS": 100,
            "LOG_RETENTION_SECONDS": 100, "ACTIVE_LOG_FILENAMES": {"bot.log"},
            "_normalize_public_feed_storage": AsyncMock(return_value={"updated": 0, "failed": 0}),
            "_public_feed_protected_upload_paths": AsyncMock(return_value=set(protected)),
            "cleanup_saved_references": AsyncMock(return_value=0),
            "cleanup_orphaned_reference_files": AsyncMock(return_value={"removed_count": 0, "removed_bytes": 0}),
            "cleanup_stale_local_generation_tasks": AsyncMock(return_value={"failed_count": 0}),
        }
        tree = ast.parse((ROOT / "bot/main.py").read_text())
        nodes = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                 and node.name in {"_remove_old_files", "_cleanup_loop"}]
        self.assertEqual(len(nodes), 2)
        # Only two fixed functions: no main imports, database, or production state.
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "cleanup-functions", "exec"), namespace)  # noqa: S102
        with self.assertRaises(EndIteration):
            asyncio.run(namespace["_cleanup_loop"]())
        namespace["cleanup_saved_references"].assert_awaited_once()
        namespace["cleanup_orphaned_reference_files"].assert_awaited_once()
        return namespace

    def test_author_image_video_audio_and_empty_shards_survive_generic_ttl(self):
        assets = [self.file(f"static/uploads/trend-assets/{kind}/ab/fixture.{ext}")
                  for kind, ext in (("image", "png"), ("video", "mp4"), ("audio", "mp3"))]
        empty = Path("static/uploads/trend-assets/image/empty")
        empty.mkdir()
        self.run_iteration()
        self.assertTrue(all(path.is_file() for path in assets))
        self.assertTrue(empty.is_dir())

    def test_old_temporary_files_are_removed_and_recent_files_survive(self):
        old = self.file("static/uploads/temporary/old.png")
        recent = self.file("static/uploads/temporary/recent.png", old=False)
        similar = self.file("static/uploads/trend-assets-temporary/old.png")
        self.run_iteration()
        self.assertFalse(old.exists())
        self.assertFalse(similar.exists())
        self.assertTrue(recent.is_file())

    def test_existing_protected_roots_and_public_results_remain_protected(self):
        protected = [self.file(f"static/uploads/{directory}/nested/old.png")
                     for directory in ("refs", "feed", "wan3_prime")]
        published = self.file("static/uploads/published-old.png")
        self.run_iteration(protected=[str(published)])
        self.assertTrue(all(path.is_file() for path in protected))
        self.assertTrue(published.is_file())


if __name__ == "__main__":
    unittest.main()
