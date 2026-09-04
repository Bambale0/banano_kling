import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
PDF_SIZE = 1_306_459
TEXT_SIZE = 67_744


def test_exact_public_offer_assets_are_bundled_everywhere():
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
    assert (
        ROOT / "frontend" / "miniapp-v0" / "public" / "legal" / "public-offer.pdf"
    ).read_bytes() == pdf
    assert (
        ROOT / "frontend" / "miniapp-v0" / "public" / "legal" / "public-offer.txt"
    ).read_bytes() == text_bytes


def test_product_code_uses_only_local_offer_resources():
    paths = [
        ROOT / "bot" / "handlers" / "public_offer_compat.py",
        ROOT / "frontend" / "miniapp-v0" / "components" / "public-offer-access.tsx",
        ROOT / "frontend" / "miniapp-v0" / "components" / "mini-app-shell.tsx",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "anketa.prodamus.ru" not in source
    assert "public-offer.txt" in source
    assert "public-offer.pdf" in source
    assert "Публичная оферта" in source


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
