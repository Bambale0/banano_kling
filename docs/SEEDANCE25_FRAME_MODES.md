# Seedance 2.5 first/last frame geometry

KIE first-frame and first-last-frame tasks require `aspect_ratio: adaptive`.
Text and multimodal reference tasks still support the configured fixed ratios.
Frame-mode output geometry follows the first image; choosing 9:16 in a legacy
template cannot force a different canvas. Use a first image with the intended
geometry, or choose the multimodal reference workflow for a fixed output ratio.

Confirmed on 2026-10-23 by one exact replay of the reported birthday trend:
8 seconds, 720p, first frame, 9:16. KIE rejected creation with code 422:
`first-frame and first-last-frame tasks only support adaptive aspect ratio`.
No task ID was returned. The operator authorized one diagnostic create up to $3;
the diagnostic did not use the customer's balance. Private input and response
artifacts remain outside Git. The generic official schema lists the global
ratio enum without this mode restriction:
[KIE Seedance 2.5 contract](https://docs.kie.ai/market/bytedance/seedance-2-5).

The adapter normalizes valid stale fixed ratios for both frame modes. Public
Mini App/Telegram validation resolves the same value before billing and task
persistence; trend history, repeat metadata and the response record `adaptive`.
Both Mini App forms and Telegram controls show automatic frame geometry.
Text/multimodal ratio choices are retained when switching back from frame mode.
This is an immutable provider constraint, not an editable business setting.
No tariff, template, database migration, retry or refund rule changes are needed.

Rejected creates emit model, scenario, numeric provider code and a safe reason
classification. Provider text is excluded because it may echo hidden prompts,
private media or credentials. There is no automatic retry or extra provider call.
