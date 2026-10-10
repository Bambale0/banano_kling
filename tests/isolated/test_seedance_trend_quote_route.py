"""Selected HTTP handler seams with injected auth/catalog; no application imports."""
import ast
import logging
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[2]


class RemoveAppImports(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        return None if (node.module or "").startswith("bot") else node


def selected(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text())
    node = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == name)
    node = RemoveAppImports().visit(node)
    node.decorator_list = []
    node.returns = None
    for arg in [*node.args.args, *node.args.kwonlyargs]:
        arg.annotation = None
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), path, "exec"), namespace)  # noqa: S102
    return namespace[name]


class TrendQuoteRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_quote_http_authorizes_but_never_reserves_legacy_claim(self):
        for model in ("seedance_2", "seedance_2_5"):
            body = {"trend_id":42, "video_quote_only":True, "client_request_id":"synthetic", "init_data":"synthetic"}
            request = SimpleNamespace(json=AsyncMock(return_value=body), app={})
            parsed = SimpleNamespace(trend_id=42, reference_urls=("user-image",), user_values={}, reference_inputs=(), client_request_id="synthetic")
            trend = SimpleNamespace(kind="video", model=model, provider_video_urls=("fixed-hidden", "user-video"), reference_contract="", trend_id=42)
            user = SimpleNamespace(id=1)
            run = AsyncMock(return_value={"ok":True,"quote_id":"quote","cost":48})
            reserve = AsyncMock()
            ns = {"Mapping":Mapping,"Sequence":Sequence,"Any":Any,"logger":logging.getLogger(__name__),
                  "parse_trend_run_request":lambda _, parsed=parsed:parsed,
                  "miniapp_module":SimpleNamespace(_get_user_context=AsyncMock(return_value=(5000000001,{"user":user}))),
                  "get_prompt_by_id":AsyncMock(return_value={"model":model,"generation_settings":{}}),
                  "trusted_trend_run":lambda *_args, trend=trend, **_kwargs:trend,"REFERENCE_CONTRACT":"private",
                  "_run_video_trend":run,"reserve_trend_run_claim":reserve,"TrendRunValidationError":ValueError,
                  "web":SimpleNamespace(json_response=lambda payload, **_:payload)}
            handler = selected("bot/trend_api.py","miniapp_run_trend",ns)
            self.assertEqual((await handler(request))["cost"],48)
            ns["get_prompt_by_id"].assert_awaited_once_with(42,approved_public_only=True)
            run.assert_awaited_once_with(telegram_id=5000000001,user=user,trend=trend,quote_context=body)
            reserve.assert_not_awaited()

    async def test_actual_seedance2_trend_accepts_quote_context_before_legacy_debit(self):
        context = {"video_quote_only":True}
        trend = SimpleNamespace(model="seedance_2",settings={"scenario":"imgtxt","duration":5},ratio="16:9",
            reference_contract="private",provider_image_urls=("image",),provider_video_urls=("video",),
            provider_audio_urls=(),user_reference_inputs=(),reference_urls=("image",))
        measured = AsyncMock(return_value={"quote_id":"q"})
        debit = AsyncMock()
        ns = {"REFERENCE_CONTRACT":"private","TrendRunValidationError":ValueError,
              "miniapp_module":SimpleNamespace(_find_video_model_meta=lambda _: {"ratios":["16:9"],"durations":[5]},
                  _resolve_gemini_omni_model=lambda model,_:model),
              "_int_setting":lambda settings,key,default:settings.get(key,default),
              "get_max_video_image_references":lambda _:9,"get_max_video_references":lambda _:3,"get_max_audio_references":lambda _:3,
              "_validate_uploaded_references":lambda *_:None,"touch_saved_references":AsyncMock(),
              "run_measured_trend_seedance2":measured,"_debit_for_generation":debit}
        handler = selected("bot/trend_api.py","_run_video_trend",ns)
        self.assertEqual(await handler(telegram_id=1,user=object(),trend=trend,quote_context=context),{"quote_id":"q"})
        measured.assert_awaited_once_with(1,trend,5,"video",context)
        debit.assert_not_awaited()

    async def test_both_compat_signatures_forward_quote_context(self):
        tree = ast.parse((ROOT / "bot/handlers/trend_seedance_25_compat.py").read_text())
        for name in ("_run_seedance25_trend","run_video_trend_with_seedance25"):
            node = next(node for node in ast.walk(tree) if isinstance(node,ast.AsyncFunctionDef) and node.name == name)
            self.assertIn("quote_context",[arg.arg for arg in node.args.kwonlyargs])
        source = (ROOT / "bot/handlers/trend_seedance_25_compat.py").read_text()
        self.assertLess(source.index("return await run_measured_trend_seedance25"),source.index("debited, debit_error"))


if __name__ == "__main__":
    unittest.main()
