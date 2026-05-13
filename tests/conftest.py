import os

TEST_ENV_DEFAULTS = {
    "BOT_TOKEN": "123456:test-token",
    "ADMIN_IDS": "999999",
    "WEBHOOK_HOST": "https://test.example.com",
    "WEBHOOK_PATH": "/telegram/webhook",
    "WEBHOOK_PORT": "8443",
    "DATABASE_PATH": ":memory:",
    "DATABASE_URL": "sqlite:///:memory:",
    "TBANK_TERMINAL_KEY": "test-terminal",
    "TBANK_SECRET_KEY": "test-secret",
    "KIE_AI_API_KEY": "test-kie-key",
    "CRYPTOBOT_API_TOKEN": "test-cryptobot-token",
}
for _key, _value in TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)


def pytest_ignore_collect(collection_path, config):
    """Provider standalone scripts are opt-in; they require live API modules/keys."""
    path = str(collection_path)
    return "/tests/standalone/" in path and not os.getenv("RUN_STANDALONE_TESTS")

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


@pytest.fixture
def temp_db_path(tmp_path):
    """Temporary database path"""
    return tmp_path / "test.db"


@pytest.fixture
def mock_env(monkeypatch):
    """Mock common environment variables"""
    monkeypatch.setenv("BOT_TOKEN", "test_bot_token")
    monkeypatch.setenv("ADMIN_IDS", "123456,789012")
    monkeypatch.setenv("WEBHOOK_HOST", "https://test.example.com")
    monkeypatch.setenv("WEBHOOK_PATH", "/webhook")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("PAYMENT_PROVIDER", "tbank")
