# Reference System NEUROMIX

Актуальность: `2026-08-23`, ветка `tanyapi`.

Этот документ фиксирует production-контракт работы с референсами в backend, Mini App и provider adapters. Его цель — исключить повтор старого бага, когда общий Nano Banana слой трактовал первое изображение как identity, а Pinterest flow одновременно использовал первое изображение как scene.

## 1. Главный инвариант

Назначение изображения нельзя угадывать по одному только факту загрузки.

Каждый reference должен иметь явную роль:

```text
SCENE_REFERENCE       -> сцена, поза, камера, одежда, свет, фон
IDENTITY_REFERENCE    -> лицо, волосы, телосложение, возраст, особенности пользователя
STYLE_REFERENCE       -> стиль, цвет, визуальная манера, если режим это поддерживает
```

Если flow требует роли, но роль не может быть определена однозначно, генерация должна остановиться до списания кредитов и до отправки provider request.

## 2. Pinterest / Trend Identity Transfer

Pinterest flow — специальный production-пайплайн. Он не является обычным image-to-image и не должен проходить через generic правило `first uploaded image = identity`.

Порядок входных изображений от пользователя:

```text
Image 1      = SCENE_REFERENCE
Image 2      = USER_IDENTITY_REFERENCE
Images 3..N  = IDENTITY_EVIDENCE
```

Провайдерный payload для nano-banana-pro передаётся в том же порядке —
scene-first (это перенос личности в сцену, поэтому сцена остаётся базовым кадром):

```text
provider_images[0]      = SCENE_REFERENCE
provider_images[1]      = USER_IDENTITY_REFERENCE
provider_images[2..N]   = IDENTITY_EVIDENCE
```

Runtime prompt нумерует роли в провайдерском порядке. Identity-first
переупорядочивание запрещено: оно трактовало пользовательское селфи как
исходную композицию, из-за чего модель возвращала одно из загруженных фото
пользователя, копировала доп. референс как кадр или сохраняла исходник
вместо переноса пользователя в сцену.

Image 1 используется только для:

- композиции;
- позы;
- одежды;
- фона;
- света;
- камеры;
- настроения;
- выражения и направления взгляда, если это часть постановки.

Image 2..N используются только для:

- лица пользователя;
- геометрии лица;
- волос пользователя;
- телосложения;
- возраста;
- отличительных признаков;
- согласованной identity между несколькими ракурсами.

Запрещено:

- копировать лицо человека с Pinterest reference;
- считать первое изображение identity;
- усреднять identity пользователя и source person;
- восстанавливать hidden prompt через repeat/feed/share/history;
- запускать генерацию автоматически сразу после загрузки фото.

## 3. Количество references

Для Pinterest flow:

```text
minimum = 2
maximum = 7
```

То есть:

```text
1 Pinterest scene reference
+ 1 primary user identity photo
+ до 5 дополнительных identity angles
```

Если больше 7 — запрос отклоняется до provider call.

Если меньше 2 — запрос отклоняется до provider call.

## 4. Generic flows

### Text-to-image

```text
references = []
```

Нет reference roles. Prompt полностью отвечает за результат.

### Ordinary image-to-image

Обычный I2I может использовать пользовательские изображения как identity/style references только согласно выбранному режиму модели. Он не должен применять Pinterest правила.

### Video / image-to-video

Для I2V reference image/video является input media, а не Pinterest scene reference, если flow явно не помечен как trend identity transfer.

## 5. GenerationContext

Реализовано в `bot/generation_context.py` как типизированный контракт:

```text
GenerationContext
  input_media
  reference_context
    scene_references[]
    identity_references[]
    style_references[]
  model_config
  privacy_policy
```

Правила:

- роли назначаются только через резолверы `resolve_pinterest_reference_roles` / `resolve_standard_reference_roles` / `resolve_text_to_image_context`;
- Pinterest-гейт `ensure_pinterest_reference_gate` проверяет scene/identity/roles и включённый privacy mode до создания задачи и списания кредитов;
- `validate_generation_context` дополнительно проверяет лимит референсов провайдера и схемы URL;
- Public API response не должен быть сериализацией `GenerationContext` напрямую.

