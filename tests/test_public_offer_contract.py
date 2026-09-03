from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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
