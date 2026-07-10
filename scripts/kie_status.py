#!/usr/bin/env python3
import asyncio
import json
import os

import aiohttp

KIE_AI_API_KEY = os.environ.get("KIE_AI_API_KEY")
BASE_URL = "https://api.kie.ai/api/v1"


async def get_task_status(task_id):
    headers = {"Authorization": f"Bearer {KIE_AI_API_KEY}"}
    params = {"taskId": task_id}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{BASE_URL}/jobs/recordInfo", headers=headers, params=params
        ) as resp:
            print(f"Status {resp.status}")
            result = await resp.json()
            print(json.dumps(result, indent=2))
            return result


if __name__ == "__main__":
    task_id = "cbf1814f63c4799585ac8b5cefce26e1"
    asyncio.run(get_task_status(task_id))
