#!/usr/bin/env python3
import re

with open("tests/test_vk_bot_lp_smoke.py", "r") as f:
    content = f.read()

# Find the old test function
start = content.find("async def test_aiapi_create_task_adds_nsfw_checker_false(monkeypatch):")
if start < 0:
    print("FAIL: test function not found")
    exit(1)

end = content.find("\n\n@pytest.mark.asyncio\nasync def test_photo_analysis", start)
if end < 0:
    print("FAIL: end boundary not found")
    exit(1)

old = content[start:end]

new = '''async def test_aiapi_create_task_adds_nsfw_checker_false(monkeypatch):
    captured = {}

    async def fake_create_kie_task(model, input_data, api_key, callback_url=None):
        captured["model"] = model
        captured["input_data"] = input_data
        captured["api_key"] = api_key
        captured["callback_url"] = callback_url
        return "task-1"

    import vk_bot_lp
    monkeypatch.setattr(
        vk_bot_lp, "kie_ai_create_kie_task", fake_create_kie_task
    )

    task_id = await vk_bot_lp.AIAPIClient().create_kie_task(
        "nano-banana-pro", {"prompt": "test"}, "key"
    )

    assert task_id == "task-1"
    assert captured["input_data"]["nsfw_checker"] is False
    assert captured["callback_url"] == vk_bot_lp.Config.WEBHOOK_URL'''

content = content.replace(old, new)
with open("tests/test_vk_bot_lp_smoke.py", "w") as f:
    f.write(content)
print("OK: test updated")
