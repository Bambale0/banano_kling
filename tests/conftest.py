import os
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
    monkeypatch.setenv("PAYMENT_PROVIDER", "yookassa")
