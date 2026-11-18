# Astro live retry recovery — 2026-11-18

## Production reproduction
- Previously deployed SHA: 0b039ca2590dfa0acd71b6df77b3bd1367bee128.
- Existing failed natal job returned HTTP 200 with true failed status.
- Explicit owner retry returned 409 despite consent because the old manual retry ledger was already used.
- Paid synthetic KIE test responses had 854 and 1057 words but failed local unsupported_claim due to unverifiable degrees. An exact-feedback retry produced 989 words and passed the fact checker.

## Targeted changes
- Preserve encrypted owner-scoped dedup and checkpoints; no automatic paid job replay.
- Configurable maximum manual retries (default two), additive durable budget table retaining legacy retry history, conditional SQL update protects against duplicate taps and races.
- Expose safe retry availability in API and show only actionable retry controls in Mini App.
- Re-arm failed Telegram outbox on a new terminal failure of an explicitly restarted job, leaving successful PDF delivery immutable.
- Send explicit unsupported degree/date values to KIE for a grounded rewrite without weakening the proof gate.

## Tests
- Regression tests failed on old behavior; Python and Mini App tests passed after fix.
- QA PostgreSQL queue claimed exactly one job among eight concurrent workers.
- PDF delivery and exact production deploy require additional confirmation.
- Test birth details synthetic. No production owner jobs, balances or Telegram chats were modified.

## Release
- Only PR to protected tanyapi, required CI, production autodeploy, exact Docker SHA and smoke; do not touch main, dev or unrelated domains.
