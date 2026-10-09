# Seedance 2.5: direct character editing

## User-facing contract

The Mini App and Telegram expose **Замена персонажа** separately from ordinary **По референсам** generation. This is a direct request: the original image references and source video go to Seedance 2.5. There is no Seedream, LAS, image pre-generation, keyframe replacement or additional paid stage.

Inputs remain one to three photos of the same person, in their original order, plus exactly one owned, managed source video lasting 4–30 seconds. First/last-frame and audio-reference inputs are not part of this scenario. The default edit replaces facial features and hair while preserving the source video's clothing, actions, objects and scene. Other changes require an explicit instruction; model quality is not guaranteed.

### Instructions (`direct-edit-v1`)

- A complete prompt naming both `@Image1` and `@Video1` is sent without the former `apix-v1` wrapper. Existing case/spacing normalization of reference tags still applies.
- An empty prompt uses the configured concise direct-edit template.
- Short wishes that do not name both inputs are appended to that direct template. This preserves the old optional-wishes and repeat behavior without letting a wish such as "keep the dress" accidentally remove the replacement instruction.
- The default template expands `{identity_images}` into the actual ordered `@Image1`, `@Image2`, `@Image3` list. Only references that exist are named.
- Direct edit validates the final prompt against the currently published KIE limit of 20,480 Unicode characters before debit. For short wishes this includes the expanded template. The pre-existing ordinary-generation limit is not changed in this scoped release.

The full provider prompt is resolved and frozen during server-side pre-debit validation. The original user instruction remains in task history and owner-only repeats. A later admin template update cannot rewrite an already validated launch. Metadata/logs include a prompt SHA-256 and role version, not a new raw private-prompt log.

## Provider boundary

The provider remains KIE `bytedance/seedance-2-5`. Images and the original video remain in `reference_image_urls` and `reference_video_urls`; no frame fields are added. Direct identity edit sets `duration=-1`, `aspect_ratio=adaptive` and `input.omni_reference_task_type=edit`. Ordinary references do not receive the edit field.

KIE accepted, persisted and completed an earlier controlled request containing the edit field. It is still absent from the published KIE schema: acceptance/echo is not proof that KIE forwards or applies it upstream. This implementation does not claim that the field alone fixes identity fidelity. Do not add LAS fields such as `template.id` to this endpoint.

Sources checked 2026-10-09:
- https://docs.kie.ai/market/bytedance/seedance-2-5.md
- https://docs.byteplus.com/id/docs/modelark/seedance-2-5

## Admin configuration

The default lives in the existing audited `bot_settings` store under `seedance25_direct_edit_template`. No migration, new tariff, credential or environment variable is required. An unset value uses the shipped default.

Telegram admin command:

```text
/seedance25_edit_prompt
/seedance25_edit_prompt set Video edit: replace the person in @Video1 with {identity_images}. Keep the original clothing and scene.
/seedance25_edit_prompt reset
```

The first command downloads the current template. `set` also works as a reply to a text/caption containing the template. Templates are limited to 4,096 characters so every accepted template can be set through the admin surface; use a reply for the maximum length, without adding the command prefix to the template message. Only authenticated configured administrators can read/change it via this command; writes record the actor using the existing settings audit columns. Placeholders, length and media aliases are validated before saving. Only `{identity_images}` is allowed; Python attribute/index/conversion/format expressions are rejected. Additional image indices must be generated from that placeholder, never fixed `@Image2` tags that would break a one-photo request.

## Paid launch safety and repeats

Provider auto-duration and billable duration remain separate. The server measures the user's managed video, requires finite 4–30 seconds and bills its ceiling using existing rates and the existing video-reference multiplier exactly once. No placeholder duration, extra image charge or second generation is introduced.

Quote-only does not debit, create a task or submit to a generation provider. Launch revalidates ownership, canonical path containment, duration, resolution, repeat lineage and the current price. Missing/stale quotes require recalculation and another explicit Start. Identity edit never automatically retries as another paid generation. Own-task repeats preserve ordered references and the original instruction; explicit empty arrays do not resurrect removed private media.

## Verification and release

Mocked tests cover direct and ordinary provider payloads, one/two/three ordered photos, empty/full/short instructions, Unicode length limits, invalid references, editable defaults, denied admin writes, audit arguments, frozen pre-debit prompt/hash, quote/debit consistency and existing Telegram/repeat contracts. Frontend tests cover direct copy, complete prompt transport, limits and ordinary-mode switching.

These tests prove request composition and payment safety, not visual quality. Production availability must be reported only after exact deployed-SHA verification and smoke checks. Visual acceptance of the generated result remains a separate requirement; neither HTTP 200 nor a provider `success` state establishes successful character replacement.
