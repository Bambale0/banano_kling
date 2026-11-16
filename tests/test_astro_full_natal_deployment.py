"""Deployment must fail closed and make external assets read-only."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_natal_depends_on_readonly_external_assets():
    compose = (ROOT / "compose.backend.yml").read_text(encoding="utf-8")
    assert ".env.astro" in compose
    assert "/app/astro-assets:ro" in compose
    assert "required: false" in compose
    assert "openephem==0.5.0" in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "/astro-assets/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_real_smoke_exists_without_user_data_provider_or_charges():
    source = (ROOT / "scripts/astro_natal_smoke.py").read_text(encoding="utf-8")
    assert "build_natal_facts" in source
    assert "get_place" in source
    assert "_ecliptic_longitude" in source
    assert "ASTRO_FULL_NATAL_SMOKE_OK" in source
