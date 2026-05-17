import pytest
from aiohttp import web

from bot.catalog_webapp import _build_trusted_order, _format_order_text


PRODUCTS = [
    {
        "id": "111",
        "wbArticle": "111",
        "sellerArticle": "ICE-111",
        "name": "Ice Loop Set",
        "category": "Аксессуары",
        "price": 1200,
        "currentPrice": 1500,
        "stockTotal": 5,
        "available": True,
        "imageUrl": "/static/item.jpg",
        "wbUrl": "https://example.test/111",
    }
]


def test_catalog_order_uses_server_catalog_price_and_total():
    order = _build_trusted_order(
        {
            "items": [{"wbArticle": "111", "qty": 2, "price": 1}],
            "delivery": {"method": "cdek", "city": "Москва", "address": "Лёд 1", "price": 999},
            "total": 2,
        },
        PRODUCTS,
    )

    assert order["items"][0]["price"] == 1200
    assert order["items"][0]["total"] == 2400
    assert order["subtotal"] == 2400
    assert order["delivery"]["price"] == 350
    assert order["total"] == 2750


def test_catalog_order_rejects_unknown_product():
    with pytest.raises(web.HTTPBadRequest):
        _build_trusted_order(
            {"items": [{"wbArticle": "999", "qty": 1}], "delivery": {}},
            PRODUCTS,
        )


def test_order_notification_html_escapes_user_content():
    text = _format_order_text(
        "SHOP-1",
        {
            "items": [{"name": "<b>hack</b>", "wbArticle": "111&222", "qty": 1, "price": 1200}],
            "total": 1200,
            "promoCode": "<PROMO>",
            "customer": {"name": "<script>alert(1)</script>", "phone": "+7&1"},
            "delivery": {"city": "<Moscow>", "address": "Ice & rink", "method": "cdek"},
        },
    )

    assert "<script>" not in text
    assert "<b>hack</b>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "&lt;b&gt;hack&lt;/b&gt;" in text
    assert "111&amp;222" in text
