#!/usr/bin/env python3
import argparse
import asyncio
import json
import os

import aiohttp

BASE_URL = "https://api.kie.ai/api/v1"
KIE_API_KEY = os.environ.get("KIE_AI_API_KEY")


async def create_kie_task(model="nano-banana-2", input_data=None, callback_url=None):
    if not KIE_API_KEY:
        print("ERROR: Set KIE_AI_API_KEY")
        return

    payload = {"model": model, "input": input_data or {}}
    if callback_url:
        payload["callBackUrl"] = callback_url

    headers = {
        "Authorization": f"Bearer {KIE_API_KEY}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/jobs/createTask", json=payload, headers=headers
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                print(json.dumps(result, indent=2))
                return result
            else:
                text = await resp.text()
                print(f"ERROR {resp.status}: {text}")
                return None


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--aspect-ratio", default="auto")
    parser.add_argument("--resolution", default="1K")
    parser.add_argument(
        "--callback-url", default="https://vkkling.chillcreative.ru/webhook/kie"
    )
    args = parser.parse_args()

    input_data = {
        "prompt": args.prompt,
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution,
        "image_input": [],
        "output_format": "png",
    }

    await create_kie_task(input_data=input_data, callback_url=args.callback_url)


if __name__ == "__main__":
    asyncio.run(main())
