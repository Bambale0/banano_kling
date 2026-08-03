from pathlib import Path


def test_mobile_media_upload_contract() -> None:
    miniapp = Path("bot/miniapp.py").read_text(encoding="utf-8")
    api = Path("frontend/miniapp-v0/lib/api.ts").read_text(encoding="utf-8")
    upload_area = Path(
        "frontend/miniapp-v0/components/forms/upload-area.tsx"
    ).read_text(encoding="utf-8")
    workspace = Path(
        "frontend/miniapp-v0/components/workspace-sheet.tsx"
    ).read_text(encoding="utf-8")
    trends = Path(
        "frontend/miniapp-v0/components/tabs/trends-tab.tsx"
    ).read_text(encoding="utf-8")
    photo_service = Path(
        "bot/services/photo_prompt_service.py"
    ).read_text(encoding="utf-8")

    assert "MINIAPP_UPLOAD_TIMEOUT_SECONDS = 900" in miniapp
    assert "timeout=MINIAPP_UPLOAD_TIMEOUT_SECONDS" in miniapp
    assert "_normalize_miniapp_upload_content_type" in miniapp
    assert "application/octet-stream" in miniapp
    assert "MEDIA_UPLOAD_TIMEOUT_MS = 900_000" in api
    assert "normalizedMediaUploadFile" in api
    assert "controller.abort()" in api
    assert "globalThis.clearTimeout(timeoutId)" in api
    assert "filesRef.current" in upload_area
    assert "photoUploadAttemptRef" in workspace
    assert "setPreviewUrl(uploaded.url)" in workspace
    assert "URL.revokeObjectURL(localPreviewUrl)" in workspace
    assert "previewUploadAttemptRef" in trends
    assert "URL.revokeObjectURL(localPreviewUrl)" in trends
    assert "image_source_to_analysis_input" in photo_service
    assert "_build_claude_image_source" in photo_service
