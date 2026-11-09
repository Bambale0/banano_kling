from pathlib import Path

import pytest

from bot import legal_documents
from bot.keyboards import (
    get_legal_documents_keyboard,
    get_more_menu_keyboard,
    get_partner_program_keyboard,
    get_payment_confirmation_keyboard,
    get_payment_method_keyboard,
    get_payment_packages_keyboard,
)


def _callbacks(markup) -> set[str]:
    return {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    }


def test_public_legal_entry_exists_in_more_menu():
    assert "legal_documents" in _callbacks(get_more_menu_keyboard())


def test_public_legal_entry_exists_before_payment():
    assert "legal_documents" in _callbacks(get_payment_packages_keyboard([]))
    assert "legal_documents" in _callbacks(get_payment_method_keyboard("test"))
    assert "legal_documents" in _callbacks(
        get_payment_confirmation_keyboard("https://example.org/pay", "order_1")
    )


def test_public_legal_entry_exists_in_partner_screen():
    assert "legal_documents" in _callbacks(get_partner_program_keyboard(""))


def test_both_documents_have_separate_routes():
    assert {"partner_offer", "privacy_policy"} <= _callbacks(
        get_legal_documents_keyboard()
    )


def test_legal_text_preserved_and_under_telegram_utf16_limit():
    text = ("Условия 🎬 обработки файлов\n" * 550).strip()
    parts = legal_documents.telegram_text_parts(text)
    assert len(parts) > 1
    assert "".join(parts) == text
    assert all(len(part.encode("utf-16-le")) // 2 <= 3800 for part in parts)


def test_empty_legal_text_is_not_sent():
    assert legal_documents.telegram_text_parts(" \n\t ") == []


def test_tiny_limit_rejected():
    with pytest.raises(ValueError):
        legal_documents.telegram_text_parts("abc", max_utf16_units=1)


@pytest.mark.parametrize(
    "candidate",
    [
        "",
        "http://example.org/offer",
        "javascript:alert(1)",
        "https://",
        "https://[invalid",
        "https://admin:password@example.org/policy",
        "file:///tmp/legal.txt",
    ],
)
def test_non_https_or_unsafe_legal_link_rejected(candidate):
    assert legal_documents.https_document_url(candidate) is None


def test_public_https_link_accepted():
    assert legal_documents.https_document_url("https://example.org/legal/privacy") == (
        "https://example.org/legal/privacy"
    )


def test_document_text_reads_utf8_and_rejects_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(legal_documents, "_DOCUMENT_ROOT", tmp_path)
    (tmp_path / "ofert.md").write_text("Публичная оферта", encoding="utf-8")
    (tmp_path / "privacy_policy.md").write_text("  ", encoding="utf-8")

    assert legal_documents.document_text("offer") == "Публичная оферта"
    with pytest.raises(ValueError, match="Empty legal document"):
        legal_documents.document_text("privacy")
