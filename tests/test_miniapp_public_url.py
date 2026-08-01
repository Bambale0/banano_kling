from __future__ import annotations

import os

from bot.env import DEFAULT_MINI_APP_URL, load_project_env


def test_missing_mini_app_url_defaults_to_public_cdn(monkeypatch, tmp_path):
    monkeypatch.setenv("BANANO_SKIP_PROJECT_ENV", "1")
    monkeypatch.delenv("MINI_APP_URL", raising=False)
    monkeypatch.setenv("WEBHOOK_HOST", "https://tanyapi.chillcreative.ru")

    load_project_env(tmp_path)

    assert os.environ["MINI_APP_URL"] == DEFAULT_MINI_APP_URL


def test_legacy_backend_mini_app_url_is_replaced(monkeypatch, tmp_path):
    monkeypatch.setenv("BANANO_SKIP_PROJECT_ENV", "1")
    monkeypatch.setenv("WEBHOOK_HOST", "https://tanyapi.chillcreative.ru")
    monkeypatch.setenv("MINI_APP_PATH", "/mini-app")
    monkeypatch.setenv(
        "MINI_APP_URL",
        "https://tanyapi.chillcreative.ru/mini-app/",
    )

    load_project_env(tmp_path)

    assert os.environ["MINI_APP_URL"] == DEFAULT_MINI_APP_URL


def test_any_stale_override_is_replaced_by_production_cdn(monkeypatch, tmp_path):
    monkeypatch.setenv("BANANO_SKIP_PROJECT_ENV", "1")
    monkeypatch.setenv("MINI_APP_URL", "https://old.example.test/mini-app/")

    load_project_env(tmp_path)

    assert os.environ["MINI_APP_URL"] == DEFAULT_MINI_APP_URL
