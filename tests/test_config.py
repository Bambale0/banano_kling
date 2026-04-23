"""Unit tests for bot/config.py"""

import pytest

from bot.config import Config


class TestConfig:
    def test_admin_ids(self):
        cfg = Config()
        cfg.ADMIN_IDS_STR = "123,456"
        assert cfg.admin_ids == [123, 456]

    def test_admin_ids_invalid(self):
        cfg = Config()
        cfg.ADMIN_IDS_STR = "invalid"
        assert cfg.admin_ids == []

    def test_admin_ids_empty(self):
        cfg = Config()
        cfg.ADMIN_IDS_STR = ""
        assert cfg.admin_ids == []

    def test_is_admin_true(self):
        cfg = Config()
        cfg.ADMIN_IDS_STR = "123456"
        assert cfg.is_admin(123456) is True

    def test_is_admin_false(self):
        cfg = Config()
        cfg.ADMIN_IDS_STR = "123456"
        assert cfg.is_admin(789012) is False

    def test_webhook_url(self):
        cfg = Config()
        cfg.WEBHOOK_HOST = "https://test.com"
        cfg.WEBHOOK_PATH = "/webhook"
        assert cfg.webhook_url == "https://test.com/webhook"

    def test_webhook_url_trailing_slash(self):
        cfg = Config()
        cfg.WEBHOOK_HOST = "https://test.com/"
        cfg.WEBHOOK_PATH = "/webhook"
        assert cfg.webhook_url == "https://test.com/webhook"

    def test_webhook_path_no_leading_slash(self):
        cfg = Config()
        cfg.WEBHOOK_HOST = "https://test.com"
        cfg.WEBHOOK_PATH = "webhook"
        assert cfg.webhook_url == "https://test.com/webhook"

    def test_payment_provider_tbank(self):
        cfg = Config()
        cfg.PAYMENT_PROVIDER = "tbank"
        assert cfg.payment_provider == "tbank"

    def test_payment_provider_yookassa(self):
        cfg = Config()
        cfg.PAYMENT_PROVIDER = "yookassa"
        assert cfg.payment_provider == "yookassa"

    def test_payment_provider_default(self):
        cfg = Config()
        cfg.PAYMENT_PROVIDER = "invalid"
        assert cfg.payment_provider == "tbank"

    def test_has_jump_finance_true_with_agent_id(self):
        cfg = Config()
        cfg.JUMP_FINANCE_CLIENT_KEY = "client-key"
        cfg.JUMP_FINANCE_AGENT_ID = 123
        assert cfg.has_jump_finance is True
        assert cfg.jump_finance_missing_settings == []

    def test_has_jump_finance_true_without_agent_id(self):
        cfg = Config()
        cfg.JUMP_FINANCE_CLIENT_KEY = "client-key"
        cfg.JUMP_FINANCE_AGENT_ID = 0
        assert cfg.has_jump_finance is True
        assert cfg.jump_finance_missing_settings == []

    def test_has_yookassa_true(self):
        cfg = Config()
        cfg.YOOKASSA_SHOP_ID = "shop123"
        cfg.YOOKASSA_SECRET_KEY = "secret"
        assert cfg.has_yookassa is True

    def test_has_yookassa_false(self):
        cfg = Config()
        cfg.YOOKASSA_SHOP_ID = ""
        cfg.YOOKASSA_SECRET_KEY = "secret"
        assert cfg.has_yookassa is False

    def test_static_base_url_default(self):
        cfg = Config()
        cfg.WEBHOOK_HOST = ""
        assert cfg.static_base_url == "https://dev.chillcreative.ru"

    def test_static_base_url_webhook(self):
        cfg = Config()
        cfg.WEBHOOK_HOST = "https://custom.com"
        assert cfg.static_base_url == "https://custom.com"
