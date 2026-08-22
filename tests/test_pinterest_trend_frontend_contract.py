from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_pinterest_repeat_matches_reference_video_flow():
    runner = read("frontend/miniapp-v0/components/trend-runner-dialog.tsx")

    for expected in (
        "Повтори фото с Pinterest",
        "РЕФЕРЕНС",
        "ТЫ",
        "или вставь ссылку",
        "Ссылка на пин с Pinterest",
        "Загрузить",
        "Рост",
        "Вес",
        "Создать →",
        "resolvePinterestReference",
        "runPinterestRepeatTrend",
        "сцена, свет и поза считаются с референса",
        "лицо и внешность берутся только с твоего фото",
    ):
        assert expected in runner

    assert "pinterestRepeat\n        ? await runPinterestRepeatTrend" in runner
    assert "completedReferences.length === exactReferenceCount" in runner
    assert "disabled={busy || !readyToGenerate}" in runner


def test_uploading_a_reference_does_not_auto_start_generation():
    runner = read("frontend/miniapp-v0/components/trend-runner-dialog.tsx")
    upload_body = runner.split("const uploadIntoSlot", 1)[1].split(
        "const handlePhotos", 1
    )[0]

    assert "uploadFile('image_reference', file)" in upload_body
    assert "handleGenerate" not in upload_body
    assert "runPinterestRepeatTrend" not in upload_body
    assert "runTrend(" not in upload_body


def test_pinterest_routes_are_registered_before_miniapp_catchall():
    routes = read("bot/handlers/trend_route_compat.py")

    assert "setup_pinterest_trend_routes(app, root)" in routes
    assert routes.index("setup_pinterest_trend_routes(app, root)") < routes.index(
        "current_setup(app)"
    )


def test_system_pinterest_trend_is_seeded_idempotently():
    backend = read("bot/pinterest_trend_api.py")

    for expected in (
        '_PINTEREST_TOOL_TITLE = "Повтори фото с Pinterest"',
        '"reference_count": 2',
        '"reference_labels": ["РЕФЕРЕНС", "ТЫ"]',
        '"ratio": "9:16"',
        '"quality": "2K"',
        '"pinterest-repeat"',
        "SELECT id",
        "UPDATE user_prompts",
        "INSERT INTO user_prompts",
        "app.on_startup.append(_ensure_pinterest_tool)",
    ):
        assert expected in backend
