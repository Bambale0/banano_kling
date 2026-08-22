from pathlib import Path

from bot import pinterest_trend_catalog, trend_preview_admin, trend_visibility


ROOT = Path(__file__).resolve().parents[1]


def test_preview_kind_supports_photo_or_video_independent_of_trend_kind():
    assert trend_preview_admin._validate_preview_kind("image", "/uploads/demo.jpg") == "image"
    assert trend_preview_admin._validate_preview_kind("video", "/uploads/demo.mp4") == "video"
    assert trend_preview_admin._validate_preview_kind("", "/uploads/demo.webm") == "video"
    assert trend_preview_admin._validate_preview_kind("", "/uploads/demo.webp") == "image"


def test_preview_url_rejects_browser_local_values():
    assert trend_preview_admin._validate_preview_url("/uploads/trends/demo.mp4") == "/uploads/trends/demo.mp4"
    for value in ("blob:https://example.test/1", "data:video/mp4;base64,AA", "file:///tmp/a.mp4"):
        try:
            trend_preview_admin._validate_preview_url(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"local preview URL must be rejected: {value}")


def test_pinterest_catalog_preserves_admin_selected_preview_type():
    video = pinterest_trend_catalog._settings_with_preserved_preview_type(
        '{"preview_type":"video","quality":"1K"}'
    )
    image = pinterest_trend_catalog._settings_with_preserved_preview_type(
        {"preview_type": "image"}
    )

    assert video["preview_type"] == "video"
    assert image["preview_type"] == "image"
    # Locked product settings must still win over stale stored values.
    assert video["quality"] == "2K"
    assert video["model"] == "banana_pro"
    assert video["reference_count"] == 2


def test_public_trend_payload_keeps_preview_type_without_exposing_recipe():
    settings = trend_visibility.public_trend_settings(
        {
            "category": "photo",
            "tags": ["trend"],
            "generation_settings": {
                "kind": "image",
                "ratio": "9:16",
                "preview_type": "video",
                "model": "banana_pro",
                "quality": "2K",
            },
        }
    )
    assert settings == {"kind": "image", "ratio": "9:16", "preview_type": "video"}
    assert "model" not in settings
    assert "quality" not in settings


def test_admin_preview_route_is_registered_before_miniapp_catchall():
    source = (ROOT / "bot/handlers/trend_route_compat.py").read_text(encoding="utf-8")
    assert "setup_trend_preview_admin_routes(app, root)" in source
    assert source.index("setup_trend_preview_admin_routes(app, root)") < source.index("current_setup(app)")
    assert "while _ensure_pinterest_tool in app.on_startup" in source


def test_frontend_supports_promo_video_for_photo_trends_and_existing_cards():
    source = (ROOT / "frontend/miniapp-v0/components/tabs/trends-tab.tsx").read_text(encoding="utf-8")
    types_source = (ROOT / "frontend/miniapp-v0/lib/types.ts").read_text(encoding="utf-8")

    assert "type TrendPreviewKind" in source
    assert "preview_type: previewKind" in source
    assert "Фото-тренд может иметь видео-инструкцию" in source
    assert "updateTrendPreview(trend.id, uploaded.url, detectedKind)" in source
    assert "Промо-видео" in source
    assert "autoPlay" in source
    assert "muted" in source
    assert "loop" in source
    assert "playsInline" in source
    assert "preview_type?: 'image' | 'video'" in types_source


def test_telegram_trends_render_video_previews_as_video():
    source = (ROOT / "bot/handlers/trends_compat.py").read_text(encoding="utf-8")
    assert "InputMediaVideo" in source
    assert "message.answer_video" in source
    assert "_trend_preview_kind" in source
