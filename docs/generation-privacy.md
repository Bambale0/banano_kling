# Generation Privacy Boundary

Актуальность: `2026-10-03`, ветка `tanyapi`.

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

Для обычной собственной generation автор может включить референсы выборочно.
Mini App отправляет отдельные zero-based индексы для image и video refs;
task detail сохраняет для доступных preview их позиции в исходном ordered list.
Backend валидирует эти source indices по неизменённому списку, разрешает в стабильные
URL и сохраняет selection в `generation_tasks.feed_reference_selection`.
Публичная карточка получает только выбранные URL; истечение одного URL не
сдвигает выбор на соседний reference. Исходный `request_data` и provider recipe при этом не изменяются.
Старые строки без selection сохраняют прежнее поведение «все или ничего».

Сохранённый selection сам по себе не является разрешением на публикацию. Для
чужого image-repeat backend наследует и разрешает повторное использование только
референсов, которые разрешены текущим `feed_references_visible` и действительно
присутствуют в доступной этому пользователю карточке. Скрытые и невыбранные
исходные URL не сохраняются в references другого пользователя. Собственные
приватные входные данные автора при этом остаются доступны в его обычной задаче.

Task detail применяет существующий privacy sanitizer при построении ответа,
помимо middleware. Legacy child-задачи с `source_feed_gen_id` не возвращают
сырые source/reference поля, recipe или publication previews. Это защита ответа,
а не массовая перезапись исторических задач или файлов.

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


## 2026-10-07: repeat privacy boundary

Intrinsic recipe privacy is shared across task APIs, Feed/Profile cards and Telegram
repeat callbacks: source lineage, trend action and stored `prompt_hidden`,
`prompt_actions_allowed` or `private_recipe` markers cannot be overridden by owning
the result or publishing its prompt. Legacy boolean representations are normalized;
malformed explicit privacy markers fail closed. Ordinary unpublished owner prompts
remain usable. Existing legacy trend-text matching is retained for task APIs.

Direct Telegram-authenticated bootstrap sanitizes recent tasks at the API return,
not only in browser authentication middleware. Private serialized request snapshots
are parsed and redacted, never returned as an opaque string.

Video repeat presets are normalized before Feed/Profile/deep-link hydration and
again when either video form consumes them. A card/detail privacy denial wins over
stale nonempty text. The editable field may still accept the user's new instructions;
it never needs to receive the hidden original. Backend redaction remains the security
boundary; client masking is additional protection for stale data.

Regression commands (isolated synthetic data only):

- `python -m pytest tests/test_hidden_repeat_prompt_privacy.py -q`
- `npm test -- --runInBand` in `frontend/miniapp-v0`
- after static export: `node e2e/hidden-repeat-prompt.mjs`

No historical database rewrite or promise to erase previously downloaded text is made.
