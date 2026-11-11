# VK Mini App: editorial trends vs public feed repeats

## Distinct namespaces — mandatory for platform parity

NEUROMIX has two unrelated ID domains. Matching integer values never imply
the same object, author, media, price, consent, or original prompt.

| Entry | Domain | Source | Navigation | Paid operation |
|---|---|---|---|---|
| prompt_42_ref_CODE | Editorial trend | approved and visible user_prompts | trend detail | authorized trend recipe, trend_id |
| feed_42_ref_CODE | Public feed | published generation_tasks | publication preview | separately authorized feed repeat, source_feed_gen_id |
| remix_42_ref_CODE | Feed repeat intent | same public generation | repeat composer | quoted backend repeat, source_feed_gen_id |

The ref_CODE suffix is attribution, never authorization for a recipe or balance.

## Verified sample

https://vk.com/app54880352#feed_370766_ref_27QT0YCB points to public
Seedance 2.5 VIDEO generation ID 370766, not editorial prompt. The public
result URL and preview MP4 returned HTTP 200 from neuromixbot.com.

The original prompt and references are hidden. However the existing
Telegram FeedTab can use sourceFeedGenId and a secure backend to repeat
a publication without exposing its source recipe. Therefore hidden
prompt is NOT proof that a secure repeat is forbidden. The public
viewer endpoint cannot grant paid repeat access by itself.

## Separate read APIs, signed VK session

- GET /mini-app/api/account-preview/trends?view=item&trend_id=42:
  approved/visible editorial prompt, sanitized, prompt_42 link.
- GET /mini-app/api/account-preview/trends?view=feed_item&gen_id=42:
  public feed item, sanitized public media, feed_42 link. No
  private prompt, hidden image/video references, private task
  ID or billing/creator secrets.

Both verify the VK session and do not impersonate Telegram.

## Remaining parity gates

A single shared MiniAppShell/FeedTab across VK and Telegram requires
native VK bootstrap, actor-owned feed and public feed detail, feed
repeat quoting/charging, native SQLite wallet idempotency, references,
provider reconciliation and author privacy checks. Keep sourceFeedGenId
and editorial promptId separate. This change is read-only navigation
infrastructure; it is not full 1:1 parity and cannot charge for remixes.

Do not add an unrelated VK frontend and do not silently migrate wallets.
