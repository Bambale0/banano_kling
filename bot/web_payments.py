"""One external website entry for Telegram commerce; no auth data in URLs."""
from urllib.parse import urlencode, urlsplit

from bot.config import config


def web_payment_url(package_id: str = "", provider: str = "", *, intent: str = "topup") -> str:
    origin = urlsplit(config.mini_app_url)
    query = {"intent": intent}
    if package_id:
        query["package_id"] = package_id
    if provider:
        query["provider"] = provider
    destination = "/mini-app/?" + urlencode(query)
    return f"{origin.scheme}://{origin.netloc}/login?" + urlencode({"return_to": destination})


def payment_callback_target(value: str) -> tuple[str, str] | None:
    if value.startswith("buy_stars_"):
        return None
    if value in {"menu_balance", "menu_topup", "menu_buy_credits", "topup_enter_promo", "topup_remove_promo"}:
        return "", ""
    prefixes = {
        "choose_pay_": "", "buy_lava_foreign_paypal_": "lava_foreign_paypal",
        "buy_lava_foreign_card_": "lava_foreign_card", "buy_lava_foreign_": "lava_foreign",
        "buy_lava_card_": "lava_card", "buy_lava_sbp_": "lava_sbp", "buy_lava_": "lava",
        "freekassa_card_": "freekassa_card", "freekassa_sbp_": "freekassa_sbp",
        "buy_freekassa_": "freekassa", "buy_yookassa_": "yookassa", "buy_crypto_": "cryptobot",
        "buy_robokassa_": "robokassa", "prodamus_pay_": "prodamus", "buy_": "",
    }
    for prefix, provider in prefixes.items():
        if value.startswith(prefix):
            return value[len(prefix):], provider
    return None
