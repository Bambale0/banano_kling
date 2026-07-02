#!/usr/bin/env python3
"""Fix AIAPIClient.create_kie_task delegation using regex."""
import re

with open("vk_bot_lp.py", "r") as f:
    content = f.read()

old = content

# Replace the full create_kie_task method body
pattern = r'(    async def create_kie_task\(self, model: str, input_data: dict, api_key: str\) -> str:\n)(.*?)(?=\n    async def upload_url_to_kie)'

replacement = r'''\1        """Delegate to kie_ai.services.create_kie_task. Preserves public API."""
        return await kie_ai_create_kie_task(
            model, input_data, api_key, callback_url=Config.WEBHOOK_URL
        )

    async def upload_url_to_kie'''

content = re.sub(pattern, replacement, content, count=1, flags=re.DOTALL)

if content != old:
    with open("vk_bot_lp.py", "w") as f:
        f.write(content)
    print("OK: create_kie_task delegated to services")
else:
    print("FAIL: no match")
