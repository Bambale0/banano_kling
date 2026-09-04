from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_partner_offer_uses_full_local_document_before_legacy_handler() -> None:
    offer_source = (ROOT / "bot/handlers/public_offer_compat.py").read_text(encoding="utf-8")
    handlers_source = (ROOT / "bot/handlers/__init__.py").read_text(encoding="utf-8")

    assert '"partner_offer"' in offer_source
    assert "PUBLIC_OFFER_PDF_PATH" in offer_source
    assert "Публичная оферта · полный документ" in offer_source

    exact_offer = handlers_source.index("common_router.include_router(public_offer_compat_router)")
    legacy_common = handlers_source.index("common_router.include_router(legacy_common_router)")
    assert exact_offer < legacy_common
