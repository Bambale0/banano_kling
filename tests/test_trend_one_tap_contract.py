from __future__ import annotations

import sqlite3
from pathlib import Path

from bot.database import _row_optional_value

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_trend_settings_are_persisted_as_structured_json() -> None:
    database = read("bot/database.py")
    miniapp = read("bot/miniapp.py")

    assert "generation_settings TEXT DEFAULT '{}'" in database
    assert '"generation_settings": prompt.generation_settings or {}' in database
    assert "generation_settings=generation_settings" in miniapp
    assert "if not config.is_admin(telegram_id):" in miniapp


def test_trend_runner_only_uploads_references_and_autostarts() -> None:
    runner = read("frontend/miniapp-v0/components/trend-runner-dialog.tsx")

    assert 'type="file"' in runner
    assert "multiple" in runner
    assert "Array.from(event.currentTarget.files || [])" in runner
    assert "event.currentTarget.value = ''" in runner
    assert "void handlePhotos(files)" in runner
    assert "await Promise.all(" in runner
    assert "uploadFile('image_reference', file)" in runner
    assert "await runTrend(" in runner

    for forbidden in (
        "resolveTrendSettings",
        "generateImage",
        "generateVideo",
        "ModelSelect",
        "RatioSelect",
        "QualitySelect",
        "ScenarioSelect",
        "DurationSelect",
    ):
        assert forbidden not in runner


def test_trend_client_sends_no_generation_settings() -> None:
    trend_api = read("frontend/miniapp-v0/lib/trend-api.ts")

    assert "trend_id: trendId" in trend_api
    assert "reference_urls: referenceUrls.map(providerReferenceUrl)" in trend_api
    assert "model:" not in trend_api.split("const payload", 1)[1].split(
        "const startParam", 1
    )[0]
    assert "generation_settings" not in trend_api


def test_backend_loads_trusted_trend_settings_by_id() -> None:
    backend = read("bot/trend_api.py")
    routes = read("bot/browser_auth.py")

    assert 'body.get("trend_id")' in backend
    assert 'body.get("reference_urls")' in backend
    assert "get_prompt_by_id(" in backend
    assert "trusted_trend_run(prompt, parsed.reference_urls)" in backend
    assert 'settings.get("model")' in backend
    assert 'trend.get("prompt_text")' in backend
    assert "setup_trend_routes(app, miniapp_root)" in routes

    for forbidden_client_field in (
        'body.get("model")',
        'body.get("prompt")',
        'body.get("ratio")',
        'body.get("quality")',
        'body.get("duration")',
        'body.get("generation_settings")',
    ):
        assert forbidden_client_field not in backend


def test_trend_card_and_deep_link_open_the_same_runner() -> None:
    trends = read("frontend/miniapp-v0/components/tabs/trends-tab.tsx")
    context = read("frontend/miniapp-v0/lib/app-context.tsx")

    assert "setTrendToRun(trend)" in trends
    assert "trend={trendToRun}" in trends
    assert "setTrendToRun(prompt)" in context
    assert "setActiveTabState(5)" in context


def test_admin_snapshot_contains_every_generation_parameter_used_by_backend() -> None:
    trends = read("frontend/miniapp-v0/components/tabs/trends-tab.tsx")
    backend = read("bot/trend_api.py")

    for key in (
        "model",
        "ratio",
        "quality",
        "count",
        "scenario",
        "duration",
        "grok_mode",
        "grok_resolution",
        "veo_generation_type",
        "veo_translation",
        "veo_resolution",
        "veo_seed",
        "veo_watermark",
        "kling_negative_prompt",
        "kling_cfg_scale",
        "omni_resolution",
        "omni_seed",
        "omni_audio_ids",
        "omni_character_ids",
        "omni_base_voice",
        "omni_voice_name",
        "omni_voice_description",
        "omni_example_dialogue",
        "omni_character_name",
        "omni_character_audio_ids",
    ):
        assert key in trends
        assert key in backend or key in {"count", "quality"}

    assert "trend-scenario:" not in trends
    assert "trend-duration:" not in trends


def test_sqlite_row_reads_structured_trend_settings() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT ? AS generation_settings",
            ('{"ratio":"9:16"}',),
        ).fetchone()
        assert row is not None
        assert _row_optional_value(row, "generation_settings") == '{"ratio":"9:16"}'
        assert _row_optional_value(row, "missing") is None
    finally:
        connection.close()
