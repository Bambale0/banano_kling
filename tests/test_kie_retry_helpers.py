import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import bot.main as main_module
from bot.main import (
    _is_retryable_kie_timeout_failure,
    _retry_nexus_banana_image_failure,
)

nano_banana_2_module = importlib.import_module("bot.services.nano_banana_2_service")
nano_banana_pro_module = importlib.import_module("bot.services.nano_banana_pro_service")


def test_seedream_download_timeout_is_retryable():
    task = SimpleNamespace(type="image", model="seedream_edit")

    assert _is_retryable_kie_timeout_failure(
        task,
        400,
        "Timeout while downloading url=https://tempfile.redpandaai.co/file.jpg",
    )


def test_seedream_sensitive_failure_is_not_retried_as_timeout():
    task = SimpleNamespace(type="image", model="seedream_edit")

    assert not _is_retryable_kie_timeout_failure(
        task,
        500,
        "The request failed because the output image may contain sensitive information.",
    )


def test_seedream_5_pro_download_timeout_is_retryable():
    task = SimpleNamespace(type="image", model="seedream_5_pro")

    assert _is_retryable_kie_timeout_failure(
        task,
        500,
        "No results were returned because the provider timed out while downloading the source.",
    )


class _FakeDbConnection:
    def __init__(self):
        self.execute = AsyncMock()
        self.commit = AsyncMock()


class _FakeDbContext:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_retry_nexus_banana_2_failure_requeues_through_kie(monkeypatch):
    connection = _FakeDbConnection()
    monkeypatch.setattr(
        main_module.db_backend,
        "connect",
        lambda: _FakeDbContext(connection),
    )
    create_task = AsyncMock(return_value="kie-task-2")
    monkeypatch.setattr(
        nano_banana_2_module.nano_banana_2_service,
        "create_task",
        create_task,
    )

    task = SimpleNamespace(
        type="image",
        model="banana_2",
        prompt=None,
        aspect_ratio="16:9",
        user_id=77,
        request_data=json.dumps(
            {
                "img_service": "banana_2",
                "provider": "nexus",
                "prompt": "make image",
                "img_ratio": "16:9",
                "img_quality": "4K",
                "reference_images": ["https://example.com/prepared.png"],
                "source_reference_images": ["https://example.com/source.png"],
            }
        ),
    )

    new_task_id = await _retry_nexus_banana_image_failure(
        task,
        "nexus-task-1",
        reason="provider safety block",
    )

    assert new_task_id == "kie-task-2"
    create_task.assert_awaited_once_with(
        prompt="make image",
        image_input=["https://example.com/source.png"],
        aspect_ratio="16:9",
        resolution="4K",
        callback_url=main_module.config.kie_notification_url
        if main_module.config.WEBHOOK_HOST
        else None,
        model="nano-banana-2",
    )
    assert connection.execute.await_count == 1
    query_args = connection.execute.await_args.args
    assert query_args[0].startswith("UPDATE generation_tasks SET task_id = ?")
    assert query_args[1][0] == "kie-task-2"
    updated_request_data = json.loads(query_args[1][1])
    assert updated_request_data["provider"] == "kie"
    assert updated_request_data["provider_model"] == "nano-banana-2"
    assert updated_request_data["provider_task_id"] == "kie-task-2"
    assert updated_request_data["auto_retry_attempt"] == 1


@pytest.mark.asyncio
async def test_retry_nexus_banana_pro_failure_requeues_through_kie(monkeypatch):
    connection = _FakeDbConnection()
    monkeypatch.setattr(
        main_module.db_backend,
        "connect",
        lambda: _FakeDbContext(connection),
    )
    create_task = AsyncMock(return_value="kie-task-pro")
    monkeypatch.setattr(
        nano_banana_pro_module.nano_banana_pro_service,
        "create_task",
        create_task,
    )

    task = SimpleNamespace(
        type="image",
        model="banana_pro",
        prompt=None,
        aspect_ratio="1:1",
        user_id=88,
        request_data=json.dumps(
            {
                "img_service": "banana_pro",
                "provider": "nexus",
                "effective_prompt": "keep face details",
                "img_ratio": "1:1",
                "img_quality": "2K",
                "reference_images": ["https://example.com/ref.png"],
            }
        ),
    )

    new_task_id = await _retry_nexus_banana_image_failure(
        task,
        "nexus-task-pro",
        reason="moderation failure",
    )

    assert new_task_id == "kie-task-pro"
    create_task.assert_awaited_once_with(
        prompt="keep face details",
        image_input=["https://example.com/ref.png"],
        aspect_ratio="1:1",
        resolution="2K",
        callback_url=main_module.config.kie_notification_url
        if main_module.config.WEBHOOK_HOST
        else None,
    )
