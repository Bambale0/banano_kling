import base64
import importlib
from pathlib import Path

import pytest

from bot.services.nano_banana_2_service import NanoBanana2Service
from bot.services.nano_banana_pro_service import NanoBananaProService
from bot.services.nexus_image_provider import (
    NexusImageProvider,
    build_nexus_image_params,
)


@pytest.mark.parametrize("model_name", ["nano-banana-2", "nano-banana-pro"])
def test_nexus_payload_uses_documented_model_and_reference_fields(model_name: str) -> None:
    refs = [f"https://example.com/{index}.png" for index in range(6)]

    params = build_nexus_image_params(
        model_name=model_name,
        prompt="keep the subject and change the background",
        aspect_ratio="16:9",
        image_input=refs,
        max_references=4,
    )

    assert params["model_name"] == model_name
    assert params["prompt"] == "keep the subject and change the background"
    assert params["aspect_ratio"] == "16:9"
    assert params["image_urls"] == refs[:4]
    assert "image_url" not in params
    assert "resolution" not in params
    assert "output_format" not in params


def test_nexus_payload_uses_image_urls_for_one_reference() -> None:
    params = build_nexus_image_params(
        model_name="nano-banana-pro",
        prompt="edit",
        aspect_ratio="1:1",
        image_input=["https://example.com/source.png"],
    )

    assert params["image_urls"] == ["https://example.com/source.png"]
    assert "image_url" not in params


class _FakeResponse:
    def __init__(self, status: int, payload: dict, body: str = "{}") -> None:
        self.status = status
        self._payload = payload
        self._body = body
        self.headers = {"Content-Type": "application/json"}
        self.content_length = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self) -> str:
        return self._body

    async def json(self, content_type=None):
        return self._payload

    async def read(self) -> bytes:
        return self._body.encode()


