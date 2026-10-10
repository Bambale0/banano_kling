"""Actual final permission fence with synthetic source rows; no app bootstrap."""
import ast
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[2]


class Conflict(ValueError):
    pass


class RepeatClaimTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tree = ast.parse((ROOT / "bot/services/seedance_quote_authorization.py").read_text())
        node = next(node for node in tree.body if isinstance(node,ast.AsyncFunctionDef))
        node.body = [part for part in node.body if not isinstance(part,ast.ImportFrom)]
        ns = {"json":json,"QuoteConflict":Conflict,"database":SimpleNamespace(_generation_identifier_clause=lambda value:("id = ?",value)),
              "db_backend":SimpleNamespace(is_postgres=lambda:True),"_video_repeat_snapshot":lambda current:current["revision"]}
        exec(compile(ast.Module(body=[node],type_ignores=[]),"actual_permission_fence","exec"),ns)  # noqa: S102
        self.verify = ns["verify_repeat_claim"]
        self.source = {"type":"video","status":"completed","is_public_feed":1,"is_profile_visible":0,"is_adult_content":0,"revision":"original"}
        self.cursor = SimpleNamespace(fetchone=AsyncMock(side_effect=lambda:dict(self.source)))
        self.db = SimpleNamespace(execute=AsyncMock(return_value=self.cursor))
        self.row = {"user_id":2,"original_json":json.dumps({"_repeat_guard":{"viewer_user_id":2,"source_id":42,"snapshot":"original"}})}

    async def test_valid_permission_locks_source_until_claim_commit(self):
        await self.verify(self.db,self.row)
        sql, params = self.db.execute.await_args.args
        self.assertTrue(sql.endswith(" FOR UPDATE"))
        self.assertEqual(params,(42,))

    async def test_withdrawn_or_revised_source_fails_closed(self):
        for changes in ({"is_public_feed":0},{"revision":"withdrawn"},{"status":"failed"},{"is_adult_content":1}):
            original = dict(self.source)
            self.source.update(changes)
            with self.assertRaises(Conflict):
                await self.verify(self.db,self.row)
            self.source = original

    async def test_actor_mismatch_never_reads_source(self):
        self.row["user_id"] = 3
        with self.assertRaises(Conflict):
            await self.verify(self.db,self.row)
        self.db.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
