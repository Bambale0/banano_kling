# Admin model tariff coverage

Baseline: b07ab430 plus the independently reviewed Banana guard fix 3360967.
This is a separate follow-up branch, not a production configuration edit.

## Inventory and outcome

| User model | Existing charging source | Admin destination |
|---|---|---|
| Nano Banana Pro / 2 | shared 1K/2K/4K tariffs | existing resolution editor |
| Nano Banana 2 Lite | scalar image tariff | existing photo model editor |
| Seedream 4.5 Edit | scalar image tariff for all qualities | existing photo model editor; no invented quality multipliers |
| Seedream 5 Pro | previously hardcoded Basic 2 / High 2.5 | new Basic/High editor backed by optional seedream_5_pro_quality_costs |
| GPT Image 2, Wan 2.7, Grok image | scalar image tariffs | existing photo model editor |
| Kling 3 Standard/Pro, 2.5 Turbo | duration tariffs | existing video model editor |
| Grok video / 1.5 | duration and configured quality tariffs | existing video model editor |
| Gemini Omni video/audio/character | separate configured models; video quality tiers | existing video model editor |
| Veo Quality/Fast/Lite | configured quality tiers | existing video model editor |
| Motion Control 2.6/3.0, Motion Pro, Glow | configured quality or duration tariffs | existing video model editor |
| Seedance 2.0/2.5/Mini/Fast | supported quality schema, including unconfigured prices | existing video model editor |
| Kling Avatar Standard/Pro | previously shared-duration fallback | new visible 5-second billing-slot override; no invented per-second tariff |
| Higgsfield Genjutsu | versioned DB settings, 3 operations × 3 resolutions | existing authenticated management, now explicitly named Higgsfield and linked from Prices |

The base Mini App image/video catalog is checked against destinations by regression
test, including canonical aliases. Compatibility-added Seedance variants are
covered by the existing Seedance admin integration tests. Unknown future models
must still be added to their supported catalog/schema.

Avatar public Mini App catalog exposes only duration [5], and Telegram hides its
duration selector. The new editor only exposes that existing billing slot. It
does not equate provider audio length with a new price-per-second rule. Existing
stale/other duration requests retain the exact old fallback behavior.

## Settings scope

Higgs management already edits tariffs, public/admin launch switches, verified
operations, operational limits/timeouts/storage bounds and notification texts.
Its existing backend admin authentication, optimistic version check, price
validation and live-verification/public-release gates are unchanged. No duplicate
JSON tariff store or alternate save endpoint is introduced.

General admin already exposes packages, photo/video tariffs, partner exchange,
video-prompt pricing, prompts, promotions and the channel-subscription setting.
This patch does not claim that every code constant, provider credential or
infrastructure setting is editable. Credentials, role grants, provider setup and
unsupported generation options are deliberately outside this UI change.

## Preservation and authorization

Opening menus performs no price writes. Missing Seedream 5 keys use exactly the
previous effective Basic 2 / High 2.5, without persisting defaults. Explicit tier
save changes only that tier and refreshes shared charging dictionaries and loaded
Mini App metadata. Seedream 4.5 pricing is untouched. Avatar explicit save adds
only the selected 5-second override; all other fallback prices remain unchanged.
Seedance 2.5's existing 5/7/13 values remain untouched.

Both entry callbacks and final price submission check the existing admin
authority. Loss of admin status while waiting for input fails closed. No role
lists are changed.

## Verification and release

Focused tests cover Seedream defaults/config updates/invalid values, both charge
surfaces, live metadata refresh, callback allow/deny, final-save denial, Higgs
management link, Avatar display without writes and untouched-duration equality,
catalog destination coverage, Banana regression, Seedance integration and
deployment price preservation. Tests use isolated fake stores, not production
writes. Python compile and diff checks are required before handoff.

No paid generations, production price changes or deployment were performed.
Full CI and post-release verification remain the release owner's responsibility.

Review follow-up: Avatar updates reject non-finite/nonpositive values and report
reload failure instead of success. Seven targeted regressions failed before the
correction and passed afterward. List/detail labels consistently describe the
existing billing slot, and custom quality keys cannot shadow the Avatar edit
button. Actual menu-to-detail-to-edit callbacks and Seedream entry reachability
are now exercised. Final focused suite: 54 passed. Focused Ruff on the isolated
new tests, pricing module and compatibility handler passes; changed-line lint is
also run for legacy files before handoff.
