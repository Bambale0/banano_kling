# One Mini App shell, independently authenticated on VK and Telegram

The product requirement is one shared MiniAppShell/TabContent with the same
eight tabs and functional parity, including paid generation, payment,
publishing, tasks, media, services and partner features.

## Confirmed former issue

AccountPlatformEntry selected the full application by telegram_linked.
This incorrectly treated optional identity linking as a prerequisite for
core product access. The unlinked VK path instead rendered a separate
VkStandaloneDiscovery. Independently, bot/miniapp.py common endpoints
still depend on a linked Telegram ID and would fail if the frontend
simply skipped this check.

## Safe release contract

An authenticated shared account response now includes a server-owned
full_app_ready boolean. A VK-only session may mount the exact same
MiniAppShell/TabContent when (1) explicitly enabled by the server
configuration and (2) the server application has registered ready
adapters for all operation domains:

bootstrap, photo, video, motion, trends, feed, services, profile,
payments, referrals and tasks.

This is a SERVER contract: neither client identity fields nor signed
VK launch query can claim all adapters are ready. The existing linked
VK studio and Telegram entry remain backward compatible.

By default VK_FULL_APP_PARITY_ENABLED is not set, and full_app_ready
is False for VK-only users. The feature must stay off until each
adapter is genuinely functional, including VK native balance and
payments. This code does NOT itself implement the adapters.

## Non-negotiable flow isolation

Editorial prompt_ID and paid trend repeats are separate from feed_ID
publication previews and remix_ID/feed source remixes. The latter
must check source generation, author-hidden prompt/references,
native actor and idempotent wallet debit without copying private
recipe data to a browser. Matching numeric IDs are not equivalent.

Keep the native VK wallet authoritative; never invent a Telegram
ID or silently transfer assets, credit or referral rewards. Account
linking remains an optional user operation.

## E2E release gates

Both messenger launch signatures, all eight tabs, all paid and free
operations, photo/video/motion, reusable media, trend-vs-feed repeats,
payment/referral ledgers, duplicate webhook/retry behavior, delivery,
privacy, error states, native VK WebView and Telegram smoke must pass
before advertising complete parity.