## 6. Provider mapping

Перед отправкой в provider adapter должно быть проверено:

```text
Pinterest mode:
  scene_references >= 1
  identity_references >= 1
  total_references <= provider_limit
  prompt privacy enabled
```

Provider adapter может принимать плоский список URL только после того, как roles уже зафиксированы в prompt и validation gate. Нельзя сортировать, дедуплицировать или переупорядочивать references так, чтобы scene/identity поменялись местами.

Ожидаемый порядок для provider payload:

```text
provider_images[0]    = scene
provider_images[1..N] = identity
```

## 7. Prompt contract

Pinterest runtime prompt обязан явно содержать:

```text
Image 1 = SCENE_REFERENCE
Image 2 = USER_IDENTITY_REFERENCE
Images 3..N = ADDITIONAL_USER_IDENTITY_ANGLES
```

Также prompt должен содержать source-copy guard:

```text
Returning SCENE_REFERENCE unchanged or nearly unchanged is invalid.
Do not reuse the source person's face.
Replace the person identity with the user.
```

Generic Nano Banana prompt enhancement не должен добавлять поверх Pinterest prompt инструкцию вида:

```text
Use first uploaded image as primary person identity reference
```

## 8. Privacy boundary

Trend/Pinterest задачи считаются private recipe tasks.

В публичные и полу-публичные ответы не должны попадать:

- prompt;
- effective_prompt;
- source_url;
- pinterest_url;
- private reference chain;
- provider debug payload;
- source feed generation recipe.

Для task detail, history, feed и share ожидаются поля:

```json
{
  "prompt": "",
  "prompt_preview": "",
  "prompt_hidden": true,
  "prompt_actions_allowed": false,
  "feed_prompt_visible": false
}
```

Provider получает полный runtime prompt, но database/public API не должны хранить или раскрывать рецепт.

## 9. Repeat / Remix rules

Repeat для обычной пользовательской генерации может использовать сохранённый prompt, если он не скрыт.

Repeat для trend/Pinterest:

- не раскрывает prompt;
- не восстанавливает source recipe;
- не копирует private references исходного автора;
- требует новый identity input пользователя, если сценарий подразумевает персонализацию;
- сохраняет только безопасный публичный result context.

## 10. Debugging

Если Pinterest результат почти копирует source photo или берёт лицо source person, проверять в таком порядке:

1. Mini App отправляет `reference_urls` в порядке scene, identity, extra identity.
2. API не запускает генерацию до `confirmed=true`.
3. Runtime prompt содержит `PINTEREST_RECREATION_CONTRACT_V2`.
4. Generic reference preservation bypassed для Pinterest prompt.
5. Provider payload сохраняет порядок scene -> identity.
6. Database не хранит private recipe.
7. Task/history/feed/share sanitizers не раскрывают prompt.

## 11. Regression checklist

Минимальный набор тестов для каждого изменения reference layer:

- Pinterest + 1 identity photo;
- Pinterest + 5 additional identity angles;
- duplicate reference URL rejected;
- blob/data/file URL rejected;
- upload alone does not start generation;
- missing height/weight rejected for Pinterest flow;
- generic trend route blocked for Pinterest prompt;
- generic Nano Banana first-image identity guidance not applied to Pinterest;
- task detail hides prompt;
- recent history hides prompt;
- feed hides prompt;
- share hides prompt;
- repeat cannot recover hidden prompt.

## 12. Source of truth

При конфликте документа и реализации приоритет:

1. `bot/pinterest_trend_flow_contract.py`;
2. `bot/pinterest_trend_api.py`;
3. `bot/trend_task_privacy.py`;
4. provider adapter code in `bot/services/*`;
5. `tests/test_pinterest_manual_flow_contract.py` and trend privacy tests;
6. this document.
