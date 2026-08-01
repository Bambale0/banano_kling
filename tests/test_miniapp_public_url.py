from __future__ import annotations

from bot.env import DEFAULT_MINI_APP_URL, load_project_env


def test_mini_app_url_defaults_to_public_cdn(monkeypatch, tmp_path):
    monkeypatch.delenv("MINI_APP_URL", raising=False)
    monkeypatch.setenv("BANANO_SKIP_PROJECT_ENV", "1")

    load_project_env(tmp_path)

    assert DEFAULT_MINI_APP_URL == "https://cdn.chillcreative.ru/mini-app/"
    assert __import__("os").environ["MINI_APP_URL"] == DEFAULT_MINI_APP_URL


def test_explicit_mini_app_url_is_preserved(monkeypatch, tmp_path):
    custom_url = "https://frontend.example.test/mini-app/"
    monkeypatch.setenv("MINI_APP_URL", custom_url)
    monkeypatch.setenv("BANANO_SKIP_PROJECT_ENV", "1")

    load_project_env(tmp_path)

    assert __import__("os").environ["MINI_APP_URL"] == custom_url
