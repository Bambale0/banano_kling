# Genjutsu ordinary Feed UI
Baseline: f70f84738981f145c630265664e87913437a1bb9; isolated feature/genjutsu-feed-ui.

## Preflight and scope
Existing completed run history has download/edit/redelivery but no ordinary Feed publication. Existing private recipes already collect user video/photo slots and quote server-side. Feed and profile repeat currently route all videos through generic video model fallback.
Backend worker owns feed_publish and the opaque recipe/card link. UI reuses that contract without sending prompts or original asset IDs.
Public test seams: React publication and feed/profile repeat; static-export browser journey with all API/media mocked. No paid/provider calls or real publication.
No pricing, database, provider, configuration or admin changes in this frontend branch.
Preserve concurrent PR251 input revision, quote invalidation, trim and source hydration changes when integrated.

## Acceptance and progress
1. [x] RED owner publication and repeat routing regressions
2. [x] Per-final-output user/fixed video selection and immutable photo binding summary
3. [x] Feed/profile opaque recipe repeat routing
4. [x] Jest, types, lint, production export, offline mobile browser fixtures
5. [ ] Parent integration and exact-SHA CI; no production claims here

Skills: current Bambale0/skills TDD (public-seam vertical slice), Bambale0/claw frontend-qa (responsive/error/disabled states), anthropics/skills webapp-testing (headless browser lifecycle). Repository test conventions take precedence over generic helpers.

## Verified 2026-10-06
- RED: owner publication regression failed before the component existed.
- Full Jest: 28 suites / 111 tests passed, including publication eligibility, immutable reference policy, duplicate clicks, lost-response idempotency, permanent withdrawal errors, late unmounted results, opaque Feed routing and malformed linkage fail-closed behavior.
- TypeScript no-emit, full ESLint, production static export and git diff --check passed.
- Offline Chromium on the real export passed at 320/360/390/430 px: both final variants expose publication; title/source fields remain within viewport; fixed/user policies and cancel/reopen preserve intent; exact publication payload; Feed and Profile route to the recipe; own video and photo upload precede a server quote; all-variant cost is explicit; no hidden prompt/fixed photo inputs; previews close on handoff; no browser exceptions.
- Fixture network routing mocks every API/media request, blocks unrecognized external hosts, and rejects generation/start actions. No live accounts, publications, uploads or paid generations used.
- A generated 2.3 KiB one-second navy MP4 is committed as test-only media to avoid requiring ffmpeg in CI. critical-flows.mjs imports this fixture, so all existing browser CI gates include it.
- 360px repeat screenshot visually checked: bounded photo/video form, visible quote and no overlap with Close. Screenshots remain local test artifacts.
- Owner authorization is enforced by the existing owner-scoped run API and backend publication endpoint; frontend hides private/redacted/incomplete/non-final runs. This branch has no migrations or operational configuration changes.
- Parent must cherry-pick onto PR251/current tanyapi, preserve source hydration and quote/range fences, run integrated browser/backend/CI checks, then verify exact deployed SHA. This frontend branch does not claim production deployment.
