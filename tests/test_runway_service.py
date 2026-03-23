import asyncio
import hashlib
import hmac
import importlib
from unittest import mock

import pytest

rs_module = importlib.import_module("bot.services.runway_service")


class FakePrediction:
    def __init__(self, id, status, output=None, error=None, logs=None):
        self.id = id
        self.status = status
        self.output = output
        self.error = error
        self.logs = logs


class FakePredictions:
    def __init__(self, create_behavior=None, get_behavior=None):
        # create_behavior can be exception or FakePrediction or callable
        self._create_behavior = create_behavior
        self._get_behavior = get_behavior
        self.create_calls = 0

    def create(self, *args, **kwargs):
        self.create_calls += 1
        b = self._create_behavior
        if callable(b):
            return b(self.create_calls)
        if isinstance(b, Exception):
            raise b
        return b

    def get(self, task_id):
        b = self._get_behavior
        if callable(b):
            return b(task_id)
        return b


class FakeClient:
    def __init__(self, preds: FakePredictions):
        self.predictions = preds


@pytest.mark.asyncio
async def test_generate_video_retries(monkeypatch):
    # Simulate transient failures then success
    seq = [
        Exception("transient"),
        Exception("transient2"),
        FakePrediction("tid123", "processing"),
    ]

    def create_behavior(call_count):
        item = seq[call_count - 1]
        if isinstance(item, Exception):
            raise item
        return item

    fake_preds = FakePredictions(create_behavior=create_behavior)
    fake_client = FakeClient(fake_preds)

    # Patch the replicate.Client constructor used inside the module
    import types

    fake_replicate = types.SimpleNamespace(Client=lambda api_token=None: fake_client)
    monkeypatch.setattr(rs_module, "replicate", fake_replicate, raising=True)

    svc = rs_module.RunwayService(api_token="fake")

    res = await svc.generate_video(prompt="hi", duration=5)

    assert res and res.get("task_id") == "tid123"


@pytest.mark.asyncio
async def test_get_task_status_parses_fileoutput(monkeypatch):
    # Prepare FakeFileOutput-like object
    class FileOut:
        def __init__(self, url):
            self.url = url

    pred = FakePrediction(
        "tidX", "succeeded", output=[FileOut("https://file.example/out.mp4")]
    )
    fake_preds = FakePredictions(get_behavior=lambda task_id: pred)
    fake_client = FakeClient(fake_preds)

    import types

    fake_replicate = types.SimpleNamespace(Client=lambda api_token=None: fake_client)
    monkeypatch.setattr(rs_module, "replicate", fake_replicate, raising=True)

    svc = rs_module.RunwayService(api_token="fake")

    status = await svc.get_task_status("tidX")

    assert status
    assert status.get("status") == "COMPLETED"
    assert (
        status.get("generated")
        and status["generated"][0]["url"] == "https://file.example/out.mp4"
    )
