import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
PDF_SIZE = 1_306_459
TEXT_SIZE = 67_744


def test_exact_public_offer_assets_are_bundled_server_side_only():
    pdf = (ROOT / "legal" / "public-offer.pdf").read_bytes()
    text_bytes = (ROOT / "legal" / "public-offer.txt").read_bytes()
    text = text_bytes.decode("utf-8")

    assert pdf.startswith(b"%PDF-")
    assert len(pdf) == PDF_SIZE
    assert len(text_bytes) == TEXT_SIZE
    assert "ПУБЛИЧНАЯ ОФЕРТА" in text
    assert "Дата вступления в силу «03» сентября 2026 г." in text
    assert "Самозанятый Турбанов Артем Валерьевич" in text

    assert (ROOT / "static" / "ofert.md").read_bytes() == text_bytes
    miniapp_legal = ROOT / "frontend" / "miniapp-v0" / "public" / "legal"
    assert not (miniapp_legal / "public-offer.pdf").exists()
    assert not (miniapp_legal / "public-offer.txt").exists()


def test_backend_offer_uses_only_local_resources():
    source = (
        ROOT / "bot" / "handlers" / "public_offer_compat.py"
    ).read_text(encoding="utf-8")

    assert "anketa.prodamus.ru" not in source
    assert "public-offer.txt" in source
    assert "public-offer.pdf" in source
    assert "Публичная оферта" in source


def test_miniapp_contains_no_public_offer_ui_or_assets():
    miniapp_root = ROOT / "frontend" / "miniapp-v0"
    shell_source = (miniapp_root / "components" / "mini-app-shell.tsx").read_text(
        encoding="utf-8"
    )
    workspace_source = (miniapp_root / "components" / "workspace-sheet.tsx").read_text(
        encoding="utf-8"
    )

    assert not (miniapp_root / "components" / "public-offer-access.tsx").exists()
    assert "PublicOfferAccess" not in shell_source
    assert "PublicOfferAccess" not in workspace_source
    assert "Публичная оферта" not in workspace_source
    assert "public-offer" not in workspace_source


def test_partner_offer_uses_full_local_document_before_legacy_handler():
    offer_source = (ROOT / "bot" / "handlers" / "public_offer_compat.py").read_text(
        encoding="utf-8"
    )
    handlers_source = (ROOT / "bot" / "handlers" / "__init__.py").read_text(
        encoding="utf-8"
    )
    legacy_source = (ROOT / "bot" / "handlers" / "common.py").read_text(
        encoding="utf-8"
    )

    assert '"partner_offer"' in offer_source
    assert "PUBLIC_OFFER_PDF_PATH" in offer_source
    assert "Публичная оферта · полный документ" in offer_source
    assert "Текст будет дополнен юристом" not in offer_source
    assert "Текст будет дополнен юристом" not in legacy_source

    exact_offer = handlers_source.index(
        "common_router.include_router(public_offer_compat_router)"
    )
    legacy_common = handlers_source.index(
        "common_router.include_router(legacy_common_router)"
    )
    assert exact_offer < legacy_common


def test_telegram_offer_is_exposed_in_more_and_removed_from_partner_ui():
    keyboards_source = (ROOT / "bot" / "keyboards.py").read_text(encoding="utf-8")
    offer_source = (
        ROOT / "bot" / "handlers" / "public_offer_compat.py"
    ).read_text(encoding="utf-8")
    partner_source = (
        ROOT / "bot" / "handlers" / "partner_approval.py"
    ).read_text(encoding="utf-8")

    more_keyboard = keyboards_source.split("def get_more_menu_keyboard():", 1)[1].split(
        "def get_admin_keyboard", 1
    )[0]
    partner_keyboards = keyboards_source.split(
        "def get_partner_program_keyboard", 1
    )[1].split("def get_settings_keyboard", 1)[0]
    preapproval_ui = partner_source.split("def _preapproval_keyboard", 1)[1].split(
        "async def _render_partner_entry", 1
    )[0]

    assert 'text="📜 Публичная оферта"' in more_keyboard
    assert 'callback_data="more_public_offer"' in more_keyboard
    assert '"more_public_offer"' in offer_source
    assert 'get_back_keyboard("ux_more")' in offer_source

    assert 'callback_data="partner_offer"' not in partner_keyboards
    assert "Публичная оферта" not in preapproval_ui


def test_telegram_offer_is_not_in_any_payment_keyboard():
    offer_source = (
        ROOT / "bot" / "handlers" / "public_offer_compat.py"
    ).read_text(encoding="utf-8")
    install_block = offer_source.split("def install_public_offer_compat", 1)[1].split(
        "async def _send_offer_text", 1
    )[0]

    assert '"get_payment_packages_keyboard"' not in install_block
    assert '"get_payment_method_keyboard"' not in install_block
    assert '"get_payment_confirmation_keyboard"' not in install_block
