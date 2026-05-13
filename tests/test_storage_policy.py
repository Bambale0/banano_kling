from pathlib import Path

from bot.services.storage_policy import choose_upload_category, public_upload_url, upload_path


def test_upload_path_separates_reference_and_result_categories(tmp_path):
    ref_path = upload_path(tmp_path, "temp_refs", "20260513", "a.jpg")
    result_path = upload_path(tmp_path, "results", "20260513", "b.png")

    assert ref_path == tmp_path / "temp_refs" / "20260513" / "a.jpg"
    assert result_path == tmp_path / "results" / "20260513" / "b.png"


def test_public_upload_url_preserves_uploads_prefix():
    assert public_upload_url("https://example.test", "results", "20260513", "x.png") == (
        "https://example.test/uploads/results/20260513/x.png"
    )


def test_choose_upload_category_by_extension_and_reference_flag():
    assert choose_upload_category("jpg", is_reference=True) == "temp_refs"
    assert choose_upload_category("mp4", is_reference=True) == "user_uploads"
    assert choose_upload_category("png", is_reference=False) == "results"
