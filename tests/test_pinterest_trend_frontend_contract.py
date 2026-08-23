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
        "Загрузить",
        "Рост",
        "Вес",
        "Создать →",
        "runPinterestRepeatTrend",
        "сцена, свет и поза считаются с референса",
        "лицо и внешность берутся только с твоего фото",
    ):
        assert expected in runner

    # The Pinterest URL shortcut is removed: only device uploads are allowed,
    # because external image hosts block provider-side fetches.
    assert "resolvePinterestReference" not in runner
    assert "Ссылка на пин с Pinterest" not in runner

    assert "pinterestRepeat\n        ? await runPinterestRepeatTrend" in runner
    assert "heightCm: parseOptionalNumber(heightCm)" in runner
    assert "weightKg: parseOptionalNumber(weightKg)" in runner
    assert "completedReferences.length === exactReferenceCount" in runner
    assert "disabled={busy || !readyToGenerate}" in runner


def test_height_and_weight_reach_backend_payload():
    client = read("frontend/miniapp-v0/lib/trend-api.ts")
    backend = read("bot/pinterest_trend_api.py")

    assert "payload.height_cm = options.heightCm" in client
    assert "payload.weight_kg = options.weightKg" in client
    assert '_measurement(body, "height_cm", minimum=120, maximum=230)' in backend
    assert '_measurement(body, "weight_kg", minimum=30, maximum=250)' in backend
    assert "height_cm=height_cm" in backend
    assert "weight_kg=weight_kg" in backend


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
        '"model": "banana_pro"',
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


def test_trends_showcase_excludes_pinterest_ai_launch():
    trends_tab = read("frontend/miniapp-v0/components/tabs/trends-tab.tsx")
    services_tab = read("frontend/miniapp-v0/components/tabs/services-tab.tsx")

    # Trends grid filters Pinterest prompts out entirely; Services is the only
    # entry point and renders the existing TrendRunnerDialog directly.
    assert "hasTrendTag(trend) && !isPinterestRepeatTrend(trend)" in trends_tab
    assert "'pinterest-ai'" in services_tab
    assert "setPinterestTrend(trend)" in services_tab
    assert "<TrendRunnerDialog" in services_tab


def test_runtime_lock_prevents_database_drift_from_changing_model_or_quality():
    backend = read("bot/pinterest_trend_api.py")

    assert 'model="banana_pro"' in backend
    # Ratio is only a configured default: at runtime it is matched to the
    # scene reference aspect so a 3:4 source stays 3:4.
    assert '"ratio": "9:16"' in backend
    assert 'ratio = str(locked_settings.get("ratio") or trusted.ratio)' in backend
    assert '_scene_matched_ratio(' in backend
    assert "locked_settings = dict(_PINTEREST_TOOL_SETTINGS)" in backend
    assert "await _lock_pinterest_run(" in backend
