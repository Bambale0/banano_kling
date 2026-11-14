# VK #451: shared public feed likes under native VK identity

Status: **feature-flagged, review only**. This PR does not enable full parity or
mutate native VK wallet balances.

## Problem and design

Telegram feed likes currently key `feed_generation_likes.user_id` to the
Telegram app's internal `users.id`. An independent VK-only person has no
Telegram actor; manufacturing one is unsafe and violates #451.

The VK-only path `POST /mini-app/api/account-preview/vk-feed-like` accepts
only `{"feed_gen_id": <positive integer>}`, authenticates a revocable VK
bearer, derives the author from the signed session, and never accepts user
IDs, TG initData or client-side ownership assertions.

A separate `vk_feed_generation_likes` table records
`(vk_user_id, generation_task_id)` with an immutable uniqueness constraint
and FK cascade on publication removal. An insertion against a completed,
public, non-adult publication and increment of the canonical
`generation_tasks.likes_count` occur in a single transaction. Duplicate
clicks, HTTP retries and overlapping requests do not increment twice.
The existing public TG feed already reads `likes_count`, so both VK and TG
visitors see the same total, without mixing actors or wallets.

The public VK feed list and deep-linked card advertise
`can_like_in_app` ONLY when `VK_MINIAPP_FEED_LIKES_ENABLED=1`. It defaults
OFF; a denied action cannot pass through to Telegram's legacy endpoints.

## Verification, rollout and limitations

Unit/integration regressions: owner-only signature, repeated and concurrent
VK likes, linked Telegram actor still uses the VK identity, stale/private/adult
source denial, no pseudo-Telegram row, failed write surfaces clear error,
visibility toggles and VK signed client transport.

Before enabling: protected SQLite and PostgreSQL DB regression, CI, actual
signed VK WebView 401/403 and duplicate-click smoke, race against unpublish,
exact-SHA deployment and production verification.

Comments/reactions from profiles, VK-owned publication creation and combined
VK/TG notification delivery are **separate outstanding #451 work**. This PR
does not declare completion of the ten-domain `full_vk_adapter()` matrix.
