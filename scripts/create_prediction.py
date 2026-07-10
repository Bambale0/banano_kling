#!/usr/bin/env python3
"""
Create a prediction on Replicate from the command line.

Requirements:
- Set environment variable `REPLICATE_API_TOKEN` with your API token.
- `pip install replicate`

Examples:
  python scripts/create_prediction.py \
    --model "google/nano-banana-2" \
    --input-json '{"prompt":"A cozy ramen shop at night","aspect_ratio":"1:1"}' \
    --wait 30

  python scripts/create_prediction.py --model "google/nano-banana-2" --input-file ./input.json --webhook https://example.com/webhook

"""

import argparse
import json
import os
import time

try:
    import replicate
except Exception as e:
    raise SystemExit("Install the replicate package (pip install replicate)") from e


def create_prediction(
    client,
    model: str,
    input_obj: dict,
    webhook: str = None,
    webhook_events_filter=None,
    cancel_after: str = None,
):
    kwargs = {"model": model, "input": input_obj}
    if webhook:
        kwargs["webhook"] = webhook
    if webhook_events_filter:
        kwargs["webhook_events_filter"] = webhook_events_filter
    if cancel_after:
        kwargs["cancel_after"] = cancel_after

    pred = client.predictions.create(**kwargs)
    return pred


def wait_for_prediction(client, prediction_id: str, timeout: int = 60):
    start = time.time()
    while True:
        p = client.predictions.get(prediction_id)
        status = getattr(p, "status", None) or (
            p.get("status") if isinstance(p, dict) else None
        )
        print(f"status={status}")
        if status in ("succeeded", "failed", "canceled"):
            return p
        if timeout and (time.time() - start) > timeout:
            print("Wait timeout reached")
            return p
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Create a Replicate prediction")
    parser.add_argument(
        "--model", required=True, help="Model name (example: google/nano-banana-2)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input-json", help="JSON string input for the model")
    group.add_argument("--input-file", help="Path to JSON file containing input object")
    parser.add_argument("--webhook", help="Webhook URL to receive updates")
    parser.add_argument(
        "--webhook-events",
        nargs="*",
        help="Webhook events filter (start output logs completed)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        help="Wait up to N seconds for prediction to finish (0 = don't wait)",
    )
    parser.add_argument(
        "--cancel-after", help="Max lifetime for prediction (e.g. 30s, 5m). Minimum 5s"
    )
    args = parser.parse_args()

    token = os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        raise SystemExit("REPLICATE_API_TOKEN environment variable is required")

    client = replicate.Client(api_token=token)

    if args.input_json:
        input_obj = json.loads(args.input_json)
    else:
        with open(args.input_file, "r", encoding="utf-8") as f:
            input_obj = json.load(f)

    pred = create_prediction(
        client,
        args.model,
        input_obj,
        webhook=args.webhook,
        webhook_events_filter=args.webhook_events,
        cancel_after=args.cancel_after,
    )

    # Print created prediction id and initial state
    try:
        pred_id = getattr(pred, "id", None) or (
            pred.get("id") if isinstance(pred, dict) else None
        )
    except Exception:
        pred_id = None

    # Attempt to print prediction object as JSON-friendly dict
    try:
        printable = dict(pred)
    except Exception:
        try:
            printable = pred._asdict()  # fallback for some clients
        except Exception:
            printable = str(pred)

    print(json.dumps({"prediction": printable}))

    if args.wait and pred_id:
        finished = wait_for_prediction(client, pred_id, timeout=args.wait)
        print("Final prediction:")
        try:
            print(json.dumps(dict(finished)))
        except Exception:
            print(finished)


if __name__ == "__main__":
    main()
