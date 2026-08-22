from __future__ import annotations

import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bot/handlers/miniapp_launch_revision_compat.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "miniapp_launch_revision_contract_target",
        MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_revision_preserves_referral_and_startapp(monkeypatch):
    module = _load_module()
    revision = "9b27f6e816d0b7bf4e2b02c47eb5216dd39e0035"
    monkeypatch.setenv("BANANO_APP_REVISION", revision)

    url = module._with_runtime_revision(
        "https://tanyapp.example/mini-app/?ref=ABC123&startapp=ref_ABC123"
    )
    parts = urlsplit(url)
    query = parse_qs(parts.query)

    assert parts.path == "/mini-app/"
    assert query["ref"] == ["ABC123"]
    assert query["startapp"] == ["ref_ABC123"]
    assert query["revision"] == [revision]


def test_unknown_or_missing_revision_keeps_launch_url_unchanged(monkeypatch):
    module = _load_module()
    original = "https://tanyapp.example/mini-app/?startapp=task_42"

    monkeypatch.delenv("BANANO_APP_REVISION", raising=False)
    assert module._with_runtime_revision(original) == original

    monkeypatch.setenv("BANANO_APP_REVISION", "unknown")
    assert module._with_runtime_revision(original) == original


def test_revisioning_is_launch_only_and_baked_into_docker_image():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    handlers = (ROOT / "bot/handlers/__init__.py").read_text(encoding="utf-8")
    compat = MODULE_PATH.read_text(encoding="utf-8")

    assert 'BANANO_APP_REVISION="${VCS_REF}"' in dockerfile
    assert "install_miniapp_launch_revision_compat(common_module)" in handlers
    assert "config.mini_app_url" not in compat
    assert 'query["revision"] = revision' in compat
