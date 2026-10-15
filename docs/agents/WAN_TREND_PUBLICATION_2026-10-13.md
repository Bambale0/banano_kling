> **Историческая задача:** новые опубликованные результаты Wan (включая те, что
> сами запущены из тренда) должны повторяться **по собственной сохранённой работе**,
> не подменяться исходным трендом. Текущий контракт:
> [PUBLISHED_REPEAT_CONTRACT.md](../PUBLISHED_REPEAT_CONTRACT.md).

# WAN manual trend publication

Scope: ordinary WAN 3 and Prime manual publisher, owned durable recipe references, safe repeat-unavailable UI, visible model selection, user-facing error sanitization. No historical trend reactivation, tariff edits, paid provider calls, or PR294 changes.

## Implementation

- Shared WAN submit helper is used by the base MiniApp handler and both compatibility installers. Generic publication cannot create a WAN public row without its private typed recipe.
- Model, prompt, source slot roles and explicit replacement keys are validated. Surrounding prompt whitespace is canonicalized identically at both boundaries.
- Storage lock covers ownership/digest validation and one transaction inserting public metadata plus private recipe. Failed second insertion rolls back the first; replay does not reactivate deactivated publications.
- Existing recipe retention pins owned reference media. Public metadata excludes the private prompt and source URLs.
- Manual editor uses owned WAN uploads, explicit fixed/replacement choices and model-bound sessions. Unsupported links and user fields are rejected explicitly.
- Both model keys remain distinct and visible on the first selector page. Failed or mismatched repeat/owner recipes block quote and launch with an explicit retry.
- User-facing WAN status/errors omit internal provider identifiers and raw upstream error text. Unexpected publication failures return fixed localized text.

## Verification ledger

- Pure publication contract: 6 PASS
- SQLite transaction harness: 8 PASS (includes five contract cases)
- Isolated actual chunk route: 12 PASS
- Isolated ordinary WAN contract: 9 PASS
- Full frontend Jest: 447 PASS across 59 suites; TypeScript PASS
- Local serialization tests use the previously approved extracted submitPrompt fixture (WAN_SUBMIT_FIXTURE=1); official CI checks the live declaration. No broader restricted source read is needed locally.
- Full checkout TypeScript: PASS
- Changed-line Ruff: 0 relevant violations; legacy violations excluded by the existing gate
- Full application/HTTP and PostgreSQL checks run only in official CI. The protected database adapter was not read or imported locally.
- Initial official CI exposed compatibility-handler dispatch and response-contract fixture failures. These were fixed with installer-parametrized tests; earlier focused green checks were not treated as end-to-end proof.
- Existing upload cancellation/retry assertions remain intact. Same-context equal/changed preset restores during unknown launches preserve the exact frozen request; effective explicit source IDs take precedence over fallback IDs. All related regressions pass.

## Release constraints

Require exact-head independent review, full required CI and the user-facing pre-release report before merge. Real iPhone upload/publish/repeat checks remain a post-release user smoke; no paid generation is represented as tested. Rows 2040/2043 remain untouched. Playbook repository refresh was previously denied; existing guidance was used without bypassing that restriction.
