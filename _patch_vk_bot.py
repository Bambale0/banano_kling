#!/usr/bin/env python3
"""Apply fixes to vk_bot_lp.py based on GPT 5.5 review.

Fixes:
1. Make logging level env-configurable (default INFO)
2. Extract run_admin_server() from UserState enum
3. Delegate AIAPIClient.create_kie_task to kie_ai.services.create_kie_task
4. Fix obfuscated chr code
5. Normalize API key references
"""

import sys
import os
import re

def patch_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    changes = []

    # === FIX 1: Logging level ===
    old_log = '''logging.basicConfig(
    level=logging.DEBUG,
    filename="logs/vk_bot.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s",
)


logging.getLogger("yookassa_payment").setLevel(logging.DEBUG)'''

    new_log = '''LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    filename="logs/vk_bot.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s",
)


logging.getLogger("yookassa_payment").setLevel(getattr(logging, LOG_LEVEL, logging.INFO))'''

    if old_log in content:
        content = content.replace(old_log, new_log)
        changes.append("Fix 1: Logging level made env-configurable (LOG_LEVEL, default INFO)")
    else:
        changes.append("Fix 1: SKIPPED - logging code pattern not found")

    # === FIX 2: Extract run_admin_server from UserState ===
    # First, find and remove the method from inside the class
    old_enum_method = '''    async def run_admin_server(self):
        """Запуск админ-панели в отдельном процессе"""
        import multiprocessing

        admin_process = multiprocessing.Process(target=run_admin_panel)
        admin_process.start()
        logging.info("Админ-панель запущена на порту 5000")


class AIAPIClient:'''

    new_enum_method = '''class AIAPIClient:'''
    
    if old_enum_method in content:
        content = content.replace(old_enum_method, new_enum_method)
        changes.append("Fix 2: Removed run_admin_server() from UserState enum")
    else:
        changes.append("Fix 2: SKIPPED - run_admin_server pattern not found")
    
    # Add standalone run_admin_server function before UserState class
    # Find where to insert it (after Config class, before UserState)
    standalone_func = '''async def run_admin_server():
    """Запуск админ-панели в отдельном процессе"""
    import multiprocessing
    try:
        from admin_panel import run_admin_panel
    except ImportError:
        logging.error("run_admin_panel not available")
        return

    admin_process = multiprocessing.Process(target=run_admin_panel)
    admin_process.start()
    logging.info("Админ-панель запущена на порту 5000")


class UserState(str, Enum):'''
    
    old_user_state = '''class UserState(str, Enum):'''
    
    if standalone_func not in content and old_user_state in content:
        content = content.replace(
            old_user_state,
            standalone_func
        )
        changes.append("Fix 2: Added standalone run_admin_server() function before UserState")
    else:
        changes.append("Fix 2: SKIPPED - standalone function already exists or pattern not found")

    # === FIX 3: Fix AIAPIClient.create_kie_task ===
    # Delegate to services.create_kie_task and fix chr obfuscation
    old_create_kie = '''    async def create_kie_task(self, model: str, input_data: dict, api_key: str) -> str:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        input_payload = dict(input_data or {})
        input_payload.setdefault("nsfw_checker", False)
        data = {
            "model": model,
            "callBackUrl": Config.WEBHOOK_URL,
            "input": input_payload,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.kie.ai/api/v1/jobs/createTask", headers=headers, json=data
            ) as resp:
                result = await resp.json()
                if result.get("code") == 200:
                    return result["data"]["taskId"]
                logging.error(f"KIE task fail: {result.get(chr(34)+chr(34)+chr(109)+chr(115)+chr(103)+chr(34)+chr(34), chr(34)+chr(34)+chr(85)+chr(110)+chr(107)+chr(110)+chr(111)+chr(119)+chr(34)+chr(34))}")
                raise ValueError(result.get("msg", "KIE task creation failed"))'''

    new_create_kie = '''    async def create_kie_task(self, model: str, input_data: dict, api_key: str) -> str:
        """Delegate to kie_ai.services.create_kie_task. Preserves public API."""
        return await kie_ai_create_kie_task(
            model, input_data, api_key, callback_url=Config.WEBHOOK_URL
        )'''

    if old_create_kie in content:
        content = content.replace(old_create_kie, new_create_kie)
        changes.append("Fix 3+4: AIAPIClient.create_kie_task now delegates to services.create_kie_task, obfuscated chr code removed")
    else:
        changes.append("Fix 3+4: SKIPPED - create_kie_task pattern not found")

    # === FIX 5: Normalize API key references ===
    # Replace Config.KLING_API_KEY with Config.api_key() in the main handler area
    # Only do this for the create_kie_task call sites, not for legacy/compat services
    replacements = [
        # Line 6109-ish
        ('model, input_data, Config.KLING_API_KEY, Config.WEBHOOK_URL',
         'model, input_data, Config.api_key(), Config.WEBHOOK_URL'),
        # Line 6082-ish
        ('photo_url, Config.KLING_API_KEY, "motioncontrol"',
         'photo_url, Config.api_key(), "motioncontrol"'),
        # Line 6087-ish
        ('Config.KLING_API_KEY,',
         'Config.api_key(),'),
        # Line 6094-ish
        ('video_url, Config.KLING_API_KEY, "motioncontrol"',
         'video_url, Config.api_key(), "motioncontrol"'),
        # Line 6110-ish
        ('model, input_data, Config.KLING_API_KEY',
         'model, input_data, Config.api_key()'),
        # Line 6132-ish  
        ('api_key = Config.KLING_API_KEY',
         'api_key = Config.api_key()'),
        # Line 6274-ish
        ('url, Config.KLING_API_KEY, "references"',
         'url, Config.api_key(), "references"'),
        # Line 6286-ish
        ('api_key = Config.KLING_API_KEY',
         'api_key = Config.api_key()'),
        # Line 6298-ish
        ('api_key = Config.KLING_API_KEY',
         'api_key = Config.api_key()'),
        # Line 6313-ish
        ('api_key = Config.KLING_API_KEY',
         'api_key = Config.api_key()'),
    ]
    
    api_changes = 0
    for old, new in replacements:
        count = content.count(old)
        if count > 0:
            content = content.replace(old, new)
            api_changes += count
    
    if api_changes > 0:
        changes.append(f"Fix 5: Normalized {api_changes} API key reference(s) to Config.api_key()")
    else:
        changes.append("Fix 5: SKIPPED - no KLING_API_KEY references to replace")

    # === FIX: Add import alias ===
    # Need to add import alias for kie_ai.services.create_kie_task -> kie_ai_create_kie_task
    # since we're using it inside AIAPIClient
    old_import = '''from kie_ai.services import (
    create_kie_task, get_kie_task_detail, KieFileService,'''
    
    new_import = '''from kie_ai.services import (
    create_kie_task as kie_ai_create_kie_task, get_kie_task_detail, KieFileService,'''

    if old_import in content:
        content = content.replace(old_import, new_import)
        changes.append("Fix Import: Added alias for services.create_kie_task")
    else:
        changes.append("Fix Import: SKIPPED - import pattern not found")

    # Write changes
    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Applied {len([c for c in changes if 'SKIPPED' not in c])} fixes:")
        for c in changes:
            print(f"  {'✓' if 'SKIPPED' not in c else '○'} {c}")
        return True
    else:
        print("❌ No changes made - file content unchanged")
        return False


if __name__ == "__main__":
    filepath = sys.argv[1] if len(sys.argv) > 1 else "vk_bot_lp.py"
    print(f"Patching {filepath}...")
    success = patch_file(filepath)
    sys.exit(0 if success else 1)
