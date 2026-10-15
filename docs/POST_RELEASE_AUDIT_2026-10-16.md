# Production audit после исправлений опубликованных повторов

**Область:** `Bambale0/banano_kling`, ветка `tanyapi`, PR [#320](https://github.com/Bambale0/banano_kling/pull/320), merge SHA `b9f6b68dd0b23d4233c021e2c35cbbc5ccea4fe9` (2026-10-15 UTC). Проверка после фактического выката и следующий документационный PR.

> **Нельзя считать выпуск проверенным по одному факту merge.** Этот документ фиксирует наблюдения и отдельные неизвестные. Промежуточные данные заменяются проверенными после CI/deploy.

## Цель

- Убедиться, что кнопка «Повторить» на любой опубликованной фото/видео работе (исходник, тренд, ремикс, чужой повтор) открывает **именно выбранный post**, без ошибки по происхождению.
- Сохранить server-side private refs/prompt и настоящие проверки `fixed/upload`, статуса публикации, quote/debit.
- Проверить Wan 3 / Prime, generic video/Seedance, фото, прямые тренды, user-facing ошибки и Telegram callbacks.
- Сверить release infrastructure, тарифы, health, CI, логи, задачи/результаты/delivery.

## Изменение и автоматические проверки

- Код PR #320 отменяет ancestry-only запреты, переход Wan-потомка к первому тренду, проверяет private author consent по текущей опубликованной работе, сохраняя root lineage для истории. При retry фото сохраняется `private_repeat_permission_source_id`.
- До merge: регрессии опубликованных Wan trend/repeat/remix, Seedance/ordinary video callback, image nested repeats, revocation, provider/refund прошли на синтетических данных; full protected CI требуется отдельно.
- Отдельные React/Jest, TypeScript, Next.js static build, browser E2E и WAN/provider проверки требуют зелёного exact head/merge CI; их результат ниже.
- Платная provider job и реальный iPhone media-upload этим аудитом **не запускаются**.

## Production verification (заполняется по результату)

| Проверка | Результат | Доказательство |
| --- | --- | --- |
| PR #320 merge | Подтверждено | `b9f6b68…` |
| Exact-SHA GitHub CI | Ожидает финального статуса | `CI — Tanya TG Bot` после merge |
| Production deploy CI | Ожидает | `Deploy — Tanya production reliable` |
| Git HEAD = Docker revision = frontend revision | Ожидает | Публичный `/mini-app/revision.txt` и Docker labels |
| Container `healthy` и API health | Ожидает нового SHA | `/health` + Docker inspect |
| Mini App HTTP и JS | Ожидает нового SHA | HTTP status, static export |
| Runtime `data/price.json` | До выката hash `3c73a065…` | Сравнить bytes/hash до/после; учитывать параллельные admin edits |
| Read-only repeat-plan опубликованного Wan | Ожидает нового SHA | У источника `315600` именно `source_feed_gen_id=315600`, не `trend_id=2048` |
| Публичная DTO приватность | Ожидает | Нет скрытых URLs/prompts; только binding/role/index |
| Проверка разных моделей/источников | Ожидает | Агрегаты/отрицательные read-only сценарии |
| Последние логи | Ожидает | Без secrets/user media; ошибки и реальные статусы |

## Исходное read-only состояние до deploy (21:xx UTC, 2026-10-15)

- Production до применения PR #320: `209af276d05c480566018a09d6b770ba030d31c0` (совпадали Git, frontend и Docker; Docker `healthy`).
- Действующий runtime `data/price.json` имел SHA-256 `3c73a0651c6deee689ce779669faf9dd572b7ac3f09eddc200b0e26f6ef39583`.
- Среди **500 последних завершённых опубликованных видео**: Wan 3 — 33 available typed plans и **один typed-unavailable**, опубликованный результат тренда №315600. Это точная ситуация, против которой создан PR #320. После deploy обязательно подтвердить, что он стал доступным.
- Многие исторические видео Seedance и других моделей не имеют typed-descriptor: generic/legacy route может быть рабочим. `None`-дескриптор **не** доказательство неисправности повтора; нужна самостоятельная signed end-to-end проверка для разных моделей.
- История WAN upload sessions за 24 часа на старом runtime включала только `expired` сессии в выборке; это не доказывает текущую проблему загрузки и не подтверждает восстановление `IMG_0729.jpeg`.

## Известные ограничения аудита

- Числа тестов и браузерная эмуляция **не** являются проверкой качества платной генерации или полного реального пользовательского маршрута.
- Для файла `IMG_0729.jpeg` прежние попытки были rejected на финальном upload complete. Пока этот файл не загружен заново на устройстве, считать его восстановление **неподтверждённым**.
- Снятие `fixed` разрешения при уже начатой provider job не может ретроактивно остановить vendor side effect. Все новые запуски/автоповторы должны recheck.
- Отчёт по статистике может перечислять поддерживаемые модели и число доступных/недоступных descriptors, но не содержит ID пользователей, полный prompt, подписи URLs или платёжные реквизиты.

## Документационный аудит

На момент инвентаризации просмотрены 133 Markdown-файла (включая новый архивный runbook). Проверены точные relative ссылки и опасные утверждения о ветках, runtime и повторных разрешениях. Исправлены нормативные файлы: [docs index](README.md), [repeat contract](PUBLISHED_REPEAT_CONTRACT.md), [private refs](PRIVATE_REPEAT_REFERENCES.md), [Wan integration](wan3-prime-integration.md), [deploy](production_auto_deploy.md), [runbook](runbook.md), README/архитектура/QA/FSM.

В старых аудитах и `.agents/README.md` остаются **исторические** внешние root-path / line-number ссылки: их нельзя автоматически переназначить к новому коду без потери исторической привязки. Для операций использовать актуальные документы и ссылки на существующие файлы. Устаревшая инструкция `dev → tanyapi` и старый CDN/systemd runbook помечены как архив.

## Если аудит находит ошибки

Оформить отдельный reproducible issue с точным task ID, SHA, классом отказа и безопасно очищенной временной шкалой; не скрывать провайдерский 5xx сообщением об отзыве разрешения. Если точный production SHA/health/rollback не подтверждён, **не объявлять релиз закрытым**. Нерешённые P1/P2 отмечать в финальном отчёте и issue tracker.
