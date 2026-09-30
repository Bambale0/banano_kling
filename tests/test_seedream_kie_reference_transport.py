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


@pytest.mark.asyncio
async def test_seedream_5_pro_caps_prompt_before_provider(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_upload(sources, **_kwargs):
        return ["https://tempfile.redpandaai.co/seedream/reference.png"]

    async def fake_kie_post(endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {"task_id": "task-long-prompt"}

    monkeypatch.setattr(
        seedream_module.kie_file_upload_service,
        "upload_local_image_sources",
        fake_upload,
    )
    monkeypatch.setattr(seedream_module.seedream_service, "_kie_post", fake_kie_post)

    result = await seedream_module.seedream_service.generate_image(
        prompt="x" * 5756,
        image_urls=["https://example.test/reference.png"],
        model="seedream/5-pro-image-to-image",
    )

    assert result == {"task_id": "task-long-prompt"}
    assert captured["endpoint"] == "/api/v1/jobs/createTask"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert len(payload["input"]["prompt"]) == 5000


def test_seedream_45_keeps_existing_6000_char_cap():
    normalized = seedream_module.seedream_service._normalize_prompt(
        "x" * 6500,
        model="seedream/4.5-edit",
    )
    assert len(normalized) == 6000
