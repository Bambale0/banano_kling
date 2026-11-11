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


def test_exact_whitespace_is_preserved_in_full_legal_text():
    source = "   Публичная оферта 👩‍💻\\n\\n"
    assert "".join(legal_documents.telegram_text_parts(source)) == source


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


@pytest.mark.parametrize(
    "callback_data",
    ["public_offer", "more_public_offer", "partner_offer", "payment_public_offer"],
)
@pytest.mark.asyncio
async def test_offer_callbacks_send_pdf_attachment_even_if_url_configured(
    callback_data, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiogram.types import FSInputFile

    from bot.handlers import public_offer_compat as offer

    monkeypatch.setattr(
        offer.config, "PARTNER_OFFER_URL", "https://example.org/legal/offer"
    )
    message = SimpleNamespace(answer=AsyncMock(), answer_document=AsyncMock())
    callback = SimpleNamespace(
        data=callback_data, message=message, answer=AsyncMock()
    )

    await offer.show_public_offer(callback)

    message.answer.assert_not_awaited()
    message.answer_document.assert_awaited_once()
    document = message.answer_document.await_args.args[0]
    assert isinstance(document, FSInputFile)
    assert document.path.name == "public-offer.pdf"
    assert message.answer_document.await_args.kwargs["caption"] == "📜 Публичная оферта"
    callback.answer.assert_awaited_once()



def test_actual_offer_handler_precedes_legacy_router():
    from bot.handlers import common_router, public_offer_compat_router

    # A regression in router order would route legacy PDF handlers first.
    routers = common_router.sub_routers
    assert public_offer_compat_router in routers
    assert routers.index(public_offer_compat_router) < next(
        index for index, child in enumerate(routers)
        if any(
            handler.callback.__module__ == "bot.handlers.common"
            for handler in child.callback_query.handlers
        )
    )


@pytest.mark.asyncio
async def test_privacy_policy_is_attached_as_file_even_if_url_configured(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiogram.types import BufferedInputFile

    from bot.handlers import common

    monkeypatch.setattr(
        common.config, "PRIVACY_POLICY_URL", "https://example.org/legal/privacy"
    )
    message = SimpleNamespace(answer=AsyncMock(), answer_document=AsyncMock())
    callback = SimpleNamespace(message=message, answer=AsyncMock())

    await common.show_privacy_policy(callback)

    message.answer.assert_not_awaited()
    message.answer_document.assert_awaited_once()
    attachment = message.answer_document.await_args.args[0]
    assert isinstance(attachment, BufferedInputFile)
    assert attachment.filename == "privacy-policy.txt"
    assert attachment.data == legal_documents.document_text("privacy").encode("utf-8")
    callback.answer.assert_awaited_once()


def test_legal_document_attachment_offer_fails_closed_on_invalid_pdf(tmp_path, monkeypatch):
    path = tmp_path / "public-offer.pdf"
    path.write_text("not a pdf", encoding="utf-8")
    monkeypatch.setattr(legal_documents, "_OFFER_PDF_PATH", path)
    with pytest.raises(ValueError, match="PDF"):
        legal_documents.legal_document_attachment("offer")


@pytest.mark.asyncio
async def test_unpublished_policy_fails_closed_without_fake_document(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot.handlers import common

    monkeypatch.setattr(common.config, "PRIVACY_POLICY_URL", "")

    def missing_policy(_kind):
        raise FileNotFoundError("privacy_policy.md")

    monkeypatch.setattr(common, "legal_document_attachment", missing_policy)
    message = SimpleNamespace(answer=AsyncMock(), answer_document=AsyncMock())
    callback = SimpleNamespace(message=message, answer=AsyncMock())

    await common.show_privacy_policy(callback)

    message.answer.assert_not_awaited()
    message.answer_document.assert_not_awaited()
    assert callback.answer.await_args.kwargs["show_alert"] is True


@pytest.mark.asyncio
async def test_opening_legal_documents_preserves_checkout_message():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot.handlers import common

    message = SimpleNamespace(answer=AsyncMock(), edit_text=AsyncMock())
    callback = SimpleNamespace(message=message, answer=AsyncMock())

    await common.show_legal_documents(callback)

    message.edit_text.assert_not_awaited()
    message.answer.assert_awaited_once()
    assert "Юридические документы" in message.answer.await_args.args[0]
    assert "partner_offer" in _callbacks(
        message.answer.await_args.kwargs["reply_markup"]
    )
    assert "privacy_policy" in _callbacks(
        message.answer.await_args.kwargs["reply_markup"]
    )


@pytest.mark.asyncio
async def test_multi_part_legal_text_is_paced_with_markup_only_on_last(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    fake_sleep = AsyncMock()
    monkeypatch.setattr(legal_documents.asyncio, "sleep", fake_sleep)
    message = SimpleNamespace(answer=AsyncMock())
    markup = object()
    await legal_documents.send_legal_parts(message, ["часть 1", "часть 2", "конец"], markup)

    assert message.answer.await_count == 3
    fake_sleep.assert_any_await(1.1)
    assert fake_sleep.await_count == 2
    assert message.answer.await_args_list[0].kwargs["reply_markup"] is None
    assert message.answer.await_args_list[1].kwargs["reply_markup"] is None
    assert message.answer.await_args_list[2].kwargs["reply_markup"] is markup
    assert all(c.kwargs["parse_mode"] is None for c in message.answer.await_args_list)


@pytest.mark.asyncio
async def test_telegram_retry_after_retries_same_part_once(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    class FakeRetryAfter(Exception):
        retry_after = 0.5

    calls = []

    async def answer(text, **kwargs):
        calls.append((text, kwargs))
        if len(calls) == 1:
            raise FakeRetryAfter()

    fake_sleep = AsyncMock()
    monkeypatch.setattr(legal_documents, "TelegramRetryAfter", FakeRetryAfter)
    monkeypatch.setattr(legal_documents.asyncio, "sleep", fake_sleep)

    await legal_documents.send_legal_parts(
        SimpleNamespace(answer=answer), ["полный документ"], None
    )
    assert len(calls) == 2
    assert calls[0][0] == calls[1][0] == "полный документ"
    fake_sleep.assert_awaited_once_with(0.7)


@pytest.mark.asyncio
async def test_offer_callback_acknowledges_before_attachment(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot.handlers import public_offer_compat as offer

    monkeypatch.setattr(offer.config, "PARTNER_OFFER_URL", "")
    order = []

    async def on_ack(*args, **kwargs):
        order.append("ack")

    async def on_send_document(*args, **kwargs):
        order.append("send_document")

    callback = SimpleNamespace(
        data="more_public_offer",
        message=SimpleNamespace(
            answer=AsyncMock(), answer_document=AsyncMock(side_effect=on_send_document)
        ),
        answer=AsyncMock(side_effect=on_ack),
    )
    await offer.show_public_offer(callback)
    assert order == ["ack", "send_document"]
