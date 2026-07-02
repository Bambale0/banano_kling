#!/usr/bin/env python3
"""Add nsfw_checker back to AIAPIClient.create_kie_task delegate."""
with open("vk_bot_lp.py", "r") as f:
    content = f.read()

old = '''    async def create_kie_task(self, model: str, input_data: dict, api_key: str) -> str:
        """Delegate to kie_ai.services.create_kie_task. Preserves public API."""
        return await kie_ai_create_kie_task(
            model, input_data, api_key, callback_url=Config.WEBHOOK_URL
        )'''

new = '''    async def create_kie_task(self, model: str, input_data: dict, api_key: str) -> str:
        """Delegate to kie_ai.services.create_kie_task. Preserves public API."""
        payload = dict(input_data or {})
        payload.setdefault("nsfw_checker", False)
        return await kie_ai_create_kie_task(
            model, payload, api_key, callback_url=Config.WEBHOOK_URL
        )'''

if old in content:
    content = content.replace(old, new)
    with open("vk_bot_lp.py", "w") as f:
        f.write(content)
    print("OK: nsfw_checker added back")
else:
    print("FAIL: pattern not found")
