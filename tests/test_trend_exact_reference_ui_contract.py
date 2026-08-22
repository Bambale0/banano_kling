from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_admin_can_save_exact_reference_count_and_order_hint():
    source = _read("frontend/miniapp-v0/components/tabs/trends-tab.tsx")
    assert "requiredReferenceCount" in source
    assert "required_reference_count: requiredReferenceCount" in source
    assert "reference_hint: referenceHint.trim()" in source
    assert "Сколько фото нужно" in source
    assert "Порядок фото для пользователя" in source


def test_runner_requires_complete_exact_reference_set_before_generate():
    source = _read("frontend/miniapp-v0/components/trend-runner-dialog.tsx")
    assert "required_reference_count" in source
    assert "uploadedReferences.length === exactReferenceCount" in source
    assert "disabled={busy || !hasEnoughReferences}" in source
    assert "removeReference" in source


def test_backend_enforces_exact_reference_count():
    source = _read("bot/trend_api.py")
    assert "_required_reference_count" in source
    assert "len(reference_urls) != required_count" in source
    assert "ровно {required_count} фото" in source