class _FakeSession:
    def __init__(self, completed_payload: dict) -> None:
        self.completed_payload = completed_payload
        self.start_json = None
        self.start_headers = None

    def post(self, url: str, *, headers: dict, json: dict):
        self.start_json = json
        self.start_headers = headers
        return _FakeResponse(202, {"task_id": "nexus-task-1"})

    def get(self, url: str, *, headers: dict):
        return _FakeResponse(200, self.completed_payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("model_name", ["nano-banana-2", "nano-banana-pro"])
async def test_nexus_provider_queues_task_and_decodes_completed_result(
    monkeypatch,
    model_name: str,
) -> None:
    raw = b"fake-png-bytes"
    encoded = base64.b64encode(raw).decode("ascii")
    fake_session = _FakeSession(
        {
            "status": "completed",
            "result": {"base64": f"data:image/png;base64,{encoded}"},
        }
    )
    provider = NexusImageProvider(api_key="test-key", model_name=model_name)

    async def _session():
        return fake_session

    monkeypatch.setattr(provider, "_get_session", _session)

    queued = await provider.generate_image(
        "draw a banana",
        "1:1",
        "4K",
        ["https://example.com/ref.png"],
        "png",
    )

    assert queued == {
        "task_id": "nexus-task-1",
        "provider": "nexus",
        "provider_model": model_name,
        "provider_task_id": "nexus-task-1",
        "retryable": False,
    }
    assert fake_session.start_json["params"]["model_name"] == model_name
    assert fake_session.start_json["params"]["image_urls"] == [
        "https://example.com/ref.png"
    ]
    assert fake_session.start_json["params"]["image_size"] == "4K"
    assert "resolution" not in fake_session.start_json["params"]
    assert len(fake_session.start_headers["Idempotency-Key"]) >= 8

    completed = await provider.get_completed_result(
        "nexus-task-1",
        fake_session.completed_payload,
    )
    assert completed is not None
    assert completed["image_bytes"] == raw
    assert completed["provider"] == "nexus"
    assert completed["provider_model"] == model_name
    assert completed["provider_task_id"] == "nexus-task-1"


class _FailingNexus:
    async def generate_image(self, *args, **kwargs):
        return None

    async def close(self):
        return None


class _FakeKie:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.posts = []

    async def _post(self, endpoint: str, payload: dict):
        self.posts.append((endpoint, payload))
        return {"data": {"taskId": self.task_id}}

    async def _get(self, endpoint: str, params: dict | None = None):
        return None

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_nano_banana_2_falls_back_to_existing_kie_task_flow(monkeypatch) -> None:
    module = importlib.import_module("bot.services.nano_banana_2_service")

    async def _upload(sources):
        return list(sources)

    monkeypatch.setattr(module.kie_file_upload_service, "upload_local_image_sources", _upload)
    kie = _FakeKie("kie-nb2")
    service = NanoBanana2Service(primary_provider=_FailingNexus(), fallback_provider=kie)

    result = await service.generate_image("prompt", aspect_ratio="1:1", resolution="4K")

    assert result == {
        "task_id": "kie-nb2",
        "provider": "kie",
        "provider_model": "nano-banana-2",
    }
    assert kie.posts[0][0] == "/api/v1/jobs/createTask"
    assert kie.posts[0][1]["model"] == "nano-banana-2"
    assert kie.posts[0][1]["input"]["resolution"] == "4K"


@pytest.mark.asyncio
async def test_nano_banana_pro_falls_back_to_existing_kie_task_flow(monkeypatch) -> None:
    module = importlib.import_module("bot.services.nano_banana_pro_service")

    async def _upload(sources):
        return list(sources)

    monkeypatch.setattr(module.kie_file_upload_service, "upload_local_image_sources", _upload)
    kie = _FakeKie("kie-pro")
    service = NanoBananaProService(primary_provider=_FailingNexus(), fallback_provider=kie)

    result = await service.generate_image("prompt", aspect_ratio="1:1", resolution="2K")

    assert result == {"task_id": "kie-pro"}
    assert kie.posts[0][0] == "/api/v1/jobs/createTask"
    assert kie.posts[0][1]["model"] == "nano-banana-pro"
    assert kie.posts[0][1]["input"]["resolution"] == "2K"


class _FailingKie:
    async def _post(self, endpoint: str, payload: dict):
        return None

    async def _get(self, endpoint: str, params: dict | None = None):
        return None

    async def close(self):
        return None


class _FakeNexusFallback:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.calls = 0

    async def generate_image(self, *args, **kwargs):
        self.calls += 1
        return {
            "task_id": f"nexus-{self.model_name}",
            "provider": "nexus",
            "provider_model": self.model_name,
            "provider_task_id": f"nexus-{self.model_name}",
            "retryable": False,
        }

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_nano_banana_2_uses_nexus_only_after_kie_create_fails(monkeypatch) -> None:
    module = importlib.import_module("bot.services.nano_banana_2_service")

    async def _upload(sources):
        return list(sources)

    monkeypatch.setattr(module.kie_file_upload_service, "upload_local_image_sources", _upload)
    nexus = _FakeNexusFallback("nano-banana-2")
    service = NanoBanana2Service(primary_provider=_FailingKie(), fallback_provider=nexus)

    result = await service.generate_image("prompt", aspect_ratio="1:1", resolution="4K")

    assert result is not None
    assert result["task_id"] == "nexus-nano-banana-2"
    assert result["provider"] == "nexus"
    assert nexus.calls == 1


@pytest.mark.asyncio
async def test_nano_banana_pro_preserves_nexus_task_after_kie_create_fails(monkeypatch) -> None:
    module = importlib.import_module("bot.services.nano_banana_pro_service")

    async def _upload(sources):
        return list(sources)

    monkeypatch.setattr(module.kie_file_upload_service, "upload_local_image_sources", _upload)
    nexus = _FakeNexusFallback("nano-banana-pro")
    service = NanoBananaProService(primary_provider=_FailingKie(), fallback_provider=nexus)

    result = await service.generate_image("prompt", aspect_ratio="1:1", resolution="2K")

    assert result is not None
    assert result["task_id"] == "nexus-nano-banana-pro"
    assert result["provider"] == "nexus"
    assert nexus.calls == 1


def test_branch_routing_keeps_kie_primary_and_nexus_fallback_for_2_and_pro() -> None:
    source = Path("bot/services/__init__.py").read_text(encoding="utf-8")

    assert 'model_name="nano-banana-2"' in source
    assert 'model_name="nano-banana-pro"' in source
    assert "nano_banana_2_service.primary_provider = banana2_kie" in source
    assert "nano_banana_pro_service.primary_provider = banana_pro_kie" in source
    assert "nano_banana_2_service.fallback_provider = NexusImageProvider(" in source
    assert "nano_banana_pro_service.fallback_provider = NexusImageProvider(" in source
    assert "Nano Banana 2 Lite is intentionally untouched" in source
