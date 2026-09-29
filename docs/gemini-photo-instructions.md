# Gemini: photo-analysis instructions

Gemini photo-only calls in PhotoPromptService and PromptAnalyzerV2Service share editable reconstruction guidance. It preserves the reference medium, composition, object counts/positions, visible light/material/pose details, and applies explicit requested edits only to the selected elements. It avoids invented hidden detail, camera metadata and identity inference. Russian and English describe the same scene without padding.

The classic service retains its structured output fields; V2 retains only prompt_ru/prompt_en. Technical JSON contracts are appended separately and take precedence over editable guidance. Voice, video and Qwen fallback retain their existing instructions.

## Administrator controls

- /gemini_photo_prompt downloads current guidance as UTF-8 text.
- /gemini_photo_prompt set TEXT replaces guidance. Alternatively reply to a text message with /gemini_photo_prompt set.
- /gemini_photo_prompt reset restores the versioned default.

Only configured administrators can read/change it. Nonempty text up to 8000 characters is accepted; Telegram's own text-message limit still applies. bot_settings.gemini_photo_instructions records updated_by_telegram_id and updated_at. No schema migration or new secret is required. Local settings cache is invalidated immediately; another process may retain its cached setting for up to 5 seconds. In-flight analyses retain their original instructions.

The task-local analysis trace links the instruction revision (photo/v2 prefix) to request ID, user ID and terminal outcome, never the instructions or user media. A Qwen fallback clears the Gemini revision from subsequent events; the earlier selection event remains correlated to the same request. This is configuration provenance, not a claim that every model response is accurate. Review real outputs for reference fidelity, requested edits, language agreement and valid schema.

## Verification

- Public service calls against a local KIE-compatible HTTP server verify effective settings, input preservation and per-surface output contract.
- Admin command tests verify authorization, set/view/reset, audit author and invalid updates.
- Existing provider fallback, pricing, voice and V2 suites cover surrounding behavior.
- A synthetic two-shape illustration checks actual Gemini output, requested background edit and language consistency without customer data or credits.
