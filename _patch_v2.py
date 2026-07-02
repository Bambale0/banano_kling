#!/usr/bin/env python3
"""Second round of fixes for vk_bot_lp.py"""
import os

filepath = "/root/vktanya/vk_bot_lp.py"
with open(filepath, 'r') as f:
    content = f.read()

orig = content

# === Fix 2b: Insert standalone run_admin_server ===
standalone = '''async def run_admin_server():
    """\u0417\u0430\u043f\u0443\u0441\u043a \u0430\u0434\u043c\u0438\u043d-\u043f\u0430\u043d\u0435\u043b\u0438 \u0432 \u043e\u0442\u0434\u0435\u043b\u044c\u043d\u043e\u043c \u043f\u0440\u043e\u0446\u0435\u0441\u0441\u0435"""
    import multiprocessing
    try:
        from admin_panel import run_admin_panel
    except ImportError:
        logging.error("run_admin_panel not available")
        return

    admin_process = multiprocessing.Process(target=run_admin_panel)
    admin_process.start()
    logging.info("\u0410\u0434\u043c\u0438\u043d-\u043f\u0430\u043d\u0435\u043b\u044c \u0437\u0430\u043f\u0443\u0449\u0435\u043d\u0430 \u043d\u0430 \u043f\u043e\u0440\u0442\u0443 5000")


'''

target = "# ==================== \u0421\u041e\u0421\u0422\u041e\u042f\u041d\u0418\u042f \u0411\u041e\u0422\u0410 ===================="
if target in content:
    content = content.replace(target, standalone + target)
    print("OK: inserted standalone run_admin_server")
else:
    print("FAIL: could not find insertion point")

# === Fix 3+4: Delegate AIAPIClient.create_kie_task ===
old = '\n    async def create_kie_task(self, model: str, input_data: dict, api_key: str) -> str:\n        headers = {\n            "Authorization": f"Bearer {api_key}",\n            "Content-Type": "application/json",\n        }\n        input_payload = dict(input_data or {})\n        input_payload.setdefault("nsfw_checker", False)\n        data = {\n            "model": model,\n            "callBackUrl": Config.WEBHOOK_URL,\n            "input": input_payload,\n        }\n        async with aiohttp.ClientSession() as session:\n            async with session.post(\n                "https://api.kie.ai/api/v1/jobs/createTask", headers=headers, json=data\n            ) as resp:\n                result = await resp.json()\n                if result.get("code") == 200:\n                    return result["data"]["taskId"]\n                logging.error(f"KIE task fail: {result.get(chr(34)+chr(34)+chr(109)+chr(115)+chr(103)+chr(34)+chr(34), chr(34)+chr(34)+chr(85)+chr(110)+chr(107)+chr(110)+chr(111)+chr(119)+chr(34)+chr(34))}")\n                raise ValueError(result.get("msg", "KIE task creation failed"))'

new = '''\n    async def create_kie_task(self, model: str, input_data: dict, api_key: str) -> str:
        """Delegate to kie_ai.services.create_kie_task. Preserves public API."""
        return await kie_ai_create_kie_task(
            model, input_data, api_key, callback_url=Config.WEBHOOK_URL
        )'''

if old in content:
    content = content.replace(old, new)
    print("OK: create_kie_task delegated")
else:
    print("FAIL: create_kie_task pattern not matched")
    idx = content.find('async def create_kie_task(self, model: str')
    if idx >= 0:
        print(f"Found at pos {idx}")
        snippet = content[idx:idx+900]
        print("--- SNIPPET ---")
        print(repr(snippet))
        print("--- END ---")

if content != orig:
    with open(filepath, 'w') as f:
        f.write(content)
    print("File written.")
else:
    print("No changes.")
