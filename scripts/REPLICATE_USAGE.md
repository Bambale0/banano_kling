Replicate prediction helper
==========================

This folder contains a small CLI helper to create Replicate predictions:

- `create_prediction.py` — CLI to call `replicate.predictions.create` and optionally wait for completion.

Quick start:

1. Install dependency:

```bash
pip install replicate
```

2. Export your API token:

```bash
export REPLICATE_API_TOKEN="your_token_here"
```

3. Run an example:

```bash
python scripts/create_prediction.py \
  --model "google/nano-banana-2" \
  --input-json '{"prompt":"An isometric diorama of a ramen shop","aspect_ratio":"1:1"}' \
  --wait 30
```

Or use an input file:

```bash
echo '{"prompt":"Hello"}' > input.json
python scripts/create_prediction.py --model "google/nano-banana-2" --input-file input.json
```

Notes:
- `--webhook` and `--webhook-events` are supported.
- `--cancel-after` accepts durations like `30s`, `5m`.
