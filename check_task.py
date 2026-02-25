#!/usr/bin/env python3
"""Проверка статуса задачи Kling"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from bot.services.kling_service import kling_service


async def check_task(task_id: str):
    """Проверяет статус задачи всеми доступными методами"""
    print(f"🔍 Проверка задачи: {task_id}\n")

    # Пробуем разные endpoint'ы
    methods = [
        ("Kling 3 (v3)", kling_service.get_v3_task_status),
        ("Kling 3 Omni", kling_service.get_omni_task_status),
        ("Kling 3 R2V", kling_service.get_r2v_task_status),
    ]

    for name, method in methods:
        try:
            result = await method(task_id)
            if result:
                print(f"✅ {name}:")
                print(f"   Status: {result.get('status', 'N/A')}")
                print(f"   Generated: {result.get('generated', [])}")
                if result.get("error"):
                    print(f"   Error: {result.get('error')}")
                print()
            else:
                print(f"❌ {name}: Нет данных\n")
        except Exception as e:
            print(f"⚠️ {name}: {e}\n")


if __name__ == "__main__":
    task_id = "0d14ba20-b018-43cd-84cb-18b14e4a013d"
    if len(sys.argv) > 1:
        task_id = sys.argv[1]

    asyncio.run(check_task(task_id))
