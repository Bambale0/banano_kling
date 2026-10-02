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

## 12. Seedance 2.0/2.5: приватные референсы тренда

Этот pipeline относится только к каталогу curated trends (`user_prompts`,
`/mini-app/api/trends/run`, `action_type=trend`). Он не является Pinterest-flow,
публикацией в feed или обычным repeat готовой генерации.

### 12.1. Контракт

Администратор может создать тренд из собственной завершённой генерации
`seedance_2` или `seedance_2_5`:

```text
исходная @Image1  = лицо автора, заменить при повторе
исходная @Image2+ = одежда, украшения, предметы, сцена и другие fixed assets
исходные @VideoN  = fixed video references
исходные @AudioN  = fixed audio references
```

При повторе:

```text
@Image1 = одно новое фото текущего пользователя
@Image2..N = скрытые fixed image assets тренда
@Video1..N = скрытые fixed video assets тренда
@Audio1..N = скрытые fixed audio assets тренда
```

Нумерация image, video и audio независима. Backend никогда не сортирует refs по
URL, имени или времени. Порядок задаётся `media_type + position`.

### 12.2. Публикация из generation task

Admin-only endpoints:

```text
POST /mini-app/api/admin/trends/seedance/source
POST /mini-app/api/admin/trends/seedance/publish
```

Источник обязан быть:

- собственной завершённой video task;
- моделью `seedance_2` или `seedance_2_5`;
- не повтором из feed и не уже запущенным trend;
- содержать лицо автора и минимум один retained asset.

Администратор явно выбирает один identity image и retained image/video/audio
indices. Автоматическое распознавание лица не используется. Compiler проверяет
и перенумеровывает все явные bindings из исходного prompt. Если исходный prompt
не содержит часть или все `@ImageN`/`@VideoN`/`@AudioN`, финальный private guard
автоматически добавляет точные bindings для каждого выбранного retained asset и
`@Image1`. Пустой исходный prompt не может стать guard-only трендом. Публикация
по-прежнему блокируется, если исходный prompt явно ссылается на исключённое или
отсутствующее media.

Для одной исходной generation одновременно допускается только один активный
private-reference trend. После деактивации можно создать replacement.

### 12.3. Durable storage

Retained refs копируются до публикации в content-addressed storage:

```text
static/uploads/trend-assets/<image|video|audio>/<sha-prefix>/<sha>.<ext>
```

Источник должен быть существующим локальным NEUROMIX upload. Произвольные
внешние URL не скачиваются. Перед записью проверяются размер и фактическая
media-signature; MIME/extension сами по себе не считаются доказательством типа.

Metadata хранится в `trend_reference_assets`:

```text
prompt_id, media_type, position, source_position, role,
file_url, file_hash, mime_type, size_bytes, label
```

Лицо автора в эту таблицу не копируется.

### 12.4. Public privacy boundary

Public trend payload может раскрывать только форму запуска:

```json
{
  "reference_count": 1,
  "reference_labels": ["ВАШЕ ЛИЦО"],
  "automatic_hidden_references": true
}
```

Public APIs, task detail, history и browser state не получают fixed asset URLs,
storage keys, role map или private prompt. `trend_task_privacy.py` удаляет все
Seedance image/video/audio reference fields из protected trend tasks.

Frontend отправляет только:

```text
trend_id
одно user identity upload
user_values
client_request_id
```

Hidden refs загружает из БД и добавляет только backend.

### 12.5. Runtime

Seedance 2.0 private-reference trend всегда запускается через multimodal
reference arrays, без `first_frame_url`:

```text
reference_image_urls = [user_identity, fixed_images...]
reference_video_urls = fixed_videos
reference_audio_urls = fixed_audio
```

Seedance 2.5 private-reference trend всегда использует `scenario=multimodal` и
`first_frame=null`. Эвристика `одно фото -> first_frame` к этому контракту не
применяется.

Для явного Seedance 2.5 video editing recipe:

```text
ровно один fixed @Video1
duration = -1
ratio = adaptive
source video duration = 4..30 секунд
```

Стоимость editing запуска рассчитывается по измеренной длительности исходного
видео, а не по `-1`. Наличие fixed video reference учитывается существующим
Seedance video-reference multiplier.

### 12.6. Idempotency

Mini App создаёт стабильный `client_request_id` на один набор:

```text
trend + user refs + user fields
```

Повтор после сетевой ошибки использует тот же ID. Backend резервирует
`(user_id, trend_id, client_request_id)` в `trend_run_claims`, связывает ID с
request hash и возвращает сохранённый ответ при повторном запросе.

In-flight claim не reclaim-ится автоматически: неизвестный процесс мог уже
дойти до provider. Это сознательный fail-closed выбор против двойной платной
задачи. Такой claim должен разрешаться reconciliation/admin-диагностикой.

Все validation, asset availability, ownership, binding и capability checks
выполняются до debit. Identity upload для private-reference trend должен
принадлежать текущему Telegram user.

## 13. Source of truth

При конфликте документа и реализации приоритет зависит от flow.

Seedance private-reference trends:

1. `bot/seedance_trend_recipe.py`;
2. `bot/seedance_trend_admin_api.py` and `bot/trend_api.py`;
3. `bot/handlers/trend_seedance_25_compat.py` and Seedance provider adapters;
4. `bot/trend_task_privacy.py`;
5. Seedance trend/compiler/privacy/database tests;
6. this document.

Pinterest identity transfer:

1. `bot/pinterest_trend_flow_contract.py`;
2. `bot/pinterest_trend_api.py`;
3. `bot/trend_task_privacy.py`;
4. provider adapter code in `bot/services/*`;
5. Pinterest contract and privacy tests;
6. this document.
