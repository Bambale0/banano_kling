# Video repeat prompt composition

## Contract

**Применяется к самой выбранной опубликованной работе**, включая опубликованный ремикс, тренд и повтор. `source_feed_gen_id`/`action_type` — происхождение, а не причина подменять источник его предком или отклонять публикацию. Общие правила: [PUBLICATION_REPEAT_CONTRACT.md](PUBLICATION_REPEAT_CONTRACT.md). Legacy и typed Seedance имеют разные внутренние режимы восстановления; они должны сохранять эквивалентный пользовательский результат, не открывая скрытые исходные строки.

Feed/profile video repeats send only the viewer's requested changes from the
Mini App. After authenticating the viewer and resolving the source publication,
the shared video-continuity boundary combines the saved source prompt with those
changes using the same composition helper as photo remixes.

- Empty edits retain the saved prompt verbatim
- Nonempty edits preserve the source and take priority for the requested changes
- Composition occurs once before dispatch, including the separate Seedance 2.5 path
- Missing/inaccessible **clicked publication** prompts fail before billing/provider submission; a working published child is never substituted by its ancestor
- Normal video creation without a source publication keeps its existing prompt semantics
- Genjutsu recipes retain their dedicated redirect and structured editing contract
- Reference grant, ordered slots, receipts, prices, refunds and referral rules remain independently validated; provider/network failure is not the same as revoked grant

Composed repeats must fit the existing provider-adapter character limits. Seedance
2 uses its canonical reference aliases before the length check; Seedance 2.5 keeps
its validation of the complete provider prompt, including identity-role instructions.
Gemini Omni uses the same named limit as its adapter. Overflow is rejected before
debit, with an actionable message that exposes neither the private prompt nor its length.

The composed prompt is retained only in the internal generation record and provider
request. Existing source lineage keeps task/history and publication responses private.
Repeat failures return generic errors. Provider request logs contain diagnostic
status/type metadata, not provider response bodies or echoed prompt text.

## Regression evidence

Baseline: `tanyapi` commit `05199e7357a221e34c6afd5ab17e3b48f36ed4a6`.
The original endpoint/provider tests reproduced edits arriving without the source
on both Seedance 2 and 2.5. Separate regressions reproduced legacy error disclosure
and truncation of edits at the Seedance 2 / Gemini Omni adapter limits.

`tests/test_video_repeat_prompt_composition.py` exercises the installed Mini App
wrapper chain, real endpoint and provider payload construction, local SQLite task
storage and detail redaction. External HTTP transport is replaced by synthetic
fixtures; additional fake-aiohttp tests cover transport logging and retries.

The focused regression set also covers existing photo remixes, reference consent,
private video callbacks/receipts, Seedance identity/adapter contracts, trends,
Genjutsu and model keyboards. No paid provider call or production write is part
of these tests. Deployment requires normal CI and a separately authorized release.
