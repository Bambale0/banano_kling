#!/usr/bin/env python3
"""Update test to mock kie_ai_create_kie_task directly since we now delegate."""
import re

with open("tests/test_vk_bot_lp_smoke.py", "r") as f:
    content = f.read()

old_test = '''@pytest.mark.asyncio
async def test_aiapi_create_task_adds_nsfw_checker_false(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def json(self):
            return {"code": 200, "data": {"taskId": "task-1"}}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(vk_bot_lp.aiohttp, "ClientSession", FakeSession)

    task_id = await vk_bot_lp.AIAPIClient().create_kie_task(
        "nano-banana-pro", {"prompt": "test"}, "key"
    )

    assert task_id == "task-1"
    assert captured["json"]["input"]["nsfw_checker"] is False'''

new_test = '''@pytest.mark.asyncio
async def test_aiapi_create_task_adds_nsfw_checker_false(monkeypatch):
    captured = {}

    async def fake_create_kie_task(model, input_data, api_key, callback_url=None):
        captured["model"] = model
        captured["input_data"] = input_data
        captured["api_key"] = api_key
        captured["callback_url"] = callback_url
        return "task-1"

    monkeypatch.setattr(
        vk_bot_lp, "kie_ai_create_kie_task", fake_create_kie_task
    )

    task_id = await vk_bot_lp.AIAPIClient().create_kie_task(
        "nano-banana-pro", {"prompt": "test"}, "key"
    )

    assert task_id == "task-1"
    assert captured["input_data"]["nsfw_checker"] is False
    assert captured["callback_url"] == vk_bot_lp.Config.WEBHOOK_URL'''

if old_test in content:
    content = content.replace(old_test, new_test)
    with open("tests/test_vk_bot_lp_smoke.py", "w") as f:
        f.write(content)
    print("OK: test updated")
else:
    print("FAIL: test pattern not found")
