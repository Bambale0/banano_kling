# Pinterest / Trend Flow Runbook

Актуальность: `2026-08-23`, ветка `tanyapi`.

Документ описывает пользовательский и технический поток Pinterest/Trend генерации после исправления reference roles и prompt privacy.

## 1. Назначение flow

Pinterest/Trend flow позволяет пользователю повторить постановку с Pinterest/trend reference, но заменить человека на самого пользователя.

Цель результата:

```text
source scene + user's identity = new generated image
```

Не цель:

```text
source image with minor edits
source person's face copied into result
prompt recipe exposed to user
```

## 2. User flow

Ожидаемый Mini App сценарий:

```text
Open Trends
  -> select Pinterest/trend card
  -> upload Pinterest scene reference
  -> upload primary user photo
  -> optionally upload 1..5 additional user angles
  -> enter required height/weight
  -> press Generate/Create explicitly
  -> wait for result
  -> receive result in Mini App/history/Telegram delivery
```

Загрузка фото сама по себе не запускает генерацию.

## 3. Required inputs

Pinterest flow requires:

- one scene reference;
- one primary identity reference;
- height;
- weight;
- explicit confirmation button.

Optional:

- up to five additional identity angles.

Validation errors must happen before provider request and before irreversible credit debit.

## 4. Reference roles

```text
reference_urls[0] = SCENE_REFERENCE
reference_urls[1] = USER_IDENTITY_REFERENCE
reference_urls[2..6] = ADDITIONAL_USER_IDENTITY_ANGLES
```

The UI should make this visible to the user:

```text
Scene:
  ✓ Pinterest photo

Identity:
  ✓ Main user photo
  + N additional angles
```

## 5. Backend validation

The API must reject:

- missing `reference_urls`;
- fewer than 2 references;
- more than 7 references;
- empty URL;
- duplicate URL;
- `blob:` / `data:` / `file:` URL;
- non-http and non-`/uploads/` URL;
- missing height;
- missing weight;
- generation without `confirmed=true`.

## 6. Runtime prompt

Runtime prompt must include `PINTEREST_RECREATION_CONTRACT_V2`.

The prompt must say:

```text
Image 1 = SCENE_REFERENCE
Image 2 = USER_IDENTITY_REFERENCE
Images 3..N = ADDITIONAL_USER_IDENTITY_ANGLES
```

It must also include conflict priority:

```text
Pose/camera/framing/expression/clothing/hairstyle arrangement/scene -> Image 1
Face/identity/body build/hair length/hair color -> user identity images
```

## 7. Generic Nano Banana bypass

Generic Nano Banana reference guidance must not be applied to Pinterest runtime prompt if that guidance implies:

```text
first uploaded image = primary identity
```

This is the root cause of the old quality bug.

## 8. Provider payload

Provider payload may be a plain image URL array only if validation and prompt role assignment already happened.

Expected order:

```text
images[0] = scene
images[1] = user identity
images[2..N] = extra user identity
```

Adapters must not reorder references by source, upload time, filename, URL, MIME type, or deduplication side effects.

## 9. Result quality checks

Manual QA should include contrastive cases:

### Case A

Scene reference: woman in dress / studio pose.

User identity: man.

Expected:

- result is recognizable as the male user;
- pose/camera/outfit/scene come from scene reference;
- source woman's face is not copied.

### Case B

Scene reference: complex lighting and crop.

User identity: 3..5 photos.

Expected:

- face and hair identity are stable;
- scene composition is preserved;
- extra identity angles do not change pose or background.

## 10. Privacy expectations

For Pinterest/trend tasks, public responses must expose result only.

Hidden fields:

- prompt;
- prompt_preview;
- effective_prompt;
- source_url;
- pinterest_url;
- private reference chain;
- provider request body.

Expected response flags:

```json
{
  "prompt_hidden": true,
  "prompt_actions_allowed": false,
  "feed_prompt_visible": false
}
```

## 11. Repeat / Share / Feed

### Repeat

Repeat must not recover hidden trend recipe.

If repeat requires personalization, it must ask for user's own identity references again or use only allowed user-owned references.

### Share

Share can expose:

- result URL;
- safe preview;
- model label;
- public metadata.

Share must not expose hidden prompt or source recipe.

### Feed

Feed item can show the result and safe action buttons.

Feed prompt actions must remain disabled for hidden trend tasks.

## 12. Webhook/history check

After provider webhook:

- task status becomes completed;
- result URL is attached;
- prompt remains hidden;
- history card opens result;
- Telegram delivery does not include recipe;
- share/repeat buttons respect prompt privacy flags.

## 13. Debug checklist

If result quality is bad:

1. Confirm Mini App sent scene first.
2. Confirm identity image exists and is not the Pinterest photo.
3. Confirm extra angles are same person.
4. Confirm `PINTEREST_RECREATION_CONTRACT_V2` in runtime prompt.
5. Confirm generic first-image identity guidance is not appended.
6. Confirm provider images preserve order.
7. Confirm model selected supports multi-reference input.
8. Confirm no fallback provider strips references.

If privacy is broken:

1. Check task detail API.
2. Check recent history API.
3. Check feed API.
4. Check share/deep-link API.
5. Check Telegram result keyboard callbacks.
6. Check admin preview separately from public API.

## 14. Minimal tests before release

```bash
python -m pytest \
  tests/test_pinterest_manual_flow_contract.py \
  tests/test_trend_task_privacy.py
```

Also run the broader generation/privacy regression suite when provider or history code changes.
