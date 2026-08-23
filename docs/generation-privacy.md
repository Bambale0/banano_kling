# Generation Privacy Boundary

Актуальность: `2026-08-23`, ветка `tanyapi`.

Документ фиксирует границы приватности для задач генерации, особенно curated trend / Pinterest flows.

## 1. Проблема

Некоторые generation flows используют коммерчески ценные или приватные рецепты:

- curated trend prompt;
- Pinterest recreation prompt;
- source feed generation context;
- private reference chain;
- provider-specific prompt engineering.

Эти данные нужны provider runtime, но не должны попадать в публичные API, историю, ленту, share links или repeat flow.

## 2. Internal vs public data

Backend должен различать два объекта:

```text
InternalGenerationContext
  -> полный prompt
  -> provider payload
  -> private references
  -> source recipe

PublicGenerationDTO
  -> result URL
  -> status
  -> safe metadata
  -> public actions
```

Нельзя отдавать internal object напрямую наружу.

## 3. Private recipe tasks

Задача считается private recipe task, если:

- `action_type == trend`;
- задача создана из Pinterest/trend flow;
- request data содержит hidden prompt marker;
- source prompt помечен как curated/private;
- feed source generation имеет скрытый prompt.

Для таких задач fail-closed поведение предпочтительнее fail-open.

## 4. Fields never exposed publicly

Следующие поля не должны выходить в public/semi-public API:

- `prompt`;
- `prompt_preview` with recipe content;
- `effective_prompt`;
- `source_url`;
- `pinterest_url`;
- `reference_images`, если это private source chain;
- `source_reference_images`;
- provider raw request body;
- internal prompt marker details beyond safe debug/admin context;
- source feed generation prompt;
- private user upload URLs, если flow не делает их публичными явно.

## 5. Required public flags

For private recipe task response:

```json
{
  "prompt": "",
  "prompt_preview": "",
  "prompt_hidden": true,
  "prompt_actions_allowed": false,
  "feed_prompt_visible": false
}
```

If a route cannot determine whether prompt is safe, it should hide prompt.

## 6. Routes to protect

Required protected surfaces:

- Mini App task detail;
- Mini App recent history;
- feed generation history;
- public feed cards;
- share/deep-link routes;
- repeat/remix bootstrap payloads;
- Telegram result keyboards and callback payloads;
- browser fallback routes that expose generation metadata.

Admin routes may expose more information only when explicitly authenticated and intended for diagnostics.

## 7. Persistence policy

Provider runtime may temporarily use full prompt before task persistence.

Database persistence should not store private recipe in long-lived public task fields.

Recommended behavior before INSERT/UPDATE of private trend task:

```text
prompt = ""
request_data.prompt removed
request_data.effective_prompt removed
request_data.source_url removed
request_data.pinterest_url removed
request_data.prompt_hidden = true
request_data.prompt_actions_allowed = false
```

If source references are needed for provider retry, store them in a private internal-only channel, not in public DTO fields.

## 8. Repeat policy

Repeat must respect privacy flags.

Allowed for public prompt task:

```text
repeat -> reuse prompt/settings if owner/action allows
```

Not allowed for private trend task:

```text
repeat -> recover hidden prompt
repeat -> expose source recipe
repeat -> clone source author reference chain
```

If repeat is available, it must use a safe product-specific flow, not raw prompt replay.

## 9. Feed/share policy

Feed/share can include:

- result URL;
- thumbnail URL;
- generation type;
- public model label;
- like/share counts;
- safe owner/profile information.

Feed/share must not include:

- hidden prompt;
- hidden prompt preview;
- source recipe;
- private reference URLs;
- provider raw payload.

## 10. Logging policy

Logs may include:

- task ID;
- user ID / telegram ID where operationally required;
- provider model;
- count of references;
- safe validation error;
- privacy policy name.

Logs must not include full private prompt, provider payload with recipe, or private reference URLs unless logs are protected and the line is explicitly redacted or debug-only.

## 11. Regression checklist

For every privacy-sensitive generation change:

- task detail hides prompt;
- history hides prompt;
- feed hides prompt;
- share hides prompt;
- repeat cannot recover prompt;
- source feed generation cannot be used to reconstruct recipe;
- public DTO does not include private `request_data` keys;
- ordinary non-private generation still works and can show prompt when allowed.

## 12. Operational debugging

If user reports that trend prompt became visible:

1. Identify generation task ID.
2. Check `prompt_hidden` and `prompt_actions_allowed` in API response.
3. Check whether task is trend/private recipe.
4. Check task detail sanitizer.
5. Check history sanitizer.
6. Check feed/share serializer.
7. Check repeat/remix bootstrap route.
8. Check database persistence path for bypasses.

If user reports repeat stopped working:

1. Check whether original task is private recipe.
2. If private, repeat should not use hidden prompt.
3. Verify product-specific repeat flow asks for required new input.
4. Confirm credits are not deducted before validation.

## 13. Source of truth

1. `bot/trend_task_privacy.py`;
2. task persistence code in `bot/database.py`;
3. Mini App routes in `bot/miniapp.py`;
4. Pinterest contract in `bot/pinterest_trend_flow_contract.py`;
5. tests covering task/history/feed/share privacy;
6. this document.
