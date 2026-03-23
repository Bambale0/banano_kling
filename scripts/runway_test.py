#!/usr/bin/env python3
"""
Simple script to send a prompt + reference to Runway (via replicate) using
the project's RunwayService and optionally wait for completion.

Usage:
  python scripts/runway_test.py --prompt "A cinematic shot" --image-url https://example.com/ref.png --wait

You can pass --token or set REPLICATE_API_TOKEN in the environment. If WEBHOOK_HOST
is set in environment/config and you prefer webhooks, you can omit --wait and
configure replicate to call your webhook endpoint; otherwise use --wait to poll.
"""
import argparse
import asyncio
import json
import logging
import os
import pathlib
import sys

# Ensure project root is on sys.path so 'bot' package can be imported when running
# this script directly (e.g., python scripts/runway_test.py)
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.services.runway_service import RunwayService

logger = logging.getLogger("runway_test")


async def main(args):
    token = args.token or os.getenv("REPLICATE_API_TOKEN")
    if not token:
        logger.warning("No REPLICATE API token provided. The request may fail.")

    svc = RunwayService(api_token=token)

    # Build call parameters
    kwargs = {
        "prompt": args.prompt,
        "duration": args.duration,
        "aspect_ratio": args.aspect,
    }
    if args.image_url:
        kwargs["image_url"] = args.image_url
    if args.reference_image_url:
        # pass a single reference as URL
        kwargs["reference_image_urls"] = [args.reference_image_url]

    if args.webhook_url:
        kwargs["webhook_url"] = args.webhook_url

    logger.info("Creating Runway prediction with: %s", kwargs)
    result = await svc.generate_video(**kwargs)

    print("Create result:")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # If we received a task id and user requested to wait, poll until completion
    task_id = None
    if isinstance(result, dict):
        task_id = result.get("task_id")

    if task_id and args.wait:
        logger.info("Waiting for completion of task %s...", task_id)
        status = await svc.wait_for_completion(
            task_id, max_attempts=args.max_attempts, delay=args.delay
        )
        print("Final status:")
        print(json.dumps(status, indent=2, ensure_ascii=False))


def parse_args():
    p = argparse.ArgumentParser(
        description="Send a prompt + reference to Runway/Replicate"
    )
    p.add_argument("--prompt", required=True, help="Text prompt for generation")
    p.add_argument("--image-url", help="Start image URL (for imgtxt) or primary image")
    p.add_argument(
        "--reference-image-url", help="Additional single reference image URL"
    )
    p.add_argument("--duration", type=int, default=5, help="Duration in seconds (5-10)")
    p.add_argument("--aspect", default="16:9", help="Aspect ratio e.g. 16:9, 9:16")
    p.add_argument(
        "--token", help="Replicate API token (overrides env REPLICATE_API_TOKEN)"
    )
    p.add_argument(
        "--webhook-url",
        help="Explicit webhook URL to pass to Replicate (overrides config)",
    )
    p.add_argument(
        "--wait",
        action="store_true",
        help="Poll until completion using RunwayService.wait_for_completion",
    )
    p.add_argument(
        "--max-attempts", type=int, default=60, help="Max polling attempts when --wait"
    )
    p.add_argument(
        "--delay", type=int, default=5, help="Polling delay seconds when --wait"
    )
    p.add_argument("--log-level", default="INFO")
    p.add_argument(
        "--simplify",
        action="store_true",
        help="Simplify the prompt before sending: keep first sentence or first 6 words",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    try:
        # Optionally simplify prompt before running
        if args.simplify:
            # Keep first sentence if present, otherwise first 6 words
            text = args.prompt.strip()
            if "." in text:
                args.prompt = text.split(".", 1)[0].strip()
            else:
                args.prompt = " ".join(text.split()[:6])
            logging.getLogger("runway_test").info(
                f"Using simplified prompt: {args.prompt}"
            )

        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        sys.exit(1)
