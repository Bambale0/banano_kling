# Telegram-only Mini App release: retired VK DNS must not block publication

## Production incident confirmed on 17 November 2026

Git SHA on Docker `banano-kling-bot` and `origin/tanyapi`: `af96e57e`.
Public Telegram Mini App `https://neuromixbot.com/mini-app/revision.txt`:
`4d52b94b`, unchanged since the earlier frontend rollout. The host's retired
`vk.neuromixbot.com` has no resolvable A record. Before this fix,
`scripts/deploy_miniapp_local.sh` performed unconditional VK `/revision.txt`
and `/` DNS/HTTP preflight **before building or publishing Telegram UI**.
Under `set -Eeuo pipefail`, the failed curl substitution aborts the script.
The script also invoked the VK mode verifier after Telegram publication.
This explains why updating the Docker backend alone could leave UI stale.

## Fix and safety gates

- Default `VK_MINIAPP_DEPLOY_ENABLED=0` means *no VK DNS, HTTP probes, builds,
  media-route edits, filesystem publishing or post-deploy verification*.
- `VK_MINIAPP_DEPLOY_ENABLED=1` explicitly preserves previous VK behavior
  including required preflight, intended HTTP 410 isolation, and live verification.
  All other values fail before networking or any production side effects.
- Retain exact-SHA Telegram static revision gate, required hashed chunk checks,
  read-only backup policy and existing production deployment constraints.
- TDD red: two new regressions failed on the old script, including a fake
  DNS/curl exit 6 and unconditional final VK smoke. Green: 48 focused tests
  on the new script, including VK enabled/disabled scenarios and existing
  production URL/backup/API contract tests. `bash -n` and Ruff passed.
- Local tests do not prove public production revision updated. Release is
  successful only after protected CI, exact-SHA container & public static
  revision match, signed admin Astro smoke and anonymous 401/403, with no
  user balances affected. Verify after deployment.

Scope: `tanyapi` production only. Do not touch any unrelated host/domain.
This follows project AGENTS.md and relevant `.agents` TDD, debugging and
verification guidance.
