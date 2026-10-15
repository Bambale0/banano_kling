# NEUROMIX / Tanya — проверка после релиза, 2026-10-16

## Объём и границы достоверности

Репозиторий `Bambale0/banano_kling`, production branch `tanyapi`. Проверяется PR [#320](https://github.com/Bambale0/banano_kling/pull/320), обязательный CI, точный deployment SHA, health/telemetry и согласованное продуктовое правило повторов для **всех** моделей, а не только для одной WAN-публикации.

**Merge SHA:** `b9f6b68dd0b23d4233c021e2c35cbbc5ccea4fe9`. Даты в отчёте — дата аудита, не дата создания каждой исходной функции. Автоматические тесты с подменёнными API не подтверждают качество реальных результатов провайдера; платных тестовых задач/списаний не запускаем без отдельного разрешения.

### Источники доказательств

- GitHub PR #320, точный post-merge `CI — Tanya TG Bot`, `CI — Tanya Mini App`, `Wan Prime Release Contract`, `Deploy — Tanya production reliable`.
- Read-only production checkout, OCI label running Docker bot, публичные `/health` и `/mini-app/revision.txt`, media static path, лог-срез без пользовательского контента.
- Реальная база только для агрегатов по `generation_tasks` / `trend_generation_runs` и чтения планов повтора; никаких UPDATE/DDL.
- `AGENTS.md` и актуальный код; `docs/agents/EXECUTION.md` — **исторический** журнал, ошибочная логика PR #319 в нём отменена.

## Release gate (заполнить только после точной проверки)

| Проверка | Результат | Доказательство |
| --- | --- | --- |
| PR #320 merged to tanyapi | Подтверждено | merge SHA выше |
| Required PR-head CI | Подтверждено | все protected checks PASS |
| Post-merge CI exact SHA | В проверке | не выдавать за зелёный до завершения workflow |
| Production backend checkout exact SHA | В проверке | `git rev-parse HEAD` |
| Docker `banano-kling-bot` OCI revision + healthy | В проверке | `docker inspect` |
| Mini App exact revision + HTTP 200 | В проверке | `/mini-app/revision.txt`, `curl -I` |
| Backend public health | В проверке | `/health` |
| Admin price file unchanged | В проверке | SHA256 pre-release `3c73a0651c6deee689ce779669faf9dd572b7ac3f09eddc200b0e26f6ef39583` |
| Read-only WAN repeat plan for public source | В проверке | selected publication ID, not ancestor trend; redacted prompt/URLs |
| Post-release logs/telemetry | В проверке | scoped, sanitized container logs |
| Real Telegram iOS Photos `IMG_0729.jpeg` | Не подтверждено | физический тест не проводился |
| Paid end-to-end model quality | Не запускалось | отдельное разрешение необходимо |

## Production data / telemetry — read-only baselines

- Исходный релизный сервер до окончания postmerge deploy оставался на `209af276d05c480566018a09d6b770ba030d31c0`. Это важно: CLI merge / зелёные PR-тесты без OCI/frontend SHA **не подтверждают** выход новой версии.
- На выборке **последних 1 200** generation tasks (не 24-часовая статистика): **1 111** `completed`, **88** `failed` и **1** `pending`. Среди этих 1 200 задач: 755 `banana_pro`, 136 `seedream_5_pro`, 111 `nano-banana-2-lite`, 59 `banana_2`, 40 `wan_3`, 30 `seedance_2_5`; это только распределение выборки, а не SLA или успех конкретного режима повтора.
- Из `trend_generation_runs` с точным `generation_tasks.status=completed` на момент read-only запроса было **1 379** завершённых связанных с трендами задач. Эти данные нельзя подменять `uses_count` (accepted attempts) и нельзя трактовать как число уникальных пользователей.
- Историческая предрелизная выборка **500 опубликованных завершённых видео** показала 345 Seedance + 23 Genjutsu + 19 Grok + 1 Motion без typed descriptor (legacy/dedicated flow может работать). Это **риск недостаточной проверки**, а не доказательство отказа у всех перечисленных моделей.

## Audit: продуктовый контракт, frontend и backend

**Правило владельца:** опубликованный завершённый результат любой поддерживаемой модели можно повторять независимо от того, оригинал это, тренд, ремикс или повтор. Источник — та работа, по которой кликнули. `source_feed_gen_id` — lineage, а не разрешение. PR #320 удалил ancestry-only блокировки в фото, обычном видео, Wan и Telegram callback, не передавая скрытые исходные ссылки в DTO. [Полный контракт](PUBLICATION_REPEAT_CONTRACT.md).

### Проверенные автоматически пути

- WAN: `tests/test_wan3_feed_repeat.py`, `tests/test_wan3_prime_lifecycle.py`, `wan3-prime-form.test.tsx`, отдельный mobile/browser all-modes contract. Серверный quote/immutable hash и reserved settlement не менялись; цены из admin config.
- Фото: `tests/test_image_repeat_reference_integrity.py`, `tests/test_private_repeat_permission.py`, `tests/test_private_repeat_runtime.py`. Привязка media-права к clicked publication отделена от родительской lineage; auto-retry сохраняет server-owned permission source.
- Seedance / generic video: `tests/test_video_repeat_private_contract.py`, `tests/test_video_repeat_private_callbacks.py`, `frontend/miniapp-v0/components/forms/video-generator-form-repeat.test.tsx`. Действующие права автора и mode-specific ограничения проверяются отдельно; provider 503 не означает отзыв разрешения.
- Категории трендов: `successful_runs_count` считает `completed` tasks один раз по ID, а не `uses_count`; ценник WAN `от N 🍌` — только нижняя граница, не quote.

### Выявленные ограничения и последующие задачи

| Приоритет | Наблюдение | Статус / критерий |
| --- | --- | --- |
| P1 — покрытие моделей | Аудит 500 последних завершённых опубликованных видео **до релиза**: `video_repeat_descriptors` выдавал typed-ready только 78 Seedance (2 + 76), 33 WAN; у 345 Seedance (223+122), 23 Genjutsu, 19 Grok и 1 Motion он возвращал `None`. `None` **не доказывает отказ**: legacy или dedicated editor могут обрабатывать повтор. | Провести модельный API+WebView smoke с реальными публикациями и проверить отсутствие потери prompt/slots; не объявлять 500/500 неработающими. Для режимов, которые явно отказывают (identity-edit, отдельный motion), доработать специализированный editor. |
| P1 — повторная публикация Genjutsu | `bot/genjutsu/feed.py::publish` явно возвращает `private_recipe_publication_forbidden`, если результат создан из приватного recipe-project (`run["private_recipe"]` / `is_private_project`). Поэтому цепочка «повтор Genjutsu → публикация результата → ещё один повтор» остаётся частично заблокированной даже после #320. | Нужен отдельный защищённый сценарий для повторно опубликованного результата с проверкой авторских media и собственным recipe, без перепродажи чужих скрытых ссылок. Проверить отдельным P1 issue/PR. |
| P1 — полный пользовательский сценарий | GitHub E2E использует synthetic provider и не подтверждает реальный input→provider payload→готовый output для каждого режима. | Матрица `original→publish→repeat→publish-repeat→repeat-again` по model/mode, variable edits и media, с authorised test tasks. |
| P2 — фото WAN на реальном iPhone | Локальный JPEG recovery после rejected complete покрыт тестами, но исходный `IMG_0729.jpeg` после релиза не был проверен на физическом устройстве. | iOS Telegram upload→complete и ручной пользовательский повтор; без платного generate на стадии проверки upload. |
| P2 — историческая документация | Release-процесс `dev→tanyapi`, systemd/старый CDN и запрет потомкам-публикациям были неверно описаны в активных docs. | Исправлены активные инструкции; provider reference и исторический audit оставлены как snapshots с явными предупреждениями. |
| P2 — инвариант цен | `data/price.json` изменяется администратором в production и должен переживать deploy без замены Git defaults. | Проверять pre/post sha256 после каждого production merge, не править runtime SQL или цены ради исправления документации. |

## Рекомендованная безопасная после-релизная проверка

1. Сверить merge SHA во всех трёх местах: checkout, OCI image, статический Mini App; health/HTTP.
2. Проверить на read-only synthetic/prod-fixture sample WAN repeat-plan: правильный выбранный source ID, source plan hash, отсутствие приватного промпта/URL в public plan и наличие заменяемых слотов.
3. Пройти по доступным видео-моделям: Genjutsu dedicated editor, Seedance typed/legacy, Kling/Grok и Motion; не выводить из отсутствия typed-схемы ложный вывод о запрете или поддержке.
4. Проверить последние callback/reconciliation/failed-upload/Telegram delivery ошибки без пользовательских секретов; тестовый `/bootstrap` без initData может отвечать `401`.
5. Точные пользовательские редакторы с replaceable slots и переменными проверить в реальном Telegram Mini App; стоимость перед подтверждением без платной отправки.
6. При выявлении дефекта открыть отдельный issue с моделью/сценарием, воспроизводимостью и task/correlation ID без копирования приватных ссылок.

**Важно:** документация и успешный CI не равны гарантии, что любая upstream модель/режим сегодня поддерживает полный повтор. Разницу между продуктовым требованием, покрытием тестами и реальным состоянием в этом отчёте запрещено скрывать.
