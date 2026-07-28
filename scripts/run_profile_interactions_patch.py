from pathlib import Path
import runpy


PATCH_PATH = Path("scripts/apply_profile_interactions.py")
WRAPPER_PATH = Path(__file__)


def main() -> None:
    source = PATCH_PATH.read_text(encoding="utf-8")
    old = '''    replace_once(
        path,
        \'\'\'        card = await get_feed_generation_card(
            gen_id,
            viewer_user_id=ctx["user"].id,
            include_unavailable=True,
        )\'\'\',
        \'\'\'        card = await get_profile_generation_card(
            gen_id,
            viewer_user_id=ctx["user"].id,
            include_unavailable=True,
        )\'\'\',
    )
'''
    new = '''    replace_once(
        path,
        \'\'\'async def miniapp_feed_item(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id") or body.get("feed_id")
        if not gen_id:
            return web.json_response({"ok": False, "error": "gen_id is required"}, status=400)

        telegram_id, ctx = await _get_user_context(
            request.app,
            init_data,
            body.get("start_param_fallback"),
        )
        card = await get_feed_generation_card(
            gen_id,
            viewer_user_id=ctx["user"].id,
            include_unavailable=True,
        )\'\'\',
        \'\'\'async def miniapp_feed_item(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id") or body.get("feed_id")
        if not gen_id:
            return web.json_response({"ok": False, "error": "gen_id is required"}, status=400)

        telegram_id, ctx = await _get_user_context(
            request.app,
            init_data,
            body.get("start_param_fallback"),
        )
        card = await get_profile_generation_card(
            gen_id,
            viewer_user_id=ctx["user"].id,
            include_unavailable=True,
        )\'\'\',
    )
'''
    if source.count(old) != 1:
        raise AssertionError(
            f"profile interaction patch invocation anchor count={source.count(old)}"
        )
    PATCH_PATH.write_text(source.replace(old, new, 1), encoding="utf-8")
    runpy.run_path(str(PATCH_PATH), run_name="__main__")
    WRAPPER_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
