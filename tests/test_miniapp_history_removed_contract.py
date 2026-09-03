from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINIAPP_COMPONENTS = ROOT / "frontend" / "miniapp-v0" / "components"


def test_studio_has_no_generation_history_gallery() -> None:
    studio = (MINIAPP_COMPONENTS / "tabs" / "studio-tab.tsx").read_text(encoding="utf-8")

    assert "TaskHistoryList" not in studio
    assert "Ваши работы" not in studio
    assert "Готовые работы остаются в чате с ботом" in studio
    assert not (MINIAPP_COMPONENTS / "task-history-list.tsx").exists()
    assert not (MINIAPP_COMPONENTS / "task-card.tsx").exists()


def test_upload_area_only_shows_current_generation_files() -> None:
    upload_area = (MINIAPP_COMPONENTS / "forms" / "upload-area.tsx").read_text(encoding="utf-8")

    assert "availableLibraryFiles" not in upload_area
    assert "handleAddFromLibrary" not in upload_area
    assert "Можно добавить без повторной загрузки" not in upload_area
    assert "files.map((file)" in upload_area
    assert "onUpload" in upload_area
