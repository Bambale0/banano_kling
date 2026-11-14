# VK #451 — public feed publication share links

This change enables the existing VK-only feed list to share public posts through
the same VK Mini App route used by a published feed item, without TG linking.

## Correct identity and namespace

A server-side `vk_public_discovery(view=feed)` read requires a valid bearer
for a VK platform actor and queries only viewer-neutral public feed rows with
`include_unavailable=False`. It constructs a VK Mini App link with the
policy-verified `vk_app_id` and optional verified `vk_community_id` via
`bot.miniapp_links.feed_link`. The fragment is `#feed_<generation_id>`,
**not** `#prompt_<trend_id>`, `#remix_<generation_id>`, or a Telegram link.

The client verifies the exact link shape, host and ID before presenting a
copy field. Clicking the feed-share action never requests a quote, paid remix,
private prompt, reference assets, Telegram wallet or partner attribution.

A shared link opens the existing `fetchVkPublicFeedItem` read-only path;
the backend still applies the public publication ACL before returning media.
The copy field remains usable when navigator.clipboard is unavailable.

No backend feature flags, pricing or DB migrations change. This is a
read-only public-sharing improvement, not full feed publishing, likes,
comments or video remix parity.

Regression tests cover the signed feed source, configured community suffix,
missing VK application, non-disclosure of private inputs, the public
publication link and rejection of spoofed/foreign/cross-namespace links.

Release requires CI, exact-SHA deployment and a live VK WebView deep-link smoke.
