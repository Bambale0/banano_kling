# Multimodal AI Generation Platform

> **Production image/video AI platform** · Telegram · FastAPI · aiogram · provider orchestration · payments · generation history · automated tests
>
> Repository codename: `banano_kling`.

This project is a production Telegram AI platform focused on image and video generation across multiple external providers. It implements the full generation lifecycle: model selection, media/reference validation, task creation, asynchronous completion, billing, refunds, result delivery, history and admin operations.

## Engineering highlights

- Telegram bot built with aiogram.
- FastAPI webhook application.
- Multiple image and video provider adapters behind service modules.
- Text-to-image and image-to-image workflows.
- Text-to-video, image-to-video, talking avatar and motion-control workflows.
- Saved references and repeat-generation flows.
- Generation task/history persistence.
- Balance, payments, referrals and partner withdrawals.
- Provider callbacks/webhooks and polling fallback paths.
- Automated regression and live-smoke tests.
- Production-oriented error handling and credit refunds.

## AI integrations

The repository contains integrations for several model families, including:

### Image

- Nano Banana / Nano Banana Pro
- GPT Image
- Seedream
- Grok Imagine
- Gemini-based image workflows

### Video

- Kling 2.5/3.x generation
- Kling AI Avatar
- Kling Motion Control
- Veo 3.x
- Grok video workflows

Provider-specific requirements are handled in dedicated services instead of being spread across user-facing handlers.

## Generation lifecycle

```text
User
  |
  v
Telegram flow
  |
  +--> validate model / references / parameters
  +--> calculate cost
  +--> reserve/debit balance
  |
  v
provider adapter
  |
  +--> create external task
  +--> save internal task state
  |
  v
callback / polling
  |
  +--> success --> save result --> deliver media --> history
  |
  +--> failure --> mark failed --> refund when applicable
```

## Repository structure

```text
bot/
├── handlers/          # user/admin generation flows
├── services/          # provider and business-service adapters
├── database.py        # users, balances, generation state/history
├── keyboards.py
├── states.py
└── main.py            # application/webhook entry point

tests/
├── provider contracts
├── database tests
├── generation helpers
├── webhook tests
└── live/              # opt-in paid/provider smoke tests
```

## Reliability principles

The platform assumes external AI providers can time out, reject payloads or finish asynchronously. The implementation therefore separates local task state from provider state and includes:

- explicit task IDs and statuses;
- callback/polling completion handling;
- validation before paid task submission;
- human-readable provider errors;
- refund paths for failed generation;
- isolated provider clients;
- opt-in live tests so CI does not accidentally spend provider credits.

## Stack

| Area | Technology |
| --- | --- |
| Backend | Python, FastAPI, aiogram |
| AI integration | KIE.AI and provider-specific APIs |
| State | persistent users, transactions and generation history |
| Payments | Crypto/payment provider adapters |
| Delivery | Telegram webhooks + provider callbacks |
| Tests | pytest + provider contract/live smoke suites |

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
pytest
```

Live provider smoke tests are intentionally opt-in because they create real external tasks and can spend credits.

## Portfolio note

This repository is included as the **AI integration/orchestration** case in the portfolio. The main value is the amount of provider-specific behavior normalized into one customer product: different model contracts, reference requirements, asynchronous APIs, billing rules and failure modes are exposed through a consistent UX and task lifecycle.
