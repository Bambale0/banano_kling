# Telegram video preview geometry — 2026-11-05

Baseline: 03a9918d (tanyapi).
Goal: send generated video previews with the actual display geometry of their file.
Audit: the reported Seedance result is 720x1280, SAR 1:1, duration 12.064s; ordinary result delivery omits width/height. The admin test lab already probes geometry including SAR and rotation.
Plan: reproduce through the ordinary result webhook; share the probe; supply dimensions for URL and downloaded-file delivery; verify tests and production rollout.
No database, price, provider routing or public API changes. Geometry comes from media, never requested aspect ratio.
Verification pending.

Implementation: shared local-only geometry probe extracted from the admin lab; the ordinary result handlers pass width/height on both URL and file upload paths. No remote probing/download is added. ffprobe has a 10-second timeout and file/pipe protocol restriction; missing metadata preserves delivery.
Regression: generated portrait and landscape MP4s exercise ordinary webhook delivery; remote media is not probed and missing ffprobe remains non-fatal. Existing SAR/rotation tests retained.
Initial reproduction: 2 failures (missing width/height). Initial focused suite: 109 passed.
UI/Mini App, migrations and pricing checks are not applicable: only Telegram media delivery arguments change.

Review: preserved env initialization order before importing the shared service; non-finite rotation now fails open (OverflowError). Focused delivery suite: 116 tests expected after review regression.
