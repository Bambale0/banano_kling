#!/usr/bin/env python3
"""
CLI for Kie.ai /api/v1/jobs/createTask - Nano Banana 2 migration.
Requires KIE_API_TOKEN env var.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.services.kie_service import kie_service


async def main():
    parser = argparse.ArgumentParser(description="Create Kie.ai task")
    parser.add_argument("--model", default="nano-banana-2", help="Model name")
    parser.add_argument("--input-json", help="JSON input string")
    parser.add_argument("--input-file", help="JSON input file")
    parser.add_argument("--callback-url", help="Webhook callback URL")
    args = parser.parse_args()

    token = os.environ.get("KIE_AI_API_KEY")
    if not token:
        print("ERROR: Set KIE_AI_API_KEY env var")
        sys.exit(1)

    if args.input_json:
        input_data = json.loads(args.input_json)
    elif args.input_file:
        with open(args.input_file) as f:
            input_data = json.load(f)
    else:
        input_data = {}

    result = await kie_service.create_task(
        model=args.model, input_data=input_data, callback_url=args.callback_url
    )
    print(json.dumps(result or {}, indent=2))


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
