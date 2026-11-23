# Wan 3.0: delivery of large Telegram results

Wan video generation and billing complete before Telegram delivery. A Telegram
transport failure must not create another paid provider request or refund a
successfully completed result.

## Delivery policy

* The durable original lives under `/uploads/wan3_prime/results/<task_id>.mp4`;
  that URL is served through the application's S3-backed media resolver.
* If the retained local file is larger than
  `WAN3_TELEGRAM_MAX_INLINE_VIDEO_BYTES`, send a Telegram message with the
  **Скачать оригинал** button instead of uploading the video.
* The default preflight limit is **48,000,000 bytes**, conservatively below the
  public Telegram Bot API's typical video-upload limit. Override it through the
  environment if the bot transport's actual limit differs.
* For S3-only files whose local size is unavailable, an explicit
  `TelegramEntityTooLarge`, HTTP 413, or `file is too big` response
  triggers the same download-link fallback.
* A timeout, lost connection, or missing Telegram receipt is **uncertain**,
  not an explicit media-size rejection. Do not automatically send a second
  message after an ambiguous result: it may duplicate a successful send.

## Durable delivery state

* A successful `send_message` response is persisted as `link_sent` with
  `delivery_message_id` and `delivery_link_sent=True` in generation metadata.
* `link_sent` is terminal for automatic delivery polling. Do not retry video
  uploads or send repeated link messages for this same task.
* A failed link send remains classified through standard Telegram handling.
* Never re-run generation, bill again or refund because a successful result
  could not be attached inline to a Telegram message.

## Operational checks

1. Confirm `wan3_prime_intents.status=completed` and `settled=1`.
2. Confirm the original URL is downloadable (a HEAD request can be rejected by
   S3 while a ranged GET succeeds).
3. Check `delivery_status` and `delivery_message_id`.
4. For historical `uncertain` states, reconcile manually. Automatic replay
   remains disabled because the Telegram acknowledgement may have been lost.
5. Regression tests: `pytest -q tests/test_wan3_prime_delivery_links.py`.
