# #451 — VK photo remixes from the PUBLIC feed, distinct from editorial trends

Status: **incremental, review-only; feature flag defaults OFF**. This does not
complete the ten-domain shared application contract or authorize switching it ON.

## Root cause

The VK Mini App previously allowed public feed browsing but its public cards
returned `can_repeat_in_app=false` unconditionally. Deep links to
`#remix_<generation-id>` displayed an explanatory dead end. Editorial prompt
IDs used by `vk-trend` are **not** generation IDs from the feed, and must never
be sent to the trend route or grant access to another creator's hidden inputs.

## New separately protected operation

`POST /mini-app/api/account-preview/vk-feed-repeat` accepts only:
`feed_gen_id`, `reference_urls`, `quote_only`, `client_request_id`, and
`expected_cost`. A signed, unlinked native VK actor is mandatory; both
`VK_MINIAPP_FEED_REPEAT_ENABLED=1` and `VK_MINIAPP_WRITES_ENABLED=1` are
required. Both quote and submit:
1. re-read the public feed card with viewer ID `None`, applying creator
   visibility, moderation, publish scope and recipe privacy;
2. allow only explicitly visible public image prompts, supported native photo
   models, unblurred available public feed items;
3. use a server-only source recipe and dynamically verified VK model ratios,
   resolution and per-model maximum reference count;
4. accept **only the signed VK actor's new image uploads** as references;
   never reuse source creator's original reference media;
5. quote and submit through the existing native VK SQLite ledger and
   idempotent claim. Ambiguous responses are read through
   `vk-generation-claim`; no automatic paid POST or new key;
6. serialize no source prompt, source references, user IDs or worker pricing
   in public feed responses.

The browser may open an ordinary Feed card or an external `#remix_ID` link.
The repeat button only appears with server-confirmed `can_repeat_in_app`.
It is explicitly **not** a permission to repeat private, blurred,
video-based, hidden-prompt or editor-only recipes.

## Rollout and follow-ups

No flag is enabled by this PR. Before enabling, use a real signed VK WebView:
validate source toggle to private between quote/submit, owner-scoped uploads,
native price drift/402/409, single debit/task on unknown provider response,
reconciliation and refund, VK delivery, history, and absence of TG ledger
writes. Then enable the separate flag with an exact-SHA deploy and smoke.

Video feed remixes with creator-protected source videos, audio, Genjutsu,
Seedance and private author media require their own native owned-reference
contract. VK-owned publication and creator cross-ledger rewards are separate
outstanding work. Never claim full VK parity from this photo-only slice.
