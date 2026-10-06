# Seedance 2.5: explicit character replacement

## User-facing contract

The Mini App exposes a separate **Замена персонажа** choice. Ordinary **По референсам** generation remains unchanged and does not silently gain editing instructions.

Character replacement uses:
- one to three photos of the same person uploaded by the authenticated user, in the original order;
- exactly one source video, 4–30 seconds long, uploaded through the app;
- an optional additional user instruction.

The server adds a versioned APIX-derived role contract. `@Image1` supplies the primary identity and appearance. `@Image2` and `@Image3`, when present, only reinforce that same identity across angles. `@Video1` supplies motion, performance, camera, timing, framing, lighting, background and scene continuity. Its original actor's facial identity must not be retained or blended. This is model guidance, not a guarantee of perfect identity fidelity.

First/last-frame inputs and audio references are not part of this scenario. The UI keeps normal reference generation separate so that role assignment is explicit. A pasted prompt never changes the ordinary scenario into identity transfer by itself.

## Provider boundary

The provider remains KIE `bytedance/seedance-2-5` through the existing create-task adapter. Image and video arrays remain `reference_image_urls` and `reference_video_urls`. The identity flag and role version are application metadata, not invented provider fields. Editing uses `duration=-1` and `aspect_ratio=adaptive` so output follows the source. No Neironych, Nexus or Higgsfield migration is involved.

Own-task repeats obtain identity mode and ordered inputs through authenticated owner-only task detail, not public feed metadata. Each repeat obtains a fresh quote; leaving identity clears the recipe lineage and explicit empty input arrays are never filled from old media. The original user instruction remains the reusable instruction. The generated role contract is composed at the provider boundary and checked against the final prompt limit before debit. Reference order and `@ImageN` / `@Video1` numbering must match the final arrays.

## Paid launch safety

Provider auto-duration and billable duration are different values. The server must measure the authenticated user's managed source upload, require a finite 4–30 second duration, and use its ceiling as the billable seconds with existing preset-manager rates and the existing video-reference price multiplier applied exactly once. No new tariff or 30-second placeholder price is introduced.

Quote-only requests must not debit, create a task or call a generation provider. A launch revalidates media ownership, canonical local containment, measured duration, resolution, repeat lineage and current price. A missing/stale quote requires recalculation and another explicit Start. An unverifiable external URL is rejected before debit; client-supplied duration or cost is never authoritative.

Identity transfer does not grant general public access to unrelated Auto/video-edit modes. Existing admin-free handling remains separate. Provider failure must not silently create a second paid task.

## Verification and release

Use synthetic assets and mocked providers for regression tests: ordinary reference versus identity payload, 1/2/3 ordered identity photos, invalid counts, frame/audio contamination, oversized expanded prompts, foreign or traversal source paths, unknown/non-finite/out-of-range duration, stale quote/current-rate changes, paid launch/debit consistency, repeat restoration and no automatic retry. Mobile QA must cover mode switching, pending uploads, stale-quote recovery and narrow layouts.

This document describes the task-branch contract. Production availability requires the authorized release and exact deployed-SHA verification; passing mocked tests does not prove model quality on real media.
