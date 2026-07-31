from __future__ import annotations

import importlib

import pytest

upload_module = importlib.import_module("bot.services.kie_file_upload_service")
seedream_module = importlib.import_module("bot.services.seedream_service")


@pytest.mark.asyncio
async def test_seedream_forces_local_references_into_kie_storage(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_upload(sources, **kwargs):
        captured["sources"] = list(sources)
        captured.update(kwargs)
        return ["https://tempfile.redpandaai.co/seedream/reference.png"]

    monkeypatch.setattr(
        seedream_module,
        "image_sources_to_supported_image_urls",
        lambda sources: list(sources),
    )
    monkeypatch.setattr(
        seedream_module.kie_file_upload_service,
        "upload_local_image_sources",
        fake_upload,
    )

    result = await seedream_module.seedream_service._prepare_effective_image_urls(
        ["https://tanyapi.chillcreative.ru/uploads/reference.png"]
    )

    assert result == ["https://tempfile.redpandaai.co/seedream/reference.png"]
    assert captured["prefer_stable_public_url"] is False
    assert captured["fallback_to_source"] is False


@pytest.mark.asyncio
async def test_seedream_aborts_instead_of_sending_unreachable_own_url(monkeypatch):
    async def failed_upload(_sources, **_kwargs):
        return [""]

    monkeypatch.setattr(
        seedream_module,
        "image_sources_to_supported_image_urls",
        lambda sources: list(sources),
    )
    monkeypatch.setattr(
        seedream_module.kie_file_upload_service,
        "upload_local_image_sources",
        failed_upload,
    )

    result = await seedream_module.seedream_service._prepare_effective_image_urls(
        ["https://tanyapi.chillcreative.ru/uploads/reference.png"]
    )

    assert result is None


@pytest.mark.asyncio
async def test_strict_kie_upload_drops_missing_local_reference(monkeypatch):
    monkeypatch.setattr(upload_module, "resolve_local_upload_path", lambda _source: None)
    monkeypatch.setattr(upload_module, "is_local_upload_source", lambda _source: True)

    service = upload_module.KieFileUploadService(api_key="test-key")
    source = "https://tanyapi.chillcreative.ru/uploads/missing.png"

    result = await service.upload_local_image_source(
        source,
        prefer_stable_public_url=False,
        fallback_to_source=False,
    )

    assert result == ""
